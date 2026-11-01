"""The verification workflow: plan -> clamp -> parallel search -> judge. No keys or network: a fake model and fake search."""

import asyncio
import json
import time
from typing import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from claimcheck.agents import llm_agents, verifier
from claimcheck.agents.verifier import clamp_plan, verify_claim
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.guardrails.verdict_checks import truth_score
from claimcheck.policy import load_policy
from claimcheck.schemas import Citation, ClaimRecord, ExtractedClaim

POLICY = load_policy()
SETTINGS = Settings(max_cost_usd_per_episode=3.0, max_searches_per_claim=3)
URL = "https://mospi.gov.in/gdp"
TEXT = "Real GDP grew by 7.4 per cent in FY2025-26, compared with 6.5 per cent in FY2024-25."


def cite(tier=1, ok=True, url=URL):
    return Citation(url=url, title="t", tier=tier, quote="q", quote_check_passed=ok)


# --- clamp: the model proposes, code decides ------------------------------------------------------
def test_clamp_never_exceeds_three_even_if_settings_or_model_ask_for_more():
    plan = {"searches": [{"query": f"q{i}", "scope": "open", "purpose": "corroborate"} for i in range(6)]}
    assert len(clamp_plan(plan, "claim", 3)) == 3
    assert len(clamp_plan(plan, "claim", 10)) == 3
    assert len(clamp_plan(plan, "claim", 1)) == 1


def test_clamp_drops_invalid_and_duplicate_searches_and_falls_back_to_the_claim():
    plan = {"searches": [{"query": "", "scope": "open"}, {"query": "a", "scope": "web"},
                         {"query": "ok", "scope": "tier1", "purpose": "official"}, {"query": "OK", "scope": "open"}]}
    assert [s["query"] for s in clamp_plan(plan, "claim", 3)] == ["ok"]
    assert clamp_plan(None, "GDP grew 7.4%", 3) == [{"query": "GDP grew 7.4%", "scope": "open", "purpose": "corroborate"}]


# --- score ---------------------------------------------------------------------------------------
def test_score_direction_and_range():
    strong, weak = [cite(1), cite(2, url="https://b.com")], [cite(3)]
    assert truth_score("unverifiable", 0.9, strong) is None
    t_hi, t_lo = truth_score("supported", 0.95, strong), truth_score("supported", 0.6, weak)
    f_hi, f_lo = truth_score("false", 0.95, strong), truth_score("false", 0.6, weak)
    assert 50 < t_lo < t_hi <= 100 and 0 <= f_hi < f_lo < 50
    assert truth_score("supported", 0.9, [cite(1, ok=False)]) < truth_score("supported", 0.9, strong)  # unchecked quotes don't count


# --- the whole workflow --------------------------------------------------------------------------
class FakeLlm(BaseLlm):
    model: str = "fake"

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        instr = str(llm_request.config.system_instruction)
        if "Plan exactly three" in instr:
            out = {"searches": [{"query": f"query {i}", "scope": "tier1" if i == 0 else "open",
                                 "purpose": ["official", "corroborate", "counter"][i]} for i in range(3)]}
        else:
            out = {"tag": "TRUE", "confidence": 0.92, "explanation": "MoSPI reports 7.4 per cent.",
                   "citations": [{"url": URL, "title": "MoSPI", "quote": TEXT}]}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(out))]))


class FakeStore:
    def __init__(self, hit=None):
        self.hit = hit

    async def match_verdict(self, emb, threshold, max_age):
        return self.hit


def _setup(monkeypatch, store, search):
    monkeypatch.setattr(llm_agents, "_model", lambda name, settings: FakeLlm())

    async def fake_embed(texts, settings):
        return [[0.0] * 3 for _ in texts]
    monkeypatch.setattr(verifier, "embed_texts", fake_embed)
    monkeypatch.setattr(verifier, "run_search", search)
    ec = EpisodeContext(episode_id="e1", video_id="v", track="finance_health", settings=SETTINGS, policy=POLICY,
                        store=store, budget=Budget(cap_usd=3.0))
    set_context(ec)
    c = ExtractedClaim(start_ts="01:00", speaker="Host", claim="India's GDP grew 7.4 per cent in FY2025-26.",
                       context_quote="x", pestle_area="economic", topic="gdp", statement_type="factual_claim", policy_tier="normal")
    return ec, ClaimRecord(index=1, start_s=60, claim=c, effective_tier="normal")


def test_workflow_runs_three_searches_concurrently_and_returns_a_cited_scored_true(monkeypatch):
    calls = []

    async def search(item):
        calls.append(item["query"])
        await asyncio.sleep(0.3)
        ec = verifier.get_context()
        if item["purpose"] == "official":
            ec.evidence.setdefault(item["claim_key"], {})[URL] = {"title": "MoSPI", "text": TEXT, "tier": 1}
        if item["purpose"] == "counter":
            return {"error": "Timeout", "sources_found": 0}  # one failed search must not sink the others
        return {"sources_found": 1}

    ec, rec = _setup(monkeypatch, FakeStore(), search)
    t0 = time.time()
    fv, cached, emb = asyncio.run(verify_claim(rec, {"video_title": "T"}))
    assert sorted(calls) == ["query 0", "query 1", "query 2"] and time.time() - t0 < 0.8  # concurrent, not 0.9 s
    assert fv.verdict == "supported" and cached is None and emb == [0.0] * 3
    assert fv.citations and fv.citations[0].quote_check_passed and fv.citations[0].tier == 1
    assert fv.score is not None and fv.score > 75


def test_cache_hit_costs_no_searches(monkeypatch):
    from claimcheck.schemas import FinalVerdict
    cached = FinalVerdict(verdict="supported", confidence=0.9, reasoning="r", citations=[cite()])

    async def search(item):
        raise AssertionError("no search expected on a cache hit")

    ec, rec = _setup(monkeypatch, FakeStore(hit=("v-old", cached)), search)
    fv, vid, _ = asyncio.run(verify_claim(rec, {"video_title": "T"}))
    assert vid == "v-old" and fv.from_cache and fv.score is not None
