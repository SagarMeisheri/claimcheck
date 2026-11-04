"""Sources: one Parallel search per claim, results used as returned. No keys or network: a fake Parallel client."""

import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from claimcheck.agents import sources
from claimcheck.agents.sources import precheck, run_claim_sources, run_video_sources
from claimcheck.config import Settings
from claimcheck.policy import load_policy
from claimcheck.tools import evidence
from claimcheck.tools.evidence import best_excerpt, clean_excerpt, search_sources, to_sources

POLICY = load_policy()
SETTINGS = Settings(max_cost_usd_per_episode=3.0, sources_per_claim=5, sources_concurrency=3, search_cost_usd=0.005,
                    summarize_sources=False, triage_sources=False)  # summaries and triage: see the tests at the end


def hit(url, title="t", excerpts=("Some text from the page.",), date=None):
    return NS(url=url, title=title, excerpts=list(excerpts), publish_date=date)


# --- One search ------------------------------------------------------------------------------------
class FakeParallel:
    def __init__(self, results=(), fail=False, delay=0.0):
        self.results, self.fail, self.delay, self.calls = list(results), fail, delay, []

    def search(self, **kw):
        self.calls.append(kw)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("parallel down")
        return NS(results=self.results)


def test_every_result_is_used_in_parallels_order_with_a_label_only(monkeypatch):
    results = [hit("https://www.moneycontrol.com/a", "Moneycontrol", ["India accounts for roughly **3%** of global market cap."], "2026-09-10"),
               hit("https://www.livemint.com/b", "Mint"),
               hit("https://en.wikipedia.org/wiki/X", "Wikipedia"),
               hit("https://www.livemint.com/b", "duplicate"),
               hit("https://mospi.gov.in/c", "MoSPI", []),
               hit("https://someblog.in/d"), hit("https://another.example/e"), hit("https://sixth.example/f")]
    fake = FakeParallel(results)
    monkeypatch.setattr(evidence, "_client", lambda s: fake)
    got = asyncio.run(search_sources("India represents only 3% of the world's stock market value.", SETTINGS, POLICY))
    # Nothing filtered by site: blogs and Wikipedia stay, in Parallel's order; only duplicates are dropped; at most 5.
    assert [s.url for s in got] == ["https://www.moneycontrol.com/a", "https://www.livemint.com/b", "https://en.wikipedia.org/wiki/X",
                                    "https://mospi.gov.in/c", "https://someblog.in/d"]
    assert [s.tier for s in got] == [3, 2, 3, 1, 3] and [s.rank for s in got] == [0, 1, 2, 3, 4]
    assert got[0].excerpt == "India accounts for roughly 3% of global market cap." and got[0].publish_date == "2026-09-10"
    assert got[3].excerpt == ""  # no excerpt is fine: the link is still shown
    # The claim's own words are the query; social media and video sites are excluded in the request itself.
    call = fake.calls[0]
    assert call["search_queries"] == ["India represents only 3% of the world's stock market value."]
    assert "youtube.com" in call["advanced_settings"]["source_policy"]["exclude_domains"]
    assert call["mode"] == "fast"


def test_pdf_layout_junk_is_removed_from_titles():
    assert evidence.clean_title("-1cmMacroeconomic Implications of COVID-19: Can Negative Supply Shocks Cause Demand Shortages?1cm") == \
        "Macroeconomic Implications of COVID-19: Can Negative Supply Shocks Cause Demand Shortages?"
    assert evidence.clean_title("Rainfall of 10cm expected in Mumbai") == "Rainfall of 10cm expected in Mumbai"


def test_excerpts_are_cleaned_and_shortened():
    assert clean_excerpt("## Title\n\nSee [the report](https://x.y/z) for **details**.", 200) == "Title See the report for details."
    long = clean_excerpt("word " * 200, 50)
    assert len(long) <= 51 and long.endswith("…")


