"""Per-claim verification.

ClaimVerifier (SequentialAgent)
  before_agent_callback: cache check (pgvector)  -> skips the whole verifier on a hit
  NormalizerAgent  -> self-contained query
  JudgeLoop (LoopAgent, max 2 rounds)
    EvidenceAgent  -> search_and_extract tool (guarded)
    JudgeAgent     -> verdict schema, sources injected as untrusted data
    ConfidenceGate -> exits the loop when confident, otherwise feeds the judge's doubts back

Then, in code: escalation (Task API) if still unsure, a second judge run for any
False verdict, the verdict checks, and the human-review flag.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import get_context
from ..guardrails.verdict_checks import apply_verdict_checks, needs_second_opinion
from ..policy import needs_review
from ..schemas import ClaimRecord, FinalVerdict, JudgeResult
from ..store import embed_texts
from ..tools.evidence import escalate_sources
from .llm_agents import evidence_agent, judge_agent, normalizer_agent
from .stages import _event

APP = "claimcheck_verifier"


class ConfidenceGate(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        rounds = int(st.get("judge_rounds", 0)) + 1
        judge = st.get("judge") or {}
        conf = float(judge.get("confidence", 0))
        done = conf >= ec.policy["verdicts"]["escalate_below_confidence"] or rounds >= 2
        delta = {"judge_rounds": rounds}
        if not done:
            delta["judge_feedback"] = f"Round {rounds} was unsure (confidence {conf:.2f}): {judge.get('reasoning', '')}"
        yield _event(self, ctx, delta, "confident" if done else "retrying", escalate=done)


def _set_normalized_query(callback_context: CallbackContext) -> Optional[types.Content]:
    n = callback_context.state.get("normalized") or {}
    kws = "; ".join(n.get("keywords", []))
    callback_context.state["normalized_query"] = f"{n.get('query', '')}" + (f" (also try: {kws})" if kws else "")
    return None


async def _cache_check(callback_context: CallbackContext) -> Optional[types.Content]:
    ec = get_context()
    emb = (await embed_texts([callback_context.state["claim_text"]], ec.settings))[0]
    callback_context.state["embedding"] = emb
    hit = await ec.store.match_verdict(emb, ec.settings.cache_similarity, ec.settings.cache_max_age_days)
    if hit:
        verdict_id, fv = hit
        callback_context.state["cached"] = {"verdict_id": verdict_id, "verdict": fv.model_dump()}
        return types.Content(role="model", parts=[types.Part(text="cache hit")])
    return None


def build_verifier(settings) -> SequentialAgent:
    normalizer = normalizer_agent(settings)
    normalizer.after_agent_callback = _set_normalized_query
    loop = LoopAgent(name="judge_loop", max_iterations=2,
                     sub_agents=[evidence_agent(settings), judge_agent(settings), ConfidenceGate(name="confidence_gate")])
    return SequentialAgent(name="claim_verifier", sub_agents=[normalizer, loop], before_agent_callback=_cache_check)


async def _run(agent, state: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    runner = InMemoryRunner(agent=agent, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="pipeline", state=state)
    msg = types.Content(role="user", parts=[types.Part(text="Verify the claim.")])
    async for _ in runner.run_async(user_id="pipeline", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="pipeline", session_id=session.id)
    return dict(done.state)


async def verify_claim(rec: ClaimRecord, meta: dict[str, Any]) -> tuple[FinalVerdict, Optional[str], Optional[list[float]]]:
    ec = get_context()
    c = rec.claim
    claim_key = f"{ec.episode_id}:{rec.index}:{uuid.uuid4().hex[:6]}"
    state = {
        "claim_key": claim_key, "claim_index": rec.index, "claim_text": c.claim, "speaker": c.speaker,
        "start_ts": c.start_ts, "context_quote": c.context_quote, "pestle_area": c.pestle_area,
        "video_title": meta.get("video_title", ""), "judge_feedback": "", "normalized_query": c.claim,
        "searches_used": 0, "judge_rounds": 0,
    }
    st = await _run(build_verifier(ec.settings), state)
    emb = st.get("embedding")

    if st.get("cached"):
        fv = FinalVerdict.model_validate(st["cached"]["verdict"])
        fv.from_cache = True
        ec.log("cache", "verdict_reused", "flagged", st["cached"]["verdict_id"], rec.index)
        return fv, st["cached"]["verdict_id"], emb

    judge = JudgeResult.model_validate(st["judge"]) if st.get("judge") else JudgeResult(
        verdict="unverifiable", confidence=0.0, reasoning="The judge returned no verdict.", citations=[])
    escalated = False

    # Escalation: still unsure after the loop -> ask the Task API for better primary sources, judge again.
    if ec.settings.enable_escalation and judge.confidence < ec.policy["verdicts"]["escalate_below_confidence"]:
        added = await escalate_sources(claim_key, c.claim)
        ec.log("verify", "escalated_to_task_api", "flagged", f"{added} new sources", rec.index)
        if added:
            escalated = True
            st2 = await _run(judge_agent(ec.settings), {**state, "searches_used": 99})
            if st2.get("judge"):
                judge = JudgeResult.model_validate(st2["judge"])

    # False rule: a second, independent judge run with sources in reverse order.
    second = None
    if needs_second_opinion(judge, ec.policy):
        st3 = await _run(judge_agent(ec.settings, name="judge_confirm"), {**state, "reorder_sources": True})
        if st3.get("judge_confirm"):
            second = JudgeResult.model_validate(st3["judge_confirm"])

    evidence = ec.evidence.get(claim_key, {})
    final, downgrades = apply_verdict_checks(judge, c, rec.effective_tier, evidence, ec.policy, second)
    for rule, detail in downgrades:
        ec.log("verdict", rule, "downgraded" if "->" in detail else "flagged", detail, rec.index)
    final.escalated = escalated
    if needs_review(final.verdict, rec.effective_tier, ec.track, ec.policy):
        final.review_status = "pending"
        ec.log("review", "human_signoff_required", "flagged", final.verdict, rec.index)
    return final, None, emb
