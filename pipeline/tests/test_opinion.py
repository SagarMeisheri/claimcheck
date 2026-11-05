"""The opinion assessment: camps, stance quotes, bias signals, the judge's output rules, and the flow. Agents and web calls are replaced."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from claimcheck.agents import opinion, sources
from claimcheck.agents.opinion import (camps_for, clean_assessment, has_verdict, pick_stance_pages, research_and_assess, verify_signals, verify_stances,
                                       wanted)
from claimcheck.agents.research import Research
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext, set_context
from claimcheck.policy import load_policy
from claimcheck.schemas import Assessment, BiasRead, BiasSignal, Source, StanceFinding, StancePlan

POLICY = load_policy()
ANSWER = "India should avoid China's mistake of aggressively flexing its muscles and picking quarrels with neighbours."
CTX = {"statement": ANSWER, "statement_type": "opinion", "question": "What should India learn from China's international relations?",
       "speaker": {"name": "Raghuram Rajan", "role": "Economist, former RBI governor", "leaning": "Described by The Hindu as a critic of the government's economic policy",
                   "leaning_basis": "described"},
       "creator": {"podcast": "TRS"}, "video": {"id": "V", "title": "Rajan interview", "channel": "TRS"}}


def src(url, rank=0, tier=3, title="Page"):
    return Source(url=url, title=title, excerpt="x", rank=rank, tier=tier)


# --- small checks ---------------------------------------------------------------------------------

def test_camps_come_from_policy_by_country_and_default_otherwise():
    assert "NDA" in camps_for(POLICY, "in")["ruling"] and "Congress" in camps_for(POLICY, "in")["opposition"]
    assert camps_for(POLICY, "zz") == camps_for(POLICY, None) and "governing" in camps_for(POLICY, None)["ruling"]


def test_the_assessment_runs_for_opinions_and_contested_answers_only_when_switched_on():
    on = Settings(research_sources=True, opinion_check=True)
    assert wanted(on, "related", "opinion") and wanted(on, "data", "forecast") and wanted(on, "contested", "factual_claim")
    assert not wanted(on, "data", "factual_claim") and not wanted(on, "skip", "opinion")
    assert not wanted(Settings(research_sources=True, opinion_check=False), "contested", "opinion")
    assert not wanted(Settings(research_sources=False, opinion_check=True), "contested", "opinion")


def test_verdict_words_are_spotted():
    assert has_verdict("This claim is false") and has_verdict("a liar") and not has_verdict("The party has stated a different position")


PAGES = [{"url": "https://party.example/a", "site": "party.example", "title": "Statement", "date": None,
          "text": "The government said it will pursue firm diplomacy while keeping trade open with its neighbours."},
         {"url": "https://opp.example/b", "site": "opp.example", "title": "Opposition", "date": "2025-01-02",
          "text": "The opposition leader said the government has been too soft in its dealings with its neighbours."}]


def sf(camp, page, stance, quote, who=""):
    return StanceFinding(camp=camp, page=page, stance=stance, quote=quote, who=who)


def test_a_camps_position_needs_a_quote_that_is_in_its_page_and_no_grading_words():
    kept, dropped = verify_stances([
        sf("ruling", 1, "Firm diplomacy with open trade.", "will pursue firm diplomacy while keeping trade open"),
        sf("opposition", 2, "Says the government is too soft.", "the government has been too soft in its dealings"),
        sf("opposition", 2, "Made up.", "this sentence is not on the page at all"),
        sf("ruling", 1, "The opposition lies about it.", "pursue firm diplomacy while keeping trade open"),
        sf("ruling", 9, "No such page.", "pursue firm diplomacy"),
    ], PAGES)
    assert [s["site"] for s in kept["ruling"]] == ["party.example"] and [s["site"] for s in kept["opposition"]] == ["opp.example"]
    assert dropped == 3


def test_a_position_from_a_page_years_old_is_not_what_a_camp_says_now():
    old = [{**PAGES[1], "date": "2010-03-08"}]
    kept, dropped = verify_stances([sf("opposition", 1, "Says the government is too soft.", "the government has been too soft in its dealings")], old)
    assert kept["opposition"] == [] and dropped == 1


def test_stance_pages_are_taken_for_each_camp_in_turn_and_at_most_two_per_camp():
    groups = {"ruling": [src(f"https://a.example/{i}", rank=i) for i in range(4)], "opposition": [src("https://b.example/x", rank=0)]}
    chosen = pick_stance_pages(groups)
    assert [s.url for s in chosen] == ["https://a.example/0", "https://a.example/1", "https://b.example/x"]


CORPUS = [ANSWER, CTX["question"], "name: Raghuram Rajan\nrole: Economist, former RBI governor\nleaning: Described by The Hindu as a critic of the government's economic policy"]


def sig(kind, text, quote):
    return BiasSignal(kind=kind, text=text, quote=quote)


def test_a_signal_stands_only_if_its_quote_is_in_the_answer_question_profile_or_findings():
    kept, dropped = verify_signals([
        sig("one_sided", "Gives only one view.", "avoid China's mistake of aggressively flexing its muscles"),
        sig("prior_stance", "Profile calls him a critic.", "Described by The Hindu as a critic of the government's economic policy"),
        sig("stake", "Works for the ruling party.", "He is a member of the ruling party and its spokesperson"),
        sig("one_sided", "Gives only one view.", "avoid China's mistake of aggressively flexing its muscles"),
        sig("loaded_language", "The speaker lies.", "avoid China's mistake of aggressively flexing"),
    ], CORPUS)
    assert [s["kind"] for s in kept] == ["one_sided", "prior_stance"] and dropped == 3


def judged(**kw):
    base = dict(bottom_line="An opinion that rests on one checkable premise; it sits closer to the opposition.", grounding="partly_backed",
                grounding_reason="One premise has an independent source.", bias="leans", toward="opposition",
                bias_reason="Matches a stated position and gives no other view.", signals=[1, 2], objection="The government says firm diplomacy works.",
                speaker_record="Described as a critic of the government's economic policy.", stake="Held a role at the RBI.", evidence="limited")
    return Assessment(**{**base, **kw})


SIGNALS = [{"kind": "one_sided", "text": "x", "quote": "q1"}, {"kind": "prior_stance", "text": "y", "quote": "q2"}]


def test_a_lean_needs_numbered_signals_to_rely_on():
    a = clean_assessment(judged(signals=[]), SIGNALS, True)
    assert a["bias"] == "cant_tell" and a["toward"] == "none"
    a = clean_assessment(judged(signals=[1, 7]), SIGNALS, True)
    assert a["bias"] == "leans" and a["toward"] == "opposition" and a["signals"] == [1]


def test_a_speakers_record_and_stake_need_a_signal_that_shows_them_and_verdict_words_are_blanked():
    a = clean_assessment(judged(signals=[1], objection="The claim is false."), SIGNALS, True)
    assert a["speaker_record"] == "" and a["stake"] == "" and a["objection"] == ""
    a = clean_assessment(judged(signals=[1, 2]), SIGNALS, True)
    assert a["speaker_record"] and a["stake"] == ""      # prior_stance is signal 2; no stake signal
    assert clean_assessment(judged(bias="balanced", toward="ruling"), SIGNALS, True)["toward"] == "none"
    assert clean_assessment(judged(), SIGNALS, False)["evidence"] == "none"


# --- the flow --------------------------------------------------------------------------------------

def make_ec(spent=0.0):
    s = Settings(research_sources=True, opinion_check=True, max_cost_usd_per_episode=3.0)
    logs = []
    ec = EpisodeContext(episode_id="e", video_id="v", settings=s, policy=POLICY, store=NS(), budget=Budget(cap_usd=3.0, spent_usd=spent), plugins_factory=lambda: [])
    ec.log = lambda *a, **k: logs.append(a)
    return ec, logs


def make_research():
    pts = [{"text": "China picked quarrels with its neighbours.", "kind": "event", "status": "same",
            "findings": [{"url": "https://news.example/c", "site": "news.example", "title": "t", "independence": "independent", "relation": "same",
                          "finding": "Reports border disputes.", "quote": "border disputes with several neighbours", "position": ""}]}]
    return Research(points=pts, positions=[], queries=["q"], related=[], counter=[], summary="s", counter_summary="", match="high")


def run_flow(monkeypatch, *, stance_error=None, bias_out="ok", judge_out="ok", research=None, spent=0.0):
    ec, logs = make_ec(spent)
    calls = {"search": [], "bias": 0, "judge": 0}

    async def fake_research(ctx, location):
        return research or make_research()

    async def fake_plan(ctx, camps):
        if stance_error:
            raise stance_error
        return StancePlan(issue="How firmly India should deal with its neighbours.", ruling_queries=["government diplomacy neighbours policy", "foreign policy neighbours trade"],
                          opposition_queries=["opposition foreign policy neighbours", "opposition criticises government neighbours"])

    async def fake_search(queries, objective, location):
        calls["search"].append(queries)
        return [src("https://party.example/a")] if "government" in queries[0] else [src("https://opp.example/b")]

    async def fake_fetch(chosen, points, positions):
        return [p for p in PAGES if any(p["url"] == s.url for s in chosen)]

    async def fake_read(issue, camps, pages):
        return [sf("ruling", 1, "Firm diplomacy with open trade.", "will pursue firm diplomacy while keeping trade open"),
                sf("opposition", 2, "Says the government is too soft.", "the government has been too soft in its dealings")]

    async def fake_bias(state):
        calls["bias"] += 1
        if bias_out == "error":
            raise RuntimeError("boom")
        return BiasRead(signals=[sig("one_sided", "Gives only one view.", "avoid China's mistake of aggressively flexing its muscles"),
                                 sig("stake", "Invented.", "He chairs the ruling party's economic cell")], matches="opposition")

    async def fake_judge(state):
        calls["judge"] += 1
        return None if judge_out == "none" else judged(signals=[1, 2], speaker_record="")

    monkeypatch.setattr(opinion, "research_answer", fake_research)
    monkeypatch.setattr(opinion, "_stance_plan", fake_plan)
    monkeypatch.setattr(opinion, "_search", fake_search)
    monkeypatch.setattr(opinion, "_fetch", fake_fetch)
    monkeypatch.setattr(opinion, "_stance_read", fake_read)
    monkeypatch.setattr(opinion, "_bias", fake_bias)
    monkeypatch.setattr(opinion, "_judge", fake_judge)

    async def go():
        token = set_context(ec)
        try:
            return await research_and_assess(CTX, "contested", "in")
        finally:
            token.var.reset(token)

    return asyncio.run(go()), calls, logs


def test_the_flow_puts_both_camps_the_checked_signals_and_the_assessment_on_the_research(monkeypatch):
    r, calls, _ = run_flow(monkeypatch)
    op = r.stored()["opinion"]
    assert op["stances"]["ruling"][0]["site"] == "party.example" and op["stances"]["opposition"][0]["site"] == "opp.example"
    assert op["issue"].startswith("How firmly") and op["matches"] == "opposition"
    assert [s["kind"] for s in op["signals"]] == ["one_sided"]                   # the invented stake quote is dropped
    a = op["assessment"]
    assert a["bias"] == "leans" and a["toward"] == "opposition" and a["signals"] == [1]
    assert a["grounding"] == "partly_backed" and a["stake"] == "" and a["evidence"] == "limited"
    assert len(calls["search"]) == 2 and calls["bias"] == 1 and calls["judge"] == 1   # one search per camp, then bias, then the judge


def test_without_stances_the_bias_agent_and_judge_still_run_and_the_failure_is_logged(monkeypatch):
    r, calls, logs = run_flow(monkeypatch, stance_error=RuntimeError("search down"))
    op = r.stored()["opinion"]
    assert op["stances"] == {"ruling": [], "opposition": []} and calls["judge"] == 1
    assert any(l[1] == "stance_failed" for l in logs)


def test_a_failing_bias_agent_or_judge_leaves_the_research_without_an_assessment(monkeypatch):
    r, _, logs = run_flow(monkeypatch, bias_out="error")
    assert "opinion" not in r.stored() and r.summary == "s" and any(l[1] == "assessment_failed" for l in logs)
    r, _, _ = run_flow(monkeypatch, judge_out="none")
    assert "opinion" not in r.stored()


def test_a_budget_error_in_the_stance_agent_stops_the_lookup(monkeypatch):
    with pytest.raises(BudgetExceeded):
        run_flow(monkeypatch, stance_error=BudgetExceeded("cap"))


def test_gather_sources_uses_the_assessment_for_opinions_and_plain_research_otherwise(monkeypatch):
    ec, _ = make_ec()
    seen = []

    async def fake_assess(ctx, route, location):
        seen.append("assess")
        return make_research()

    async def fake_research(ctx, location):
        seen.append("research")
        return make_research()

    monkeypatch.setattr(opinion, "research_and_assess", fake_assess)
    from claimcheck.agents import research as R
    monkeypatch.setattr(R, "research_answer", fake_research)

    async def go(ctx, route):
        token = set_context(ec)
        try:
            return await sources.gather_sources(ctx, route, "in")
        finally:
            token.var.reset(token)

    asyncio.run(go(CTX, "related"))
    asyncio.run(go({**CTX, "statement_type": "factual_claim"}, "data"))
    assert seen == ["assess", "research"]