def test_the_excerpt_is_the_passage_about_the_claim_not_the_page_menu():
    page = ["Home Markets Indigo Share Price Equitas SFB Share Price Suzlon Energy Share Price NSE Share Price. "
            "Passive funds under-allocate India. India accounts for roughly 3% of global market capitalisation and nominal GDP. "
            "Subscribe to our newsletter for more."]
    got = best_excerpt(page, "India represents only 3% of the world's stock market value.", 200)
    assert got.startswith("India accounts for roughly 3% of global market capitalisation")
    assert best_excerpt([], "x", 100) == "" and best_excerpt(["Short."], "x", 100) == "Short."


def test_no_results_means_an_empty_list():
    assert to_sources([], POLICY, 5, 300) == []


# --- One claim ---------------------------------------------------------------------------------------
def row(**kw):
    base = {"id": "c1", "idx": 3, "episode_id": "e1", "start_s": 60, "claim_text": "GDP grew 7.4%", "statement_type": "factual_claim",
            "policy_tier": "normal", "not_checked_reason": None, "sources_status": "queued",
            "episodes": {"id": "e1", "youtube_video_id": "vid", "title": "T", "status": "done", "cost_usd": 0.5}}
    eps = kw.pop("episodes", {})
    base.update(kw)
    base["episodes"] = {**base["episodes"], **eps}
    return base


class FakeStore:
    def __init__(self, r=None, batch=()):
        self.row, self.batch = r, list(batch)
        self.saved, self.status, self.cost, self.updates = {}, {}, [], []

    async def get_claim_for_sources(self, claim_id):
        return self.row

    async def get_episode(self, eid):
        return {"id": eid, "status": "done", "cost_usd": 0}

    async def list_batch_claims(self, eid):
        return self.batch

    async def set_sources_status(self, cid, status, error=None):
        self.status[cid] = (status, error)

    async def get_creator(self, creator_id):
        return getattr(self, "creator", None)

    async def get_episode_speakers(self, eid):
        return getattr(self, "speakers", [])

    async def save_sources_route(self, cid, route, triage=None):
        self.routes = getattr(self, "routes", {})
        self.routes[cid] = route
        self.status[cid] = ("not_requested", None)

    async def save_claim_sources(self, cid, found, summary="", match="", *, counter=None, counter_summary="", route=None, triage=None):
        self.routes = getattr(self, "routes", {})
        self.routes[cid] = route
        self.counter = getattr(self, "counter", {})
        self.counter[cid] = ([s.url for s in counter or []], counter_summary)
        self.match = getattr(self, "match", {})
        self.match[cid] = match
        self.saved[cid] = [s.url for s in found]
        self.summary = getattr(self, "summary", {})
        self.summary[cid] = summary
        self.full = getattr(self, "full", {})
        self.full[cid] = found
        self.status[cid] = ("done", None)

    async def add_episode_cost(self, eid, usd, tin, tout):
        self.cost.append(usd)

    async def update_episode(self, eid, fields):
        self.updates.append(fields)

    async def save_guardrail_events(self, eid, events):
        self.events = events


def test_precheck():
    assert precheck(row(), SETTINGS) == (True, "", 200)
    assert precheck(row(sources_status="failed"), SETTINGS)[0]
    for kw, words in [({"policy_tier": "never"}, "content policy"),
                      ({"sources_status": "done"}, "already"), ({"sources_status": "searching"}, "Already searching"),
                      ({"episodes": {"cost_usd": 3.0}}, "budget"), ({"episodes": {"status": "processing"}}, "finished")]:
        ok, msg, code = precheck(row(**kw), SETTINGS)
        assert not ok and code == 409 and words in msg, kw
    assert precheck(None, SETTINGS)[2] == 404


def test_one_claim_saves_whatever_the_search_returns_and_charges_one_search(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([hit("https://someblog.in/a"), hit("https://www.livemint.com/b")]))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "done" and res["sources"] == 2
    assert store.saved["c1"] == ["https://someblog.in/a", "https://www.livemint.com/b"] and store.cost == [0.005]


def test_one_claim_with_no_results_is_done_and_empty(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([]))
    store = FakeStore(row())
    assert asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))["sources"] == 0 and store.saved["c1"] == []


