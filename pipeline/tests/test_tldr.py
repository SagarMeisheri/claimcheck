"""The podcast profile's TL;DRs (agents/tldr.py): what code counts for the digest, what is kept from the model's sentences, and when it
is written. The model call is replaced; no keys or network."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from claimcheck.agents import tldr
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext, set_context
from claimcheck.schemas import PersonTldr, TldrOut


def claim(start, q, label, *, qtype="factual", atype="direct", stype="factual_claim", **extra):
    grounding = {"label": label, "basis": [{"finding": "A page title"}]} if label else None
    return {"start_s": start, "speaker": "Guest", "claim_text": f"Answer at {start}", "statement_type": stype, "question": q, "question_kind": "asked",
            "question_analysis": {"type": qtype}, "not_checked_reason": None,
            "qa_tags": {"answer": {"type": atype}, **({"grounding": grounding} if grounding else {}), **extra}}


CLAIMS = [
    claim(60, "How much revenue is needed?", "contradicted", qtype="evaluative", atype="pivot",
          conflict={"kind": "self_report", "disclosure": "undisclosed"}, stake={"link": "benefits"}),
    claim(130, "What happens next?", "grounded", qtype="speculative", stype="forecast", flags=["missing_context"]),
    claim(200, "What happens next?", "plausible", qtype="speculative", stype="opinion"),  # a second answer to the same question
    {**claim(300, "Hidden?", "grounded"), "not_checked_reason": "outside_policy"},
    {**claim(400, "Implied", None), "question_kind": "implied"},
]
SPEAKERS = [
    {"label": "Guest", "role": "guest", "statements": 3, "incentives": {"commercial": {"reason": "Sells a book."}, "access_preserving": {"reason": "hidden"}},
     "speakers": {"name": "Ada Guest", "summary": "A professor.", "public_profile": {"role": "Professor of finance", "businesses": [{"name": "Acme"}], "critiques": [{}, {}]}}},
    {"label": "Host", "role": "host", "statements": 0, "incentives": {}, "speakers": None},
]
CREATOR = {"podcast": "The Show", "summary": "Interviews.", "public_profile": {"known_for": "Long interviews", "incentives": {}}}
EP = {"title": "A talk", "interaction": {"dynamic": "neutral", "description_notes": ["n"]}}


def test_the_digest_is_counted_in_code():
    d = tldr.build_digest(EP, CLAIMS, SPEAKERS, CREATOR)
    assert d["answers"] == 4 and d["interview_dynamic"] == "neutral"       # the redacted answer is left out
    assert d["question_types"] == {"evaluative": 1, "speculative": 1}       # one per distinct asked question; implied ones don't count
    assert d["answer_types"] == {"pivot": 1, "direct": 3} and d["evidence"] == {"contradicted": 1, "grounded": 1, "plausible": 1}
    assert d["statement_types"]["forecast"] == 1 and d["conflicts_of_interest"] == 1 and d["stakes_found"] == 1 and d["undisclosed"] == 1
    assert d["flags"] == {"missing_context": 1}
    assert d["contradicted_or_ungrounded"] == [{"time": "1:00", "verdict": "contradicted", "question": "How much revenue is needed?",
                                                 "said": "Answer at 60", "difference": "A page title"}]


def test_the_people_come_hosts_first_with_their_stakes_and_the_show_last():
    people = tldr.build_digest(EP, CLAIMS, SPEAKERS, CREATOR)["people"]
    assert [p["label"] for p in people] == ["Host", "Guest", "__show"]
    guest = people[1]
    assert guest["name"] == "Ada Guest" and guest["about"] == "Professor of finance" and guest["businesses"] == ["Acme"] and guest["criticism_reported"] == 2
    assert guest["stakes"] == [{"tag": "commercial", "why": "Sells a book."}]    # internal tags are never offered
    assert people[0]["name"] == "Host" and people[2]["about"] == "Long interviews"


def test_counts_record_what_the_sentences_were_written_from():
    assert tldr.counts_of(CLAIMS) == {"answers": 4, "contradicted": 1, "ungrounded": 0, "plausible": 1, "grounded": 1, "exempt": 0}


GOOD = TldrOut(headline="A talk on AI valuations.", questions="Mostly what-if questions.", answers="Mostly direct.", statements="One forecast.",
               evidence="One answer contradicted: revenue.", flags="One undisclosed conflict.",
               people=[PersonTldr(label="Guest", tldr="A professor who sells a book."), PersonTldr(label="Nobody", tldr="Not in the digest.")])


def test_only_whole_sets_of_sentences_are_kept_and_unknown_people_dropped():
    d = tldr.build_digest(EP, CLAIMS, SPEAKERS, CREATOR)
    out = tldr.check(GOOD, d, {"answers": 4})
    assert out["headline"] == "A talk on AI valuations." and out["people"] == {"Guest": "A professor who sells a book."} and out["counts"] == {"answers": 4}
    assert tldr.check(GOOD.model_copy(update={"evidence": "  "}), d, {}) is None and tldr.check(None, d, {}) is None


class FakeStore:
    def __init__(self):
        self.updates = []

    async def get_episode(self, episode_id):
        return {**EP, "id": episode_id, "creator_id": "c"}

    async def list_claims_for_tldr(self, episode_id):
        return CLAIMS

    async def get_episode_speakers(self, episode_id):
        return SPEAKERS

    async def get_creator(self, creator_id):
        return CREATOR

    async def update_episode(self, episode_id, fields):
        self.updates.append(fields)


def run(coro_fn, monkeypatch, out, *, settings=None, spent=0.0):
    seen = []

    async def gen(digest):
        seen.append(digest)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(tldr, "_generate", gen)
    store = FakeStore()
    ec = EpisodeContext(episode_id="e", video_id="v", settings=settings or Settings(max_cost_usd_per_episode=3.0), policy={}, store=store,
                        budget=Budget(cap_usd=3.0, spent_usd=spent), plugins_factory=lambda: [])

    async def go():
        token = set_context(ec)
        try:
            return await coro_fn(store)
        finally:
            token.var.reset(token)

    return asyncio.run(go()), store, seen, ec


def test_refreshing_saves_next_to_the_existing_interaction(monkeypatch):
    _, store, seen, _ = run(lambda st: tldr.refresh_tldr(st, "e"), monkeypatch, GOOD)
    saved = store.updates[0]["interaction"]
    assert saved["dynamic"] == "neutral" and saved["description_notes"] == ["n"] and saved["tldr"]["headline"] == "A talk on AI valuations."
    assert len(seen) == 1 and saved["tldr"]["counts"]["answers"] == 4


def test_a_failed_call_or_a_budget_error_never_reaches_the_lookup(monkeypatch):
    for boom in (RuntimeError("down"), BudgetExceeded("cap")):
        _, store, _, _ = run(lambda st: tldr.refresh_tldr(st, "e"), monkeypatch, boom)
        assert store.updates == []


def test_it_is_skipped_when_off_or_when_the_budget_has_no_room(monkeypatch):
    _, store, seen, _ = run(lambda st: tldr.refresh_tldr(st, "e"), monkeypatch, GOOD, settings=Settings(tldr=False))
    assert store.updates == [] and seen == []
    _, store, seen, _ = run(lambda st: tldr.refresh_tldr(st, "e"), monkeypatch, GOOD, spent=2.995)
    assert store.updates == [] and seen == []


def test_make_tldr_raises_a_budget_error_and_logs_a_failed_call(monkeypatch):
    with pytest.raises(BudgetExceeded):
        run(lambda st: tldr.make_tldr(st, "e"), monkeypatch, BudgetExceeded("cap"))
    result, _, _, ec = run(lambda st: tldr.make_tldr(st, "e"), monkeypatch, RuntimeError("down"))
    assert result is None and any(e.rule == "tldr_failed" for e in ec.events)


def test_unchallenged_opinions_are_found_from_the_next_question():
    a = {**claim(60, "Q1?", "plausible", qtype="evaluative"), "qa_tags": {"claim": {"type": "anchored_opinion"}, "grounding": {"label": "plausible"}}}
    b = {**claim(120, "Q2?", "grounded", qtype="factual"), "qa_tags": {"claim": {"type": "anchored_opinion"}, "grounding": {"label": "grounded"}}}
    c = {**claim(200, "Q3?", "plausible", qtype="challenging"), "qa_tags": {"claim": {"type": "anchored_opinion"}, "grounding": {"label": "plausible"}}}
    d = {**claim(260, "Q4?", "plausible", qtype="evaluative"), "qa_tags": {"claim": {"type": "anchored_opinion"}, "grounding": {"label": "plausible"}}}
    # a: next question (Q2) is not a challenge -> flagged; b: grounded; c: next (Q4) isn't a challenge -> flagged; d: last answer, no next question
    assert tldr.unchallenged([a, b, c, d]) == ["1:00", "3:20"]
    assert tldr.build_digest(EP, [a, b, c, d], [], None)["unchallenged_opinions_at"] == ["1:00", "3:20"]
