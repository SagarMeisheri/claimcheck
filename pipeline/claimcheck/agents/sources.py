"""Sources for one claim: at most three web searches, run at the same time, then one pass that copies sentences.

Workflow (ADK graph)
  plan     LlmAgent     proposes three searches: the original source, an independent one, other figures
  clamp    code         validates the plan and cuts it to max_searches_per_claim (never more than 3)
  search   parallel_worker, one Parallel search + extract per item, concurrent, no retries, one failure doesn't sink the rest
  pick     LlmAgent     copies one sentence per relevant source; never assesses the claim or the speaker
checks (code)            page was fetched, sentence is on it, site is official or established news (guardrails/source_checks.py)

The result is a list of sources, possibly empty. Nothing here says whether the claim is right.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from google.adk.agents.context import Context
from google.adk.runners import InMemoryRunner
from google.adk.workflow import RetryConfig, START, Workflow, node
from google.genai import types

from ..context import get_context
from ..guardrails.source_checks import check_sources
from ..schemas import CheckedSource, ClaimRecord, SourcePick
from ..tools.evidence import run_search
from .llm_agents import picker_agent, planner_agent

APP = "claimcheck_sources"
MAX_QUERY_CHARS = 300
HARD_MAX_SEARCHES = 3  # the product rule; config can only lower it


def clamp_plan(plan: Optional[dict[str, Any]], claim_text: str, limit: int) -> list[dict[str, str]]:
    """The model proposes searches; code decides what actually runs. Valid, unique, at most `limit`."""
    limit = max(1, min(limit, HARD_MAX_SEARCHES))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for s in (plan or {}).get("searches", []):
        q = str(s.get("query", "")).strip()
        scope = s.get("scope")
        if not q or len(q) > MAX_QUERY_CHARS or scope not in ("tier1", "open") or q.lower() in seen:
            continue
        seen.add(q.lower())
        out.append({"query": q, "scope": scope, "purpose": str(s.get("purpose", ""))})
    if not out:  # planner returned nothing usable: search the claim itself once
        out = [{"query": claim_text[:MAX_QUERY_CHARS], "scope": "open", "purpose": "independent"}]
    return out[:limit]


def build_workflow(settings) -> Workflow:
    async def clamp(ctx: Context) -> list[dict[str, Any]]:
        st = ctx.state
        base = {"claim_key": st["claim_key"], "claim_index": st.get("claim_index"), "claim_text": st["claim_text"],
                "pestle_area": st.get("pestle_area", "economic")}
        return [{**base, **s} for s in clamp_plan(st.get("plan"), st["claim_text"], settings.max_searches_per_claim)]

    # No retries: a retry would be a fourth search. A failed search returns an error result instead of raising.
    @node(name="search", parallel_worker=True, max_parallel_workers=HARD_MAX_SEARCHES,
          retry_config=RetryConfig(max_attempts=1), timeout=settings.tool_timeout_s + 5)
    async def search(node_input: dict[str, Any]) -> dict[str, Any]:
        return await run_search(node_input)

    return Workflow(name="claim_sources", edges=[(START, planner_agent(settings), node(clamp, name="clamp"), search,
                                                  picker_agent(settings))])


async def _run(workflow, state: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    runner = InMemoryRunner(node=workflow, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="pipeline", state=state)
    msg = types.Content(role="user", parts=[types.Part(text="Find sources.")])
    async for _ in runner.run_async(user_id="pipeline", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="pipeline", session_id=session.id)
    return dict(done.state)


async def find_sources(rec: ClaimRecord, meta: dict[str, Any]) -> list[CheckedSource]:
    """Plan -> clamp -> parallel search -> pick, then the checks in code. Returns the sources that passed (maybe none)."""
    ec = get_context()
    c = rec.claim
    claim_key = f"{ec.episode_id}:{rec.index}:{uuid.uuid4().hex[:6]}"
    state = {
        "claim_key": claim_key, "claim_index": rec.index, "claim_text": c.claim,
        "start_ts": c.start_ts, "pestle_area": c.pestle_area, "video_title": meta.get("video_title", ""),
    }
    st = await _run(build_workflow(ec.settings), state)
    picked = SourcePick.model_validate(st["picked"]).sources if st.get("picked") else []
    return check_sources(picked, ec.evidence.get(claim_key, {}), ec.policy,
                         log=lambda rule, url: ec.log("sources", rule, "skipped", url, rec.index), claim_index=rec.index)