def test_a_failed_search_can_be_retried(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel(fail=True))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and store.status["c1"][0] == "failed" and "Try again" in store.status["c1"][1]
    assert store.cost == [0.005]


def test_cost_cap_stops_a_lookup_before_searching(monkeypatch):
    fake = FakeParallel([hit("https://a.example/x")])
    monkeypatch.setattr(evidence, "_client", lambda s: fake)
    store = FakeStore(row(episodes={"cost_usd": 2.999}))
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and "budget" in res["reason"] and not fake.calls and not store.cost


# --- Every claim of a video --------------------------------------------------------------------------
def claims(n):
    return [{"id": f"id{i}", "idx": i, "start_s": (n - i) * 10, "claim_text": f"claim {i}"} for i in range(n)]


def test_all_claims_each_get_their_own_search_a_few_at_a_time(monkeypatch):
    fake = FakeParallel([hit("https://a.example/x")], delay=0.2)
    monkeypatch.setattr(evidence, "_client", lambda s: fake)
    store = FakeStore(batch=claims(6))
    t0 = time.time()
    out = asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    took = time.time() - t0
    assert out == {"status": "done", "searched": 6, "skipped": 0, "claims": 6, "remaining": 0, "cost_usd": 0.03}
    assert sorted(q["search_queries"][0] for q in fake.calls) == [f"claim {i}" for i in range(6)]  # one search per claim, no grouping
    assert 0.35 < took < 1.0  # 6 searches of 0.2 s, 3 at a time: about 0.4 s, not 1.2 s
    assert set(store.saved) == {f"id{i}" for i in range(6)} and store.cost == [pytest.approx(0.03)]
    assert store.updates[0] == {"sources_batch_status": "running"} or store.updates[0].get("sources_batch_status") == "running"
    assert store.updates[-1] == {"sources_batch_status": None, "progress": {}}


def test_all_claims_stop_at_the_budget_and_return_the_rest(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([hit("https://a.example/x")]))
    store = FakeStore(batch=claims(10))
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_cost_usd_per_episode=0.02, search_cost_usd=0.005,
                                                                 sources_concurrency=3, summarize_sources=False,
                                                                 triage_sources=False), store=store))
    assert out["searched"] == 4 and len(store.saved) == 4  # $0.02 pays for 4 searches; earliest claims first
    assert set(store.saved) == {"id9", "id8", "id7", "id6"}


def test_one_failed_search_does_not_stop_the_others(monkeypatch):
    class Flaky(FakeParallel):
        def search(self, **kw):
            if kw["search_queries"][0] == "claim 2":
                raise RuntimeError("timeout")
            return super().search(**kw)
    monkeypatch.setattr(evidence, "_client", lambda s: Flaky([hit("https://a.example/x")]))
    store = FakeStore(batch=claims(4))
    asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    assert set(store.saved) == {"id0", "id1", "id3"} and store.status["id2"][0] == "failed"


def test_nothing_to_do():
    store = FakeStore(batch=[])
    assert asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))["status"] == "skipped"
    assert store.updates == [{"sources_batch_status": None}]


def test_lookups_for_one_video_are_serialised(monkeypatch):
    active = {"n": 0, "max": 0}

    async def slow(claim_text, settings, policy, **kw):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.01)
        active["n"] -= 1
        return []
    monkeypatch.setattr(sources, "search_sources", slow)
    sources._episode_locks.clear()

    async def both():
        store = FakeStore(row())
        await asyncio.gather(run_claim_sources("c1", settings=SETTINGS, store=store), run_claim_sources("c2", settings=SETTINGS, store=store))
    asyncio.run(both())
    assert active["max"] == 1


def test_each_press_is_capped_and_the_rest_wait_for_the_next_press(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([hit("https://a.example/x")]))
    store = FakeStore(batch=claims(10))
    out = asyncio.run(run_video_sources("e1", settings=Settings(sources_all_max_searches=3, search_cost_usd=0.005, summarize_sources=False,
                                                                triage_sources=False), store=store))
    assert out["searched"] == 3 and out["remaining"] == 7 and set(store.saved) == {"id9", "id8", "id7"}
    assert not any(f"id{i}" in store.status for i in range(7))  # never touched: they keep "Check sources"


