"""Sources: one search keeps every result as returned; one lookup per answer, shared by the button and "Check all". No keys or network."""

import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from claimcheck.agents import sources
from claimcheck.agents.research import Research
from claimcheck.agents.sources import Lookup, precheck, run_claim_sources, run_video_sources
from claimcheck.context import get_context
from claimcheck.schemas import Source
from claimcheck.config import Settings
from claimcheck.policy import load_policy
from claimcheck.tools import evidence
from claimcheck.tools.evidence import best_excerpt, clean_excerpt, search_sources, to_sources

POLICY = load_policy()
SETTINGS = Settings(max_cost_usd_per_episode=3.0, sources_per_claim=5, sources_concurrency=3, search_cost_usd=0.005)


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


def test_a_long_excerpt_limit_keeps_all_the_text_the_search_returned_and_a_short_one_picks_a_passage():
    from claimcheck.tools.evidence import to_sources

    r = NS(url="https://a.example/x", title="T", publish_date=None,
           excerpts=["First passage about something else entirely, long enough to matter here.", "India accounts for roughly 3% of global market cap, says the report."])
    whole = to_sources([r], POLICY, 5, 1200, "global market cap 3%")[0].excerpt
    assert "First passage" in whole and "roughly 3%" in whole
    picked = to_sources([r], POLICY, 5, 80, "global market cap 3%")[0].excerpt
    assert "roughly 3%" in picked and "First passage" not in picked


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
    assert [s.rank for s in got] == [0, 1, 2, 3, 4]  # every source alike: no tier
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


# --- One answer ---------------------------------------------------------------------------------------
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
        self.saved, self.status, self.cost, self.updates, self.analysis = {}, {}, [], [], {}

    async def get_claim_for_sources(self, claim_id):
        return self.row

    async def get_episode(self, eid):
        return {"id": eid, "status": "done", "cost_usd": 0}

    async def count_looked_up(self, eid):
        return getattr(self, "looked", 0)

    async def list_batch_claims(self, eid, recheck=False):
        self.recheck = recheck
        return self.batch

    async def set_sources_status(self, cid, status, error=None):
        self.status[cid] = (status, error)

    async def get_creator(self, creator_id):
        return getattr(self, "creator", None)

    async def get_episode_speakers(self, eid):
        return getattr(self, "speakers", [])

    async def save_sources_route(self, cid, route, triage=None, qa_tags=None):
        self.tags = getattr(self, "tags", {})
        self.tags[cid] = qa_tags
        self.routes = getattr(self, "routes", {})
        self.routes[cid] = route
        self.status[cid] = ("not_requested", None)

    async def save_claim_sources(self, cid, found, summary="", match="", *, counter=None, counter_summary="", route=None, triage=None, research=None,
                                 qa_tags=None):
        self.tags = getattr(self, "tags", {})
        self.tags[cid] = qa_tags
        self.routes = getattr(self, "routes", {})
        self.routes[cid] = route
        self.match = getattr(self, "match", {})
        self.match[cid] = match
        self.saved[cid] = [s.url for s in found]
        self.research = getattr(self, "research", {})
        self.research[cid] = research
        self.status[cid] = ("done", None)

    async def save_question_analysis(self, claim_ids, analysis):
        for i in claim_ids:
            self.analysis[i] = analysis

    async def add_episode_cost(self, eid, usd, tin, tout):
        self.cost.append(usd)

    async def update_episode(self, eid, fields):
        self.updates.append(fields)

    async def save_guardrail_events(self, eid, events):
        self.events = events


def fake_lookup(monkeypatch, urls=("https://a.example/x",), skip=(), fail=(), delay=0.0, active=None):
    """Replaces the lookup (planner, searches, tags) with one that charges a search and returns the given pages."""
    calls = []

    async def lookup(claim, vctx, *, force):
        calls.append((claim["claim_text"], force))
        if active is not None:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        get_context().budget.add(get_context().settings.search_cost_usd)
        if delay or active is not None:
            await asyncio.sleep(delay or 0.01)
        if active is not None:
            active["n"] -= 1
        if claim["claim_text"] in fail:
            raise RuntimeError("search timeout")
        if claim["claim_text"] in skip:
            return Lookup("skip", [], None, {"claim": {"type": "pure_opinion", "p": 0.9}, "grounding": {"label": "exempt"}})
        srcs = [Source(url=u, title="t", excerpt="e", rank=i) for i, u in enumerate(urls)]
        r = Research(points=[], positions=[], queries=["q"], related=srcs, counter=[], summary="", counter_summary="", match="medium")
        return Lookup("related", srcs, r, {"grounding": {"label": "plausible", "p": 0.7}, "chain": "Direct A → Objective fact → Plausible"})

    monkeypatch.setattr(sources, "lookup_answer", lookup)
    return calls


