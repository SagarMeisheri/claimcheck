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

    async def save_claim_sources(self, cid, found):
        self.saved[cid] = [s.url for s in found]
        self.status[cid] = ("done", None)

    async def add_episode_cost(self, eid, usd, tin, tout):
        self.cost.append(usd)

    async def update_episode(self, eid, fields):
        self.updates.append(fields)


def test_precheck():
    assert precheck(row(), SETTINGS) == (True, "", 200)
    assert precheck(row(sources_status="failed"), SETTINGS)[0]
    for kw, words in [({"statement_type": "opinion"}, "only be looked up for claims"), ({"policy_tier": "never"}, "content policy"),
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
    assert out == {"status": "done", "searched": 6, "claims": 6, "remaining": 0, "cost_usd": 0.03}
    assert sorted(q["search_queries"][0] for q in fake.calls) == [f"claim {i}" for i in range(6)]  # one search per claim, no grouping
    assert 0.35 < took < 1.0  # 6 searches of 0.2 s, 3 at a time: about 0.4 s, not 1.2 s
    assert set(store.saved) == {f"id{i}" for i in range(6)} and store.cost == [pytest.approx(0.03)]
    assert store.updates[0] == {"sources_batch_status": "running"} or store.updates[0].get("sources_batch_status") == "running"
    assert store.updates[-1] == {"sources_batch_status": None, "progress": {}}


def test_all_claims_stop_at_the_budget_and_return_the_rest(monkeypatch):
    monkeypatch.setattr(evidence, "_client", lambda s: FakeParallel([hit("https://a.example/x")]))
    store = FakeStore(batch=claims(10))
    out = asyncio.run(run_video_sources("e1", settings=Settings(max_cost_usd_per_episode=0.02, search_cost_usd=0.005,
                                                                 sources_concurrency=3), store=store))
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

    async def slow(claim_text, settings, policy):
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
    out = asyncio.run(run_video_sources("e1", settings=Settings(sources_all_max_searches=3, search_cost_usd=0.005), store=store))
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