def test_claims_with_the_same_wording_share_one_search(monkeypatch):
    fake = FakeParallel([hit("https://a.example/x")])
    monkeypatch.setattr(evidence, "_client", lambda s: fake)
    batch = [{"id": "a", "start_s": 1, "claim_text": "GDP grew 7.4%."}, {"id": "b", "start_s": 2, "claim_text": "gdp grew 7.4 %"},
             {"id": "c", "start_s": 3, "claim_text": "Inflation was 5%."}]
    store = FakeStore(batch=batch)
    out = asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    assert out["searched"] == 2 and len(fake.calls) == 2 and store.saved["a"] == store.saved["b"] == ["https://a.example/x"]


# --- One neutral line per source (ADK step) ------------------------------------------------------------
import json  # noqa: E402
from typing import AsyncGenerator  # noqa: E402

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from claimcheck.agents import llm_agents  # noqa: E402
from claimcheck.agents.sources import acceptable_summary, summarize_missing  # noqa: E402

SUMMARY_SETTINGS = Settings(max_cost_usd_per_episode=3.0, sources_per_claim=5, search_cost_usd=0.005, summarize_sources=True,
                            triage_sources=False)


class SummaryLlm(BaseLlm):
    model: str = "fake"
    text: str = ""
    match: str = "high"
    fail: bool = False

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        if self.fail:
            raise RuntimeError("model down")
        assert "never judge the statement" in str(llm_request.config.system_instruction)
        sent = str(llm_request.contents[-1])
        assert "UNTRUSTED RELATED PAGE 3" in sent  # every source with an excerpt is given to the model
        assert "Excerpt: India's share stood at 2.98 percent" in sent  # the excerpt the reader sees, nothing more
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps({"summary": self.text, "match": self.match}))]))


def _with_summary(monkeypatch, text, fail=False, match="high"):
    monkeypatch.setattr(llm_agents, "_model", lambda name, settings: SummaryLlm(text=text, fail=fail, match=match))
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([
        hit("https://www.livemint.com/a", "Mint", ["India's share stood at 2.98 percent as of March 30, 2026."]),
        hit("https://someblog.in/b", "Blog", ["Markets are interesting."]),
        hit("https://en.wikipedia.org/wiki/X", "Wikipedia", ["List of countries by market cap."])]))


def test_one_plain_summary_of_the_excerpts(monkeypatch):
    _with_summary(monkeypatch, "Reports put India's share of global market cap at 2.98% in March 2026 [1].")
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SUMMARY_SETTINGS, store=store))
    assert (res["status"], res["sources"], res["summary"], res["match"]) == ("done", 3, True, "high")
    assert store.match["c1"] == "high"
    # plain text: any reference numbers the model adds are removed
    assert store.summary["c1"] == "Reports put India's share of global market cap at 2.98% in March 2026."
    assert store.saved["c1"] == ["https://www.livemint.com/a", "https://someblog.in/b", "https://en.wikipedia.org/wiki/X"]


def test_a_summary_that_grades_the_claim_is_dropped_but_the_sources_are_kept(monkeypatch):
    _with_summary(monkeypatch, "The sources confirm the statement [1].")
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SUMMARY_SETTINGS, store=store))
    assert res["sources"] == 3 and store.summary["c1"] == ""
    assert any(e.rule == "summary_judging_words" for e in store.events)


def test_a_failed_summary_step_still_saves_every_source(monkeypatch):
    _with_summary(monkeypatch, "", fail=True)
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SUMMARY_SETTINGS, store=store))
    assert res["status"] == "done" and res["sources"] == 3 and res["summary"] is False
    assert any(e.rule == "summary_failed" for e in store.events)


