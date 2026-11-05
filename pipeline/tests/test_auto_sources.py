"""Automatic source checking as answers are found: which answers start a lookup, the limits, and what is saved. No keys or network."""

import asyncio
from types import SimpleNamespace as NS

from claimcheck.agents import sources
from claimcheck.agents.sources import AutoSources, Digest, Lookup, VideoContext
from claimcheck.agents.stages import build_record
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext
from claimcheck.policy import load_policy
from claimcheck.tools.evidence import related_objective

POLICY = load_policy()


def answer(i, **kw):
    raw = {"start_ts": f"{i + 1}:00", "question": "How was NPCI funded?", "question_kind": "asked", "asked_by": "Host",
           "speaker": "Sohini Rajola", "claim": f"NPCI was funded with Rs {100 + i} crore.", "context_quote": "...",
           "statement_context": "NPCI", "statement_type": "factual_claim", "pestle_area": "economic", "topics": ["npci"],
           "policy_tier": "normal", **kw}
    return build_record(i, raw, NS(policy=POLICY, listed_people=[], creator=None, log=lambda *a, **k: None), log=False)


class Store:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.status = []  # (claim id, status) in order
        self.saved = []

    async def get_claim_row(self, episode_id, idx):
        return self.rows.get(idx, {"id": f"id{idx}", "idx": idx, "claim_text": f"answer {idx}", "statement_type": "factual_claim",
                                   "sources_status": "not_requested", "start_s": 60})

    async def set_sources_status(self, claim_id, status, error=None):
        self.status.append((claim_id, status))

    async def get_episode(self, episode_id):
        return {"id": episode_id, "youtube_video_id": "VID123", "title": "The episode"}

    async def get_creator(self, creator_id):
        return None

    async def get_episode_speakers(self, episode_id):
        return []


def make(settings=None, store=None, spent=0.0):
    settings = settings or Settings(auto_sources_as_found=True, max_cost_usd_per_episode=3.0)
    store = store or Store()
    ec = EpisodeContext(episode_id="ep1", video_id="v", settings=settings, policy=POLICY, store=store,
                        budget=Budget(cap_usd=settings.max_cost_usd_per_episode, spent_usd=spent), plugins_factory=lambda: [])
    return AutoSources(ec), store


def run(auto, recs):
    async def go():
        for r in recs:
            auto.submit(r)
        await auto.drain()
    asyncio.run(go())


def patch_lookup(monkeypatch, route="related", fail=None, calls=None):
    async def lookup(claim, vctx, *, force):
        if calls is not None:
            calls.append(claim["id"])
        if fail:
            raise fail
        return Lookup(route, [], [], None), Digest("A summary.", "high", "")

    async def save(store, claim_id, found, digest):
        store.saved.append((claim_id, found.route))

    monkeypatch.setattr(sources, "_lookup_and_summarize", lookup)
    monkeypatch.setattr(sources, "_save", save)


def test_each_answer_starts_a_lookup_and_is_saved(monkeypatch):
    calls = []
    patch_lookup(monkeypatch, calls=calls)
    auto, store = make()
    run(auto, [answer(0), answer(1)])
    assert sorted(calls) == ["id0", "id1"]
    assert sorted(store.saved) == [("id0", "related"), ("id1", "related")]
    assert ("id0", "searching") in store.status  # shown as searching straight away


def test_stories_questions_and_redacted_answers_are_never_looked_up(monkeypatch):
    calls = []
    patch_lookup(monkeypatch, calls=calls)
    auto, _ = make()
    run(auto, [answer(0, statement_type="story"), answer(1, statement_type="question"), answer(2, policy_tier="never")])
    assert calls == [] and auto.started == 0


def test_a_skip_from_the_classifier_is_saved_as_a_skip(monkeypatch):
    patch_lookup(monkeypatch, route="skip")
    auto, store = make()
    run(auto, [answer(0)])
    assert store.saved == [("id0", "skip")]


