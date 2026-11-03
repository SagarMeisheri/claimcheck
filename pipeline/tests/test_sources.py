"""Sources for one claim: plan -> clamp -> parallel search -> pick -> checks in code. No keys or network:
a scripted model and a fake search."""

import asyncio
import json
import time
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from claimcheck.agents import llm_agents, sources
from claimcheck.agents.sources import clamp_plan, find_sources
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.policy import load_policy
from claimcheck.schemas import ClaimRecord, ExtractedClaim

POLICY = load_policy()
SETTINGS = Settings(max_cost_usd_per_episode=3.0, max_searches_per_claim=3)
OFFICIAL = "https://mospi.gov.in/gdp"
NEWS = "https://www.thehindu.com/gdp"
BLOG = "https://random-blog.example/gdp"
TEXT = "Press note.\nReal GDP grew by 7.4 per cent in FY2025-26, compared with 6.5 per cent in FY2024-25."
QUOTE = "Real GDP grew by 7.4 per cent in FY2025-26, compared with 6.5 per cent in FY2024-25."


# --- clamp: the model proposes, code decides ------------------------------------------------------
def test_clamp_never_exceeds_three_even_if_settings_or_model_ask_for_more():
    plan = {"searches": [{"query": f"q{i}", "scope": "open", "purpose": "independent"} for i in range(6)]}
    assert len(clamp_plan(plan, "claim", 3)) == 3
    assert len(clamp_plan(plan, "claim", 10)) == 3
    assert len(clamp_plan(plan, "claim", 1)) == 1


def test_clamp_drops_invalid_and_duplicate_searches_and_falls_back_to_the_claim():
    plan = {"searches": [{"query": "", "scope": "open"}, {"query": "a", "scope": "web"},
                         {"query": "ok", "scope": "tier1", "purpose": "original"}, {"query": "OK", "scope": "open"}]}
    assert [s["query"] for s in clamp_plan(plan, "claim", 3)] == ["ok"]
    assert clamp_plan(None, "GDP grew 7.4%", 3) == [{"query": "GDP grew 7.4%", "scope": "open", "purpose": "independent"}]


# --- the whole workflow --------------------------------------------------------------------------
class FakeLlm(BaseLlm):
    model: str = "fake"
    picks: list = []

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        instr = str(llm_request.config.system_instruction)
        if "Plan exactly three" in instr:
            out = {"searches": [{"query": f"query {i}", "scope": "open", "purpose": p}
                                for i, p in enumerate(["original", "independent", "other_figures"])]}
        else:
            assert "never comment on the speaker" in instr and "Sources:" in str(llm_request.contents[-1])
            out = {"sources": self.picks}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(out))]))


def _setup(monkeypatch, search, picks):
    monkeypatch.setattr(llm_agents, "_model", lambda name, settings: FakeLlm(picks=picks))
    monkeypatch.setattr(sources, "run_search", search)
    ec = EpisodeContext(episode_id="e1", video_id="v", settings=SETTINGS, policy=POLICY, store=None, budget=Budget(cap_usd=3.0))
    set_context(ec)
    c = ExtractedClaim(start_ts="01:00", speaker="Host", claim="India's GDP grew 7.4 per cent in FY2025-26.",
                       context_quote="x", pestle_area="economic", topic="gdp", statement_type="factual_claim", policy_tier="normal")
    return ec, ClaimRecord(index=1, start_s=60, claim=c, effective_tier="normal")


def _search_that_fetches(calls):
    async def search(item):
        calls.append(item["query"])
        await asyncio.sleep(0.3)
        ev = sources.get_context().evidence.setdefault(item["claim_key"], {})
        if item["purpose"] == "original":
            ev[OFFICIAL] = {"title": "MoSPI", "text": TEXT, "tier": 1, "publish_date": "2026-05-30"}
            ev[BLOG] = {"title": "Blog", "text": TEXT, "tier": 3}
        if item["purpose"] == "independent":
            ev[NEWS] = {"title": "The Hindu", "text": TEXT, "tier": 2}
        if item["purpose"] == "other_figures":
            return {"error": "Timeout", "sources_found": 0}  # one failed search must not sink the others
        return {"sources_found": 1}
    return search


def test_three_searches_run_concurrently_and_only_checked_sources_are_kept(monkeypatch):
    calls = []
    picks = [
        {"url": OFFICIAL, "title": "MoSPI", "quote": QUOTE},
        {"url": OFFICIAL, "title": "MoSPI again", "quote": QUOTE},                     # duplicate URL
        {"url": NEWS, "title": "The Hindu", "quote": "GDP rose sharply to a record 7.4 per cent this year."},  # not on the page
        {"url": BLOG, "title": "Blog", "quote": QUOTE},                                # tier 3: not shown
        {"url": "https://x.com/a/status/1", "title": "post", "quote": QUOTE},          # blocklisted
        {"url": "https://rbi.org.in/never-fetched", "title": "RBI", "quote": QUOTE},   # page was never fetched
    ]
    ec, rec = _setup(monkeypatch, _search_that_fetches(calls), picks)
    t0 = time.time()
    found = asyncio.run(find_sources(rec, {"video_title": "T"}))
    assert sorted(calls) == ["query 0", "query 1", "query 2"] and time.time() - t0 < 0.8  # concurrent, not 0.9 s
    assert [(s.url, s.tier, s.publish_date) for s in found] == [(OFFICIAL, 1, "2026-05-30")]
    dropped = sorted(e.rule for e in ec.events if e.stage == "sources")
    assert dropped == ["blocked_source", "quote_not_on_page", "source_not_fetched", "source_tier_not_allowed"]


def test_a_news_source_is_shown_and_at_most_three_are_kept(monkeypatch):
    calls = []
    urls = [OFFICIAL, NEWS] + [f"https://www.reuters.com/{i}" for i in range(3)]

    async def search(item):
        calls.append(item["query"])
        ev = sources.get_context().evidence.setdefault(item["claim_key"], {})
        for u in urls:
            ev[u] = {"title": u, "text": TEXT, "tier": 1}
        return {"sources_found": len(urls)}

    _, rec = _setup(monkeypatch, search, [{"url": u, "title": "t", "quote": QUOTE} for u in urls])
    found = asyncio.run(find_sources(rec, {"video_title": "T"}))
    assert [s.url for s in found] == urls[:3] and {s.tier for s in found} == {1, 2}


def test_nothing_relevant_gives_an_empty_list(monkeypatch):
    calls = []
    _, rec = _setup(monkeypatch, _search_that_fetches(calls), [])
    assert asyncio.run(find_sources(rec, {"video_title": "T"})) == []
