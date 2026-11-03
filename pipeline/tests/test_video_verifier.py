"""The automatic whole-video verifier: planning rules in code, and the whole ADK workflow with a fake model, search and store."""

import asyncio
import json
import re
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from claimcheck.agents import llm_agents, video_verifier as vv
from claimcheck.config import Settings
from claimcheck.schemas import FinalVerdict

SETTINGS = Settings(auto_verify_max_claims=12, auto_verify_max_searches=5, max_cost_usd_per_episode=3.0)


def claim(n, text, tier="normal", **kw):
    return {"n": n, "id": f"id{n}", "idx": n, "start_s": n * 10, "speaker": "Host", "claim_text": text, "context_quote": text,
            "pestle_area": "economic", "topic": "gdp", "statement_type": "factual_claim", "policy_tier": tier,
            "checkworthiness": None, **kw}


# --- Planning rules (code, not the model) ------------------------------------------------------------
def test_knowledge_route_only_for_plain_normal_tier_claims():
    assert vv.knowledge_ok("The Constitution came into force in 1950.", "normal")  # a year is fine
    assert not vv.knowledge_ok("GDP grew 7.4 per cent.", "normal")  # any figure needs a source
    assert not vv.knowledge_ok("Delhi is the capital.", "stricter")


def test_select_claims_takes_the_most_checkworthy_then_orders_by_time():
    rows = [{"id": "a", "start_s": 30, "checkworthiness": 0.9}, {"id": "b", "start_s": 10, "checkworthiness": 0.1},
            {"id": "c", "start_s": 20, "checkworthiness": 0.8}]
    assert [r["id"] for r in vv.select_claims(rows, 2)] == ["c", "a"]


def test_plan_groups_claims_that_share_a_search_and_overrides_the_model_where_unsafe():
    claims = [claim(1, "Delhi is the capital."), claim(2, "GDP grew 7.4 per cent."), claim(3, "Rate was 6.5 per cent."),
              claim(4, "Vague remark."), claim(5, "Policy claim.", tier="stricter")]
    triage = {"items": [
        {"n": 1, "route": "knowledge"}, {"n": 2, "route": "knowledge", "priority": 1},  # 2 has a figure: forced to search
        {"n": 3, "route": "search", "group": "GDP", "query": "india gdp growth", "priority": 1},
        {"n": 4, "route": "skip"}, {"n": 5, "route": "knowledge"}]}  # 5 is stricter: forced to search
    triage["items"][1].update(group="gdp", query="india gdp growth")
    p = vv.plan_items(triage, claims, SETTINGS)
    assert p["knowledge"] == [1] and p["skipped"] == [4]
    gdp = next(g for g in p["groups"] if g["label"] == "gdp")
    assert gdp["ns"] == [2, 3] and gdp["query"] == "india gdp growth"  # one search for both
    assert any(5 in g["ns"] for g in p["groups"])


def test_plan_keeps_one_search_back_for_the_follow_up_and_leaves_the_rest_unresolved():
    claims = [claim(i, f"Claim {i} has 5 numbers.") for i in range(1, 9)]
    p = vv.plan_items({"items": []}, claims, SETTINGS)  # nothing grouped: each claim is its own search
    assert len(p["groups"]) == SETTINGS.auto_verify_max_searches - vv.FOLLOW_UP_RESERVE == 4
    assert len(p["unresolved"]) == 4


def test_follow_up_respects_the_search_budget_and_publishes_the_rest_as_they_are():
    d = lambda i: {"claim": claim(i, "x"), "final": FinalVerdict(verdict="unverifiable", confidence=0.4, reasoning="r").model_dump(), "query": f"q{i}"}
    results = [{"searches": 4, "deferred": [d(1), d(2)], "escalate": [claim(3, "y")]}]
    p = vv.follow_up_items(results, SETTINGS)  # 5 allowed - 4 used = 1 left
    assert len(p["items"]) == 1 and p["items"][0]["last"] is True
    assert {x["claim"]["id"] for x in p["publish_now"]} == {"id2"}  # the one without a search left is published as it is


# --- The whole workflow ----------------------------------------------------------------------------------
URL = "https://thehindu.com/economy"
TEXT = "The Reserve Bank of India kept the repo rate unchanged at the policy meeting held in October."


class FakeLlm(BaseLlm):
    model: str = "fake"
    judge_calls: int = 0

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        instr = str(llm_request.config.system_instruction)
        nums = [int(n) for n in re.findall(r"^(\d+)\. \[", instr, re.M)]
        if "triage the checkable claims" in instr:
            out = {"items": [{"n": 1, "route": "knowledge"},
                             {"n": 2, "route": "search", "group": "rbi", "query": "rbi repo rate october", "priority": 1},
                             {"n": 3, "route": "search", "group": "rbi", "query": "rbi repo rate october", "priority": 1},
                             {"n": 4, "route": "skip"}]}
        elif "general knowledge" in instr:
            out = {"items": [{"n": n, "tag": "TRUE", "confidence": 0.97, "explanation": "Well established."} for n in nums]}
        else:  # batch judge
            FakeLlm.judge_calls += 1
            cite = [{"url": URL, "title": "The Hindu", "quote": TEXT}]
            if FakeLlm.judge_calls == 1:  # claim 2 is settled; claim 3 is not, but one better search could settle it
                out = {"verdicts": [
                    {"n": 2, "tag": "TRUE", "confidence": 0.9, "explanation": "The RBI left the rate unchanged.", "citations": cite},
                    {"n": 3, "tag": "UNVERIFIABLE", "confidence": 0.3, "explanation": "Not covered.", "follow_up_query": "rbi stance october"}]}
            else:
                out = {"verdicts": [{"n": n, "tag": "TRUE", "confidence": 0.88, "explanation": "Confirmed.", "citations": cite} for n in nums]}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(out))]))


