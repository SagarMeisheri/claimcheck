"""The answer-tag Workflow (agents/qa_tags.py): routing by claim type, what each call sees, and the skepticism rules. The classifier
and the research are replaced; no keys or network."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from google.adk.labs.classifiers import BinaryAnswer, ChoiceAnswer, ClassifierResponse

from claimcheck.agents import qa_tags, research
from claimcheck.agents.research import Research
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext, set_context


def ch(label, opts, p=0.8):
    rest = (1 - p) / (len(opts) - 1)
    return ChoiceAnswer(choice=label, probabilities={o: (p if o == label else rest) for o in opts})


def yes(p=0.9):
    return BinaryAnswer(probability=p)


def page(site="news.example", independence="independent"):
    return {"url": f"https://{site}/a", "site": site, "title": "t", "date": "2026-01-01", "independence": independence, "text": "excerpt"}


def make_research(pages):
    r = Research(points=[{"text": "A point.", "kind": "figure", "status": "sources_found"}], positions=[], queries=["q"], related=[],
                 counter=[], summary="", counter_summary="", match="medium")
    r.all_pages = pages
    return r


CTX = {"statement": "Black Myth: Wukong cost at least $70 million.", "context_quote": "Wukong was seventy million...",
       "question": "How much does a game cost?", "question_spoken": "My only question is, how much money does it take?",
       "question_kind": "asked", "asked_by": "Vinamre Kasanaa",
       "speaker": {"name": "Varun Mayya", "role": "Co-founder of Aeos", "businesses": [{"name": "Aeos", "relation": "founder", "url": "https://a.example"}]}}


def run(monkeypatch, answers, ctx=CTX, pages=(page(),), points=True, fail=(), boom=None, settings=None, spent=0.0):
    """Runs tag_answer with `answers` as every question's answer. Returns (tags, research, calls, ec)."""
    calls = []

    async def classify(names, payload):
        calls.append((tuple(names), payload))
        if boom:
            raise boom
        if set(names) & set(fail):
            raise RuntimeError("model down")
        return ClassifierResponse(answers={n: answers[n] for n in names if n in answers})

    async def fake_research(ctx, location, force=False):
        return make_research(list(pages)) if points else None

    monkeypatch.setattr(qa_tags, "_classify", classify)
    monkeypatch.setattr(research, "research_answer", fake_research)
    ec = EpisodeContext(episode_id="e", video_id="v", settings=settings or Settings(max_cost_usd_per_episode=3.0), policy={}, store=NS(),
                        budget=Budget(cap_usd=3.0, spent_usd=spent), plugins_factory=lambda: [])

    async def go():
        token = set_context(ec)
        try:
            return await qa_tags.tag_answer(ctx, None)
        finally:
            token.var.reset(token)

    t = asyncio.run(go())
    return t.tags, t.research, calls, ec


BASE = {"answer_type": ch("evasive", qa_tags.ATYPES), "claim_type": ch("objective_fact", qa_tags.CTYPES),
        "grounding": ch("grounded", qa_tags.GROUNDING), "match": ch("high", qa_tags.MATCH)}


def test_a_researched_answer_costs_two_calls_and_gets_the_chain(monkeypatch):
    tags, r, calls, _ = run(monkeypatch, BASE)
    assert [c[0] for c in calls] == [("answer_type", "claim_type"), ("grounding", "match")]
    assert tags["answer"]["type"] == "evasive" and tags["claim"]["type"] == "objective_fact" and tags["grounding"]["label"] == "grounded"
    assert tags["chain"] == "Evasive A → Objective fact → Grounded" and tags["grounding"]["evidence"] == "limited" and r.match == "high"


def test_a_pure_opinion_is_exempt_with_one_call_and_no_search(monkeypatch):
    tags, r, calls, _ = run(monkeypatch, {**BASE, "claim_type": ch("pure_opinion", qa_tags.CTYPES, 0.9)})
    assert len(calls) == 1 and r is None and tags["grounding"]["label"] == "exempt" and tags["chain"].endswith("Pure opinion → Exempt")


def test_an_unsure_pure_opinion_is_researched_after_all(monkeypatch):
    tags, r, calls, _ = run(monkeypatch, {**BASE, "claim_type": ch("pure_opinion", qa_tags.CTYPES, 0.5)})
    assert r is not None and len(calls) == 2 and tags["grounding"]["label"] == "grounded"


def test_nothing_checkable_makes_a_prediction_exempt_and_a_fact_plausible(monkeypatch):
    tags, r, _, _ = run(monkeypatch, {**BASE, "claim_type": ch("prediction", qa_tags.CTYPES)}, points=False)
    assert r is None and tags["grounding"]["label"] == "exempt"
    tags, _, _, _ = run(monkeypatch, BASE, points=False)
    assert tags["grounding"]["label"] == "plausible"  # the speaker's own history: no public record


def test_the_answer_call_never_carries_conflict_questions_for_a_speaker_with_no_stake(monkeypatch):
    _, _, calls, _ = run(monkeypatch, BASE)
    assert "speaker_interests" not in calls[0][1] and "pages" not in calls[0][1]
    assert calls[0][1]["question_as_asked"] == CTX["question_spoken"] and calls[0][1]["spoken_words"].startswith("Wukong")


STAKE = {**CTX, "speaker_incentives": {"commercial": {"reason": "Founder of Aeos"}}}


