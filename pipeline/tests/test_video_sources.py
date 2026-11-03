"""Sources for a whole video: planning rules in code, and the whole ADK workflow with a scripted model, search and store."""

import asyncio
import json
import re
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from claimcheck.agents import llm_agents, video_sources as vs
from claimcheck.config import Settings
from claimcheck.schemas import BatchTriage

SETTINGS = Settings(sources_all_max_claims=12, sources_all_max_searches=5, max_cost_usd_per_episode=3.0)


def claim(n, text, **kw):
    return {"n": n, "id": f"id{n}", "idx": n, "start_s": n * 10, "claim_text": text,
            "pestle_area": "economic", "topic": "gdp", "statement_type": "factual_claim", "policy_tier": "normal", **kw}


# --- Planning rules (code, not the model) ------------------------------------------------------------
def test_select_claims_takes_the_first_ones_in_time_order():
    rows = [claim(3, "c"), claim(1, "a"), claim(2, "b")]
    assert [r["n"] for r in vs.select_claims(rows, 2)] == [1, 2]


def test_plan_groups_claims_that_share_a_search_and_skips_vague_ones():
    claims = [claim(1, "a"), claim(2, "b"), claim(3, "c"), claim(4, "d")]
    triage = {"items": [{"n": 1, "route": "search", "group": "RBI ", "query": "rbi repo rate", "priority": 2},
                        {"n": 2, "route": "search", "group": "rbi", "priority": 1},
                        {"n": 3, "route": "skip"}]}  # claim 4 has no item: searched on its own text
    p = vs.plan_items(triage, claims, SETTINGS)
    assert [(g["label"], g["ns"], g["query"]) for g in p["groups"]] == [("rbi", [1, 2], "rbi repo rate"), ("solo-4", [4], "d")]
    assert p["skipped"] == [3] and p["unresolved"] == []


def test_the_removed_knowledge_route_is_treated_as_a_search():
    t = BatchTriage.model_validate({"items": [{"n": 1, "route": "knowledge"}, {"n": 2, "route": "skip"}]})
    assert [i.route for i in t.items] == ["search", "skip"]


def test_plan_keeps_one_search_back_for_the_follow_up_and_leaves_the_rest_unresolved():
    claims = [claim(i, f"c{i}") for i in range(1, 8)]
    p = vs.plan_items({"items": []}, claims, SETTINGS)  # 7 solo groups, 5 searches: 4 now, 1 kept back
    assert len(p["groups"]) == 4 and p["unresolved"] == [5, 6, 7]


def test_follow_up_respects_the_search_budget_and_saves_the_rest_as_they_are():
    d = lambda i: {"claim": claim(i, "x"), "query": f"q{i}"}
    results = [{"searches": 4, "deferred": [d(1), d(2)]}]
    p = vs.follow_up_items(results, SETTINGS)  # 5 allowed - 4 used = 1 left
    assert len(p["items"]) == 1 and p["items"][0]["last"] is True
    assert [c["id"] for c in p["save_now"]] == ["id2"]


# --- The whole workflow ----------------------------------------------------------------------------------
URL = "https://www.thehindu.com/economy"
TEXT = "The Reserve Bank of India kept the repo rate unchanged at the policy meeting held in October."


class FakeLlm(BaseLlm):
    model: str = "fake"
    pick_calls: int = 0

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        instr = str(llm_request.config.system_instruction)
        nums = [int(n) for n in re.findall(r"^(\d+)\. ", instr, re.M)]
        if "plan cheap web searches" in instr:
            out = {"items": [{"n": 1, "route": "knowledge"},  # removed route: searched like any other
                             {"n": 2, "route": "search", "group": "rbi", "query": "rbi repo rate october", "priority": 1},
                             {"n": 3, "route": "search", "group": "rbi", "query": "rbi repo rate october", "priority": 1},
                             {"n": 4, "route": "skip"}]}
        else:  # batch picker
            assert "never comment on the speakers" in instr
            FakeLlm.pick_calls += 1
            src = [{"url": URL, "title": "The Hindu", "quote": TEXT}]
            if 2 in nums and 3 in nums:  # the shared search finds a source for claim 2; claim 3 needs another search
                out = {"items": [{"n": 2, "sources": src}, {"n": 3, "sources": [], "follow_up_query": "rbi stance october"}]}
            else:
                out = {"items": [{"n": n, "sources": src} for n in nums]}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(out))]))


class FakeStore:
    def __init__(self, rows):
        self.rows, self.status, self.saved, self.updates = rows, {}, [], []

    async def get_episode(self, eid):
        return {"id": eid, "youtube_video_id": "v", "title": "T", "status": "done", "cost_usd": 0}

    async def list_batch_claims(self, eid):
        return self.rows

    async def set_sources_status(self, cid, status, error=None):
        self.status[cid] = status

    async def update_episode(self, eid, fields):
        self.updates.append(fields)

    async def save_claim_sources(self, cid, sources):
        self.saved.append((cid, [s.url for s in sources]))
        self.status[cid] = "done"

    async def add_episode_cost(self, *a):
        pass

    async def save_guardrail_events(self, *a):
        pass


def _rows():
    texts = ["Delhi is the capital of India.", "The RBI kept the repo rate unchanged in October.",
             "The RBI held rates steady at its October meeting.", "Some vague remark."]
    return [{k: v for k, v in claim(i + 1, t).items() if k != "n"} for i, t in enumerate(texts)]


def _patch(monkeypatch, search):
    FakeLlm.pick_calls = 0
    monkeypatch.setattr(llm_agents, "_model", lambda name, settings: FakeLlm())
    monkeypatch.setattr(vs, "run_search", search)


def test_whole_video_loop_saves_each_claim_as_it_finishes(monkeypatch):
    queries = []

    async def search(item):
        queries.append(item["query"])
        vs.get_context().evidence.setdefault(item["claim_key"], {})[URL] = {"title": "The Hindu", "text": TEXT, "tier": 2}
        return {"sources_found": 1}
    _patch(monkeypatch, search)
    store = FakeStore(_rows())
    out = asyncio.run(vs.run_video_sources("e1", settings=SETTINGS, store=store))

    assert out["status"] == "done" and out["saved"] == 3 and out["of"] == 4
    # One search for claim 1 alone, one shared by claims 2 and 3, one follow-up for claim 3.
    assert sorted(queries) == sorted(["Delhi is the capital of India.", "rbi repo rate october", "rbi stance october"])
    by_id = dict(store.saved)
    assert by_id["id1"] == [URL] and by_id["id2"] == [URL] and by_id["id3"] == [URL]
    assert store.status["id4"] == "not_requested"  # skipped by triage: a viewer can still press "Check sources"
    assert store.updates[0]["sources_batch_status"] == "running" and store.updates[-1]["sources_batch_status"] is None


def test_a_failed_search_leaves_its_claims_for_a_viewer_and_does_not_crash(monkeypatch):
    async def search(item):
        raise RuntimeError("search down")
    _patch(monkeypatch, search)
    store = FakeStore(_rows())
    out = asyncio.run(vs.run_video_sources("e1", settings=SETTINGS, store=store))
    assert out["status"] == "done" and not store.saved
    assert all(store.status[f"id{i}"] == "not_requested" for i in range(1, 5))


def test_nothing_runs_with_no_claims():
    store = FakeStore([])
    assert asyncio.run(vs.run_video_sources("e1", settings=SETTINGS, store=store))["status"] == "skipped"
    assert store.updates == [{"sources_batch_status": None}]


def test_automatic_sources_are_off_by_default():
    assert Settings().auto_sources is False