def test_judging_words_are_caught_but_plain_descriptions_pass():
    for bad in ["Confirms the GDP figure [1].", "The claim is false according to RBI [2].", "Data contradicts this.",
                "Figures are consistent with the statement.", "This is misleading."]:
        assert acceptable_summary(bad) == "", bad
    for ok in ["Reports give GDP growth of 7.4% in 2025-26.", "One gives India's share as 2.98% in March 2026.",
               "They describe passive fund allocation to India."]:
        assert acceptable_summary(ok) == ok
    assert len(acceptable_summary("word " * 100)) <= 361


def test_old_lookups_get_a_summary_from_their_stored_excerpts_without_a_new_search(monkeypatch):
    _with_summary(monkeypatch, "Reports give 2.98% in March 2026.")
    monkeypatch.setattr(evidence, "_client", lambda s: (_ for _ in ()).throw(AssertionError("no search")))

    class OldStore(FakeStore):
        saved_summary: dict = {}

        async def list_claims_missing_summary(self, limit):
            stored = [{"url": u, "title": t, "tier": 3, "excerpt": e, "publish_date": None, "rank": i}
                      for i, (u, t, e) in enumerate([("https://www.livemint.com/a", "Mint", "India's share stood at 2.98 percent as of March 30, 2026."),
                                                     ("https://someblog.in/b", "Blog", "Markets are interesting."),
                                                     ("https://en.wikipedia.org/wiki/X", "Wikipedia", "List of countries by market cap.")])]
            return [{"id": "c1", "episode_id": "e1", "claim_text": "India is 3% of world market cap",
                     "episodes": {"cost_usd": 0.1}, "claim_sources": stored}]

        async def save_sources_summary(self, cid, summary, match=""):
            self.saved_summary[cid] = (summary, match)

    store = OldStore(row())
    out = asyncio.run(summarize_missing(settings=SUMMARY_SETTINGS, store=store))
    assert out["summarised"] == 1 and store.saved_summary["c1"] == ("Reports give 2.98% in March 2026.", "high")


def test_source_match_is_saved_even_when_the_summary_is_dropped(monkeypatch):
    # match rates relevance only; a summary with judging words is dropped but the match is kept
    _with_summary(monkeypatch, "The sources confirm the statement.", match="medium")
    store = FakeStore(row())
    asyncio.run(run_claim_sources("c1", settings=SUMMARY_SETTINGS, store=store))
    assert store.summary["c1"] == "" and store.match["c1"] == "medium"


def test_a_failed_summary_step_saves_no_match(monkeypatch):
    _with_summary(monkeypatch, "", fail=True)
    store = FakeStore(row())
    asyncio.run(run_claim_sources("c1", settings=SUMMARY_SETTINGS, store=store))
    assert store.match["c1"] == ""


def test_opinions_forecasts_and_other_statements_can_have_sources_too():
    for kind in ("opinion", "forecast", "advice", "other"):
        assert precheck(row(statement_type=kind), SETTINGS)[0], kind


def test_questions_and_stories_have_no_sources_to_look_up():
    for kind in ("question", "story"):
        ok, msg, code = precheck(row(statement_type=kind), SETTINGS)
        assert not ok and code == 409 and "Questions and personal stories" in msg


# --- Triage (ClassifierNode) and the second search -------------------------------------------------------
from google.adk.labs.classifiers import BaseClassifier, ChoiceAnswer, ClassifierResponse  # noqa: E402

from claimcheck.agents import llm_agents as _llm_agents  # noqa: E402

TRIAGE_SETTINGS = Settings(max_cost_usd_per_episode=3.0, sources_per_claim=5, sources_concurrency=3, search_cost_usd=0.005,
                           summarize_sources=False, triage_sources=True, counter_search=True)


class FakeClassifier(BaseClassifier):
    model: str = "fake"
    labels: dict = {}
    fail: bool = False
    seen: list = []

    async def classify(self, *, input, questions):
        self.seen.append(input)
        if self.fail:
            raise ValueError("model returned junk")
        label = self.labels.get(input["statement"], "related")
        return ClassifierResponse(answers={n: ChoiceAnswer(choice=label, probabilities={k: float(k == label) for k in q.criteria})
                                           for n, q in questions.items()})