def test_precheck():
    assert precheck(row(), SETTINGS) == (True, "", 200)
    assert precheck(row(sources_status="failed"), SETTINGS)[0]
    for kw, words in [({"policy_tier": "never"}, "content policy"),
                      ({"sources_status": "done"}, "already"), ({"sources_status": "searching"}, "Already searching"),
                      ({"episodes": {"cost_usd": 3.0}}, "budget"), ({"episodes": {"status": "processing"}}, "finished")]:
        ok, msg, code = precheck(row(**kw), SETTINGS)
        assert not ok and code == 409 and words in msg, kw
    assert precheck(None, SETTINGS)[2] == 404


def test_opinions_forecasts_and_other_statements_can_have_sources_too():
    for kind in ("opinion", "forecast", "advice", "other"):
        assert precheck(row(statement_type=kind), SETTINGS)[0], kind


def test_questions_have_no_sources_to_look_up_but_stories_do():
    ok, msg, code = precheck(row(statement_type="question"), SETTINGS)
    assert not ok and code == 409 and "Questions" in msg
    assert precheck(row(statement_type="story"), SETTINGS)[0]  # the claim-type classifier decides what a story needs


def test_one_answer_saves_every_page_the_lookup_found_and_its_tags_and_is_never_skipped(monkeypatch):
    calls = fake_lookup(monkeypatch, urls=("https://someblog.in/a", "https://www.livemint.com/b"))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res == {"claim_id": "c1", "status": "done", "sources": 2, "match": "medium", "grounding": "plausible", "cost_usd": 0.005}
    assert store.saved["c1"] == ["https://someblog.in/a", "https://www.livemint.com/b"] and store.cost == [0.005]
    assert calls == [("GDP grew 7.4%", True)]                                           # the button forces the lookup
    assert store.tags["c1"]["grounding"]["label"] == "plausible"                    # the answer's tags are saved with its pages


def test_one_answer_with_no_pages_is_done_and_empty(monkeypatch):
    fake_lookup(monkeypatch, urls=())
    store = FakeStore(row())
    assert asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))["sources"] == 0 and store.saved["c1"] == []


def test_a_failed_lookup_can_be_retried(monkeypatch):
    fake_lookup(monkeypatch, fail=("GDP grew 7.4%",))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and store.status["c1"][0] == "failed" and "Try again" in store.status["c1"][1]
    assert store.cost == [0.005]


def test_cost_cap_stops_a_lookup_before_searching(monkeypatch):
    calls = fake_lookup(monkeypatch)
    store = FakeStore(row(episodes={"cost_usd": 2.999}))
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and "budget" in res["reason"] and not calls and not store.cost


# --- Every answer of a video -------------------------------------------------------------------------
EACH = SETTINGS.lookup_cost_estimate_usd  # what the budget plans for one lookup


def claims(n):
    return [{"id": f"id{i}", "idx": i, "start_s": (n - i) * 10, "claim_text": f"claim {i}"} for i in range(n)]


def test_all_answers_each_get_their_own_lookup_a_few_at_a_time(monkeypatch):
    calls = fake_lookup(monkeypatch, delay=0.2)
    store = FakeStore(batch=claims(6))
    t0 = time.time()
    out = asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    took = time.time() - t0
    assert out == {"status": "done", "searched": 6, "skipped": 0, "claims": 6, "remaining": 0, "cost_usd": 0.03}
    assert sorted(c for c, f in calls) == [f"claim {i}" for i in range(6)] and not any(f for _, f in calls)   # not forced: the planner may skip
    assert 0.35 < took < 1.0  # 6 lookups of 0.2 s, 3 at a time: about 0.4 s, not 1.2 s
    assert set(store.saved) == {f"id{i}" for i in range(6)} and store.cost == [pytest.approx(0.03)]
    assert store.updates[0].get("sources_batch_status") == "running"
    assert store.updates[-1] == {"sources_batch_status": None, "progress": {}}


def test_an_answer_with_nothing_checkable_is_set_aside_and_keeps_its_button(monkeypatch):
    fake_lookup(monkeypatch, skip=("claim 1",))
    store = FakeStore(batch=claims(3))
    out = asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    assert out["searched"] == 2 and out["skipped"] == 1 and store.routes["id1"] == "skip" and store.status["id1"] == ("not_requested", None)


def test_all_answers_stop_at_the_budget_and_return_the_rest(monkeypatch):
    fake_lookup(monkeypatch)
    store = FakeStore(batch=claims(10))
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_cost_usd_per_episode=EACH * 4.2, search_cost_usd=0.005, sources_concurrency=3), store=store))
    assert out["searched"] == 4 and len(store.saved) == 4  # the budget pays for 4 lookups; earliest answers first
    assert set(store.saved) == {"id9", "id8", "id7", "id6"}