class FakeStore:
    def __init__(self, rows):
        self.rows, self.status, self.saved, self.updates = rows, {}, [], []

    async def get_episode(self, eid):
        return {"id": eid, "youtube_video_id": "v", "title": "T", "status": "done", "cost_usd": 0, "channels": {"track": "finance_health"}}

    async def list_auto_verify_claims(self, eid):
        return self.rows

    async def set_claim_status(self, cid, status, error=None):
        self.status[cid] = status

    async def update_episode(self, eid, fields):
        self.updates.append(fields)

    async def match_verdict(self, emb, threshold, max_age):
        return None

    async def save_claim_verdict(self, cid, verdict, cached_id, emb, model):
        self.saved.append((cid, verdict))
        self.status[cid] = "verified"
        return "vid"

    async def refresh_episode_after_verify(self, eid, pending):
        pass

    async def add_episode_cost(self, *a):
        pass

    async def save_guardrail_events(self, *a):
        pass


def _rows():
    texts = ["Delhi is the capital of India.", "The RBI kept the repo rate unchanged in October.",
             "The RBI held rates steady at its October meeting.", "Some vague remark."]
    return [{k: v for k, v in claim(i + 1, t).items() if k != "n"} for i, t in enumerate(texts)]


def _patch(monkeypatch, search):
    FakeLlm.judge_calls = 0
    monkeypatch.setattr(llm_agents, "_model", lambda name, settings: FakeLlm())

    async def fake_embed(texts, settings):
        return [[0.0] * 3 for _ in texts]
    monkeypatch.setattr(vv, "embed_texts", fake_embed)
    monkeypatch.setattr(vv, "run_search", search)


def test_whole_video_loop_publishes_each_claim_as_it_finishes_with_two_searches(monkeypatch):
    queries = []

    async def search(item):
        queries.append(item["query"])
        vv.get_context().evidence.setdefault(item["claim_key"], {})[URL] = {"title": "The Hindu", "text": TEXT, "tier": 2}
        return {"sources_found": 1}
    _patch(monkeypatch, search)
    store = FakeStore(_rows())
    out = asyncio.run(vv.run_video_verification("e1", settings=SETTINGS, store=store))

    assert out["status"] == "done" and out["verified"] == 3 and out["of"] == 4
    assert queries == ["rbi repo rate october", "rbi stance october"]  # one shared search + one follow-up, not one per claim
    by_id = {cid: v for cid, v in store.saved}
    assert by_id["id1"].basis == "model_knowledge" and by_id["id1"].citations == [] and by_id["id1"].score is None
    assert by_id["id2"].verdict == "supported" and by_id["id2"].citations and by_id["id2"].basis == "sources"
    assert by_id["id3"].verdict == "supported"  # settled by the follow-up search
    assert store.status["id4"] == "not_requested"  # skipped by triage: a viewer can still press Verify
    order = [cid for cid, _ in store.saved]
    assert order.index("id1") < order.index("id3")  # the easy claim showed up before the follow-up finished
    assert store.updates[0]["auto_verify_status"] == "running" and store.updates[-1]["auto_verify_status"] == "done"


def test_a_failed_search_leaves_its_claims_for_a_viewer_and_does_not_crash(monkeypatch):
    async def search(item):
        raise RuntimeError("search down")
    _patch(monkeypatch, search)
    store = FakeStore(_rows())
    out = asyncio.run(vv.run_video_verification("e1", settings=SETTINGS, store=store))
    assert out["status"] == "done"
    assert store.status["id1"] == "verified"  # general-knowledge claim still published
    assert store.status["id2"] == "not_requested" and store.status["id3"] == "not_requested"


def test_nothing_runs_when_disabled_or_no_claims(monkeypatch):
    store = FakeStore([])
    assert asyncio.run(vv.run_video_verification("e1", settings=SETTINGS, store=store))["status"] == "skipped"


def test_manual_run_uses_the_higher_verify_all_limits(monkeypatch):
    seen = {}
    real = vv.build_video_verifier

    def spy(settings):
        seen["claims"], seen["searches"] = settings.auto_verify_max_claims, settings.auto_verify_max_searches
        return real(settings)
    monkeypatch.setattr(vv, "build_video_verifier", spy)

    async def search(item):
        return {"sources_found": 0}
    _patch(monkeypatch, search)
    asyncio.run(vv.run_video_verification("e1", settings=Settings(), store=FakeStore(_rows()), manual=True))
    assert seen == {"claims": Settings().verify_all_max_claims, "searches": Settings().verify_all_max_searches}


def test_automatic_verification_is_off_by_default():
    assert Settings().auto_verify is False