def _triage(monkeypatch, labels=None, fail=False, results=None):
    clf = FakeClassifier(labels=labels or {}, fail=fail, seen=[])
    monkeypatch.setattr(_llm_agents, "triage_classifier", lambda s: clf)
    fake = FakeParallel(results or [hit("https://a.example/x"), hit("https://b.example/y")])
    monkeypatch.setattr(evidence, "_client", lambda s: fake)
    return clf, fake


def test_data_and_contested_statements_get_a_second_search_with_new_links_only(monkeypatch):
    clf, fake = _triage(monkeypatch, {"GDP grew 7.4%": "data"})
    store = FakeStore(row(speaker="Raj Shamani", episodes={"creator_id": "cr1"}))
    store.creator = {"id": "cr1", "podcast": "Figuring Out", "country": "India", "profile": {"biases": "Hustle optimism.", "criticism": "Softballs."}}
    store.speakers = [{"label": "Raj Shamani", "speakers": {"status": "ready", "name": "Raj Shamani", "summary": "Host.",
                                                             "profile": {"known_positions": "Bullish on India."}}}]
    res = asyncio.run(run_claim_sources("c1", settings=TRIAGE_SETTINGS, store=store))
    assert res["status"] == "done" and res["route"] == "data" and store.routes["c1"] == "data"
    assert len(fake.calls) == 2 and store.cost == [pytest.approx(0.01)]  # both searches charged
    related, counter = sorted(fake.calls, key=lambda c: len(c["search_queries"]))
    assert "Said by Raj Shamani on Figuring Out" in related["objective"] and related["advanced_settings"]["location"] == "in"
    assert counter["search_queries"] == ["GDP grew 7.4%", "GDP grew 7.4% official statistics data"]
    assert "primary sources" in counter["objective"] and "Bullish on India" in counter["objective"] and "Softballs" in counter["objective"]
    assert store.counter["c1"] == ([], "")  # the second search found only links the first already had
    # The classifier saw the statement with its speaker and show profiles.
    assert clf.seen[0]["speaker"]["known_positions"] == "Bullish on India." and clf.seen[0]["creator"]["podcast"] == "Figuring Out"


def test_a_statement_triage_skips_gets_no_search_in_a_batch_but_one_when_pressed(monkeypatch):
    _, fake = _triage(monkeypatch, {"claim 0": "skip", "claim 1": "related"})
    store = FakeStore(batch=claims(2))
    out = asyncio.run(run_video_sources("e1", settings=TRIAGE_SETTINGS, store=store))
    assert out["searched"] == 1 and out["skipped"] == 1 and len(fake.calls) == 1
    assert store.routes == {"id0": "skip", "id1": "related"} and store.status["id0"] == ("not_requested", None)
    _, fake = _triage(monkeypatch, {"GDP grew 7.4%": "skip"})
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=TRIAGE_SETTINGS, store=store))
    assert res["route"] == "related" and len(fake.calls) == 1 and store.saved["c1"]  # a viewer asked: one search


def test_if_the_classifier_fails_the_second_search_still_runs(monkeypatch):
    _, fake = _triage(monkeypatch, fail=True)
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=TRIAGE_SETTINGS, store=store))
    assert res["route"] == "data" and len(fake.calls) == 2  # "GDP grew 7.4%" has a figure
    assert sources.fallback_route("Modi is the best PM") == "contested"


def test_a_failed_second_search_keeps_the_first(monkeypatch):
    class HalfDown(FakeParallel):
        def search(self, **kw):
            if len(kw["search_queries"]) > 1:
                raise RuntimeError("timeout")
            return super().search(**kw)
    _triage(monkeypatch, {"GDP grew 7.4%": "contested"})
    monkeypatch.setattr(evidence, "_client", lambda s: HalfDown([hit("https://a.example/x")]))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=TRIAGE_SETTINGS, store=store))
    assert res["status"] == "done" and store.saved["c1"] == ["https://a.example/x"] and store.counter["c1"] == ([], "")