def test_a_recheck_asks_for_every_answer_and_leaves_those_over_the_budget_as_they_were(monkeypatch):
    fake_lookup(monkeypatch)
    batch = [{**c, "sources_status": "done" if c["idx"] % 2 == 0 else "not_requested"} for c in claims(6)]
    store = FakeStore(batch=batch)
    cfg = Settings(max_cost_usd_per_episode=EACH * 4.2, search_cost_usd=0.005, sources_concurrency=3)
    out = asyncio.run(run_video_sources("e1", settings=cfg, store=store, recheck=True))
    assert store.recheck is True and out["searched"] == 4
    assert set(store.saved) == {"id5", "id4", "id3", "id2"}            # earliest first; the budget pays for 4
    assert "id1" not in store.status and "id0" not in store.status   # answers over the budget are left exactly as they were
    asyncio.run(run_video_sources("e1", settings=cfg, store=store))
    assert store.recheck is False


def test_one_failed_lookup_does_not_stop_the_others(monkeypatch):
    fake_lookup(monkeypatch, fail=("claim 2",))
    store = FakeStore(batch=claims(4))
    asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    assert set(store.saved) == {"id0", "id1", "id3"} and store.status["id2"][0] == "failed"


def test_nothing_to_do():
    store = FakeStore(batch=[])
    assert asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))["status"] == "skipped"
    assert store.updates == [{"sources_batch_status": None}]


def test_lookups_for_one_video_are_serialised(monkeypatch):
    active = {"n": 0, "max": 0}
    fake_lookup(monkeypatch, active=active)
    sources._episode_locks.clear()

    async def both():
        store = FakeStore(row())
        await asyncio.gather(run_claim_sources("c1", settings=SETTINGS, store=store), run_claim_sources("c2", settings=SETTINGS, store=store))
    asyncio.run(both())
    assert active["max"] == 1


def test_a_video_is_capped_at_its_total_lookups_and_the_rest_keep_their_button(monkeypatch):
    fake_lookup(monkeypatch)
    store = FakeStore(batch=claims(10))
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_searches_per_video=3, search_cost_usd=0.005), store=store))
    assert out["searched"] == 3 and out["remaining"] == 7 and set(store.saved) == {"id9", "id8", "id7"}
    assert not any(f"id{i}" in store.status for i in range(7))  # never touched: they keep "Check sources"


def test_lookups_already_done_count_against_the_video_total(monkeypatch):
    fake_lookup(monkeypatch)
    store = FakeStore(batch=claims(10))
    store.looked = 198  # e.g. from the button and the automatic lookups while the video was read
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_searches_per_video=200, search_cost_usd=0.005), store=store))
    assert out["searched"] == 2 and out["remaining"] == 8
    store = FakeStore(batch=claims(10))
    store.looked = 200
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_searches_per_video=200), store=store))
    assert out["status"] == "skipped" and "200 source lookups" in out["reason"]


def test_zero_means_no_count_limit_and_a_recheck_only_has_the_cap_itself(monkeypatch):
    fake_lookup(monkeypatch)
    off = dict(search_cost_usd=0.005)
    store = FakeStore(batch=claims(10))
    store.looked = 500
    assert asyncio.run(run_video_sources("e1", settings=Settings(max_searches_per_video=0, **off), store=store))["searched"] == 10
    store = FakeStore(batch=claims(10))
    store.looked = 200
    assert asyncio.run(run_video_sources("e1", settings=Settings(max_searches_per_video=200, **off), store=store, recheck=True))["searched"] == 10


def test_the_button_is_refused_once_the_video_has_used_its_lookups(monkeypatch):
    store = FakeStore(row())
    store.looked = 200
    out = asyncio.run(run_claim_sources("c1", settings=Settings(max_searches_per_video=200), store=store))
    assert out["status"] == "failed" and "200 source lookups" in out["reason"] and store.status["c1"][0] == "failed"


def test_answers_with_the_same_wording_share_one_lookup(monkeypatch):
    calls = fake_lookup(monkeypatch)
    batch = [{"id": "a", "start_s": 1, "claim_text": "GDP grew 7.4%."}, {"id": "b", "start_s": 2, "claim_text": "gdp grew 7.4 %"},
             {"id": "c", "start_s": 3, "claim_text": "Inflation was 5%."}]
    store = FakeStore(batch=batch)
    out = asyncio.run(run_video_sources("e1", settings=SETTINGS, store=store))
    assert out["searched"] == 2 and len(calls) == 2 and store.saved["a"] == store.saved["b"] == ["https://a.example/x"]
