"""Per-claim verification: at most three web searches, run at the same time, then one judgement.

cache check (code)       pgvector: a similar claim already judged is reused, with no searches
Workflow (ADK graph)
  plan     LlmAgent     proposes three searches: official source, independent corroboration, counter-evidence
  clamp    code         validates the plan and cuts it to max_searches_per_claim (never more than 3)
  search   parallel_worker, one Parallel search + extract per item, concurrent, no retries, one failure doesn't sink the rest
  judge    LlmAgent     TRUE / FALSE / UNVERIFIABLE with explanation, correction and cited quotes
checks (code)            quote check, number check, source-tier rules, neutral wording, score, human-review flag
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from google.adk.agents.context import Context
from google.adk.runners import InMemoryRunner
from google.adk.workflow import RetryConfig, START, Workflow, node
from google.genai import types

from ..context import get_context
from ..guardrails.verdict_checks import apply_verdict_checks, truth_score
from ..policy import needs_review
from ..schemas import ClaimRecord, FinalVerdict, JudgeOutput, JudgeResult
from ..store import embed_texts
from ..tools.evidence import run_search
from .llm_agents import judge_agent, planner_agent

APP = "claimcheck_verifier"
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
        out = [{"query": claim_text[:MAX_QUERY_CHARS], "scope": "open", "purpose": "corroborate"}]
    return out[:limit]


def build_verifier(settings) -> Workflow:
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

    return Workflow(name="claim_verifier", edges=[(START, planner_agent(settings), node(clamp, name="clamp"), search,
                                                   judge_agent(settings))])


async def _run(workflow, state: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    runner = InMemoryRunner(node=workflow, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="pipeline", state=state)
    msg = types.Content(role="user", parts=[types.Part(text="Verify the claim.")])
    async for _ in runner.run_async(user_id="pipeline", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="pipeline", session_id=session.id)
    return dict(done.state)


async def verify_claim(rec: ClaimRecord, meta: dict[str, Any]) -> tuple[FinalVerdict, Optional[str], Optional[list[float]]]:
    ec = get_context()
    c = rec.claim

    # 1. Cache: an already-judged similar claim costs no searches.
    emb = (await embed_texts([c.claim], ec.settings))[0]
    hit = await ec.store.match_verdict(emb, ec.settings.cache_similarity, ec.settings.cache_max_age_days)
    if hit:
        verdict_id, fv = hit
        fv.from_cache = True
        fv.score = truth_score(fv.verdict, fv.confidence, fv.citations)
        ec.log("cache", "verdict_reused", "flagged", verdict_id, rec.index)
        return fv, verdict_id, emb

    # 2. Plan -> clamp -> parallel search -> judge.
    claim_key = f"{ec.episode_id}:{rec.index}:{uuid.uuid4().hex[:6]}"
    state = {
        "claim_key": claim_key, "claim_index": rec.index, "claim_text": c.claim, "speaker": c.speaker,
        "start_ts": c.start_ts, "context_quote": c.context_quote, "pestle_area": c.pestle_area,
        "video_title": meta.get("video_title", ""),
    }
    st = await _run(build_verifier(ec.settings), state)
    judge = (JudgeOutput.model_validate(st["judge"]).to_result() if st.get("judge") else JudgeResult(
        verdict="unverifiable", confidence=0.0, reasoning="The judge returned no verdict.", citations=[]))

    # 3. Checks in code: quotes, numbers, source tiers, wording; then score and review flag.
    evidence = ec.evidence.get(claim_key, {})
    final, downgrades = apply_verdict_checks(judge, c, rec.effective_tier, evidence, ec.policy)
    for rule, detail in downgrades:
        ec.log("verdict", rule, "downgraded" if "->" in detail else "flagged", detail, rec.index)
    if final.verdict != "false":
        final.correction = ""
    final.score = truth_score(final.verdict, final.confidence, final.citations)
    if needs_review(final.verdict, rec.effective_tier, ec.track, ec.policy):
        final.review_status = "pending"
        ec.log("review", "human_signoff_required", "flagged", final.verdict, rec.index)
    return final, None, emb