def test_at_most_the_streaming_budget_pays_for_lookups_start_during_extraction(monkeypatch):
    calls = []
    patch_lookup(monkeypatch, calls=calls)
    each = Settings().lookup_cost_estimate_usd
    settings = Settings(auto_sources_as_found=True, max_cost_usd_per_episode=3.0, auto_sources_stream_budget_usd=each * 2.5)
    assert settings.max_streamed_lookups == 2
    auto, _ = make(settings)
    run(auto, [answer(i) for i in range(6)])
    assert len(calls) == 2
    assert Settings(auto_sources_as_found=True, auto_sources_stream_budget_usd=0).max_streamed_lookups == 0


def test_nothing_starts_when_the_video_budget_is_used_up(monkeypatch):
    calls = []
    patch_lookup(monkeypatch, calls=calls)
    auto, store = make(spent=3.0)
    run(auto, [answer(0)])
    assert calls == [] and store.status == []


def test_an_answer_that_already_has_sources_is_not_looked_up_again(monkeypatch):
    calls = []
    patch_lookup(monkeypatch, calls=calls)
    auto, _ = make(store=Store({0: {"id": "id0", "idx": 0, "claim_text": "x", "sources_status": "done"}}))
    run(auto, [answer(0)])
    assert calls == []


def test_a_failed_lookup_is_marked_failed_and_the_others_carry_on(monkeypatch):
    patch_lookup(monkeypatch, fail=RuntimeError("search down"))
    auto, store = make()
    run(auto, [answer(0), answer(1)])
    assert ("id0", "failed") in store.status and ("id1", "failed") in store.status and store.saved == []


def test_a_budget_error_gives_the_answer_back_to_the_button(monkeypatch):
    patch_lookup(monkeypatch, fail=BudgetExceeded("cap"))
    auto, store = make()
    run(auto, [answer(0)])
    assert store.status[-1] == ("id0", "not_requested")


def test_cancelling_leaves_nothing_stuck_searching(monkeypatch):
    async def slow(claim, vctx, *, force):
        await asyncio.sleep(10)

    monkeypatch.setattr(sources, "_lookup_and_summarize", slow)
    auto, store = make()

    async def go():
        auto.submit(answer(0))
        await asyncio.sleep(0.05)
        await auto.cancel()

    asyncio.run(go())
    assert store.status[0] == ("id0", "searching") and store.status[-1] == ("id0", "not_requested")


def test_the_question_reaches_the_classifier_and_the_search():
    vctx = VideoContext(NS(), {"id": "ep1"})
    ctx = vctx.for_claim({"claim_text": "NPCI was funded with Rs 100 crore.", "statement_type": "factual_claim", "question": "How was NPCI funded?"})
    assert ctx["question"] == "How was NPCI funded?"
    assert 'In answer to: "How was NPCI funded?"' in related_objective(ctx["statement"], ctx)
    assert "In answer to" not in related_objective("A statement.", {})


def test_either_switch_turns_automatic_checking_on():
    assert not Settings(auto_sources=False, auto_sources_as_found=False).auto_sources_enabled
    assert Settings(auto_sources=True).auto_sources_enabled
    assert Settings(auto_sources_as_found=True).auto_sources_enabled


def test_an_answer_waiting_for_a_free_slot_already_shows_as_searching(monkeypatch):
    release = None

    async def lookup(claim, vctx, *, force):
        await release.wait()
        return Lookup("related", [], [], None), Digest()

    async def save(store, claim_id, found, digest):
        store.saved.append((claim_id, found.route))

    monkeypatch.setattr(sources, "_lookup_and_summarize", lookup)
    monkeypatch.setattr(sources, "_save", save)
    auto, store = make(Settings(auto_sources_as_found=True, max_cost_usd_per_episode=3.0, sources_concurrency=1))

    async def go():
        nonlocal release
        release = asyncio.Event()
        auto.submit(answer(0))
        auto.submit(answer(1))
        await asyncio.sleep(0.05)
        waiting = list(store.status)  # one holds the only slot, the other is queued behind it
        release.set()
        await auto.drain()
        return waiting

    waiting = asyncio.run(go())
    assert ("id0", "searching") in waiting and ("id1", "searching") in waiting
    assert sorted(store.saved) == [("id0", "related"), ("id1", "related")]