def test_rule_1_a_self_serving_claim_with_no_independent_page_is_ungrounded(monkeypatch):
    ans = {**BASE, "answer_type": ch("narrative", qa_tags.ATYPES), "claim_type": ch("anchored_opinion", qa_tags.CTYPES),
           "grounding": ch("plausible", qa_tags.GROUNDING), "self_serving": yes(), "disclosed": yes(0.8)}
    tags, _, calls, _ = run(monkeypatch, ans, ctx=STAKE, pages=[page("aeos.example", "own_organisation")])
    assert calls[0][0] == ("answer_type", "claim_type", "self_serving", "self_serving_pivot", "disclosed")
    assert "Aeos" in str(calls[0][1]["speaker_interests"])
    assert tags["grounding"]["label"] == "ungrounded" and tags["grounding"]["was"] == "plausible"
    assert tags["conflict"] == {"kind": "self_report", "disclosure": "disclosed"}
    assert tags["chain"] == "Narrative A → Anchored opinion → Ungrounded (self-report, disclosed)"


def test_rule_1_an_independent_page_keeps_a_grounded_self_serving_claim(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**BASE, "self_serving": yes(), "disclosed": yes(0.2)}, ctx=STAKE,
                        pages=[page("aeos.example", "own_organisation"), page("reuters.example")])
    assert tags["grounding"]["label"] == "grounded" and tags["conflict"]["disclosure"] == "undisclosed"


def test_rule_2_missing_context_is_asked_only_of_ideological_or_financial_speakers_and_kept_as_a_flag(monkeypatch):
    ideo = {**CTX, "speaker_incentives": {"ideological": {}}}
    tags, _, calls, _ = run(monkeypatch, {**BASE, "missing_context": yes()}, ctx=ideo)
    assert calls[1][0] == ("grounding", "match", "missing_context")
    assert tags["grounding"]["label"] == "grounded" and tags["flags"] == ["missing_context"]
    assert tags["chain"].endswith("Grounded (missing context)")
    _, _, calls, _ = run(monkeypatch, BASE)
    assert calls[1][0] == ("grounding", "match")


def test_a_self_serving_pivot_counts_only_for_a_pivot(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**BASE, "self_serving_pivot": yes()}, ctx=STAKE)
    assert "conflict" not in tags  # evasive, not a pivot
    tags, _, _, _ = run(monkeypatch, {**BASE, "answer_type": ch("pivot", qa_tags.ATYPES), "self_serving_pivot": yes()}, ctx=STAKE)
    assert tags["flags"] == ["self_serving_pivot"] and tags["conflict"]["kind"] == "self_serving_pivot"


def test_staged_pushback_is_asked_only_when_the_host_is_tagged_soft(monkeypatch):
    soft = {**CTX, "host_incentives": {"invested_peer": {}}, "host": {"name": "Host"}}
    tags, _, calls, _ = run(monkeypatch, {**BASE, "staged_pushback": yes()}, ctx=soft)
    assert "staged_pushback" in calls[0][0] and "host_interests" in calls[0][1] and tags["flags"] == ["staged_pushback"]
    _, _, calls, _ = run(monkeypatch, BASE, ctx={**CTX, "host_incentives": {"adversarial": {}}})
    assert "staged_pushback" not in calls[0][0]


def test_the_evidence_rules_still_hold(monkeypatch):
    assert run(monkeypatch, {**BASE, "grounding": ch("contradicted", qa_tags.GROUNDING, 0.5)})[0]["grounding"]["label"] == "plausible"
    assert run(monkeypatch, {**BASE, "grounding": ch("contradicted", qa_tags.GROUNDING, 0.7)})[0]["grounding"]["label"] == "contradicted"
    assert run(monkeypatch, BASE, pages=())[0]["grounding"]["label"] == "plausible"  # grounded needs a page
    t = run(monkeypatch, {**BASE, "grounding": ch("plausible", qa_tags.GROUNDING)})[0]
    assert t["match"]["label"] == "medium"  # pages that settle nothing can't be a direct match
    assert run(monkeypatch, {**BASE, "answer_type": ch("pivot", qa_tags.ATYPES, 0.3)})[0]["answer"]["type"] == "unclear"


def test_a_failed_call_is_left_out_and_routes_to_research(monkeypatch):
    tags, r, _, ec = run(monkeypatch, BASE, fail=("answer_type",))
    assert r is not None and "answer" not in tags and "claim" not in tags and tags["grounding"]["label"] == "grounded"
    assert tags["failed"] == ["answer_type", "claim_type"] and any(e.rule == "tag_failed" for e in ec.events)


def test_a_budget_error_is_never_swallowed(monkeypatch):
    with pytest.raises(BudgetExceeded):
        run(monkeypatch, BASE, boom=BudgetExceeded("cap"))


def test_with_tags_off_the_answer_is_only_researched(monkeypatch):
    tags, r, calls, _ = run(monkeypatch, BASE, settings=Settings(tag_answers=False))
    assert tags is None and r is not None and calls == []


def test_a_research_failure_reaches_the_caller_as_itself(monkeypatch):
    async def down(ctx, location, force=False):
        raise research.ResearchUnavailable("every search failed")

    monkeypatch.setattr(research, "research_answer", down)
    monkeypatch.setattr(qa_tags, "_classify", lambda names, payload: _answer_with(names))
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(), policy={}, store=NS(), budget=Budget(cap_usd=3.0), plugins_factory=lambda: [])

    async def go():
        token = set_context(ec)
        try:
            await qa_tags.tag_answer(CTX, None)
        finally:
            token.var.reset(token)

    with pytest.raises(research.ResearchUnavailable):
        asyncio.run(go())


async def _answer_with(names):
    return ClassifierResponse(answers={n: BASE[n] for n in names if n in BASE})
