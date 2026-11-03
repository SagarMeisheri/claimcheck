"""Custom (code-only) agents: the ingest gate, the content-policy filter and publishing.

These run inside the ADK pipeline like any agent, but contain no LLM calls, so the rules they enforce cannot be
talked around.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..context import get_context
from ..guardrails.injection import find_injections, wrap_untrusted
from ..guardrails.input_checks import validate_metadata
from ..policy import is_never, normalize_topics
from ..schemas import ClaimRecord, ExtractedClaim
from ..store import ts_to_seconds
from ..tools.youtube import fetch_metadata


def _event(agent: BaseAgent, ctx: InvocationContext, delta: dict[str, Any], text: str = "") -> Event:
    return Event(author=agent.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta=delta),
                 content=types.Content(role="model", parts=[types.Part(text=text or agent.name)]))


def classify_statement(claim: ExtractedClaim, policy: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Content policy in code: (tier, not_checked_reason). A None reason means sources can be looked up.

    Never-show topics are redacted whatever the statement type; other non-factual statements are tagged with their
    type and have no sources button.
    """
    if is_never(claim.policy_tier, claim.topics, policy):
        return "never", "outside_policy"
    if not claim.sourceable:
        return "normal", claim.statement_type  # opinion / forecast / other
    return "normal", None


def build_record(i: int, raw: dict[str, Any], ec: Any, log: bool = True) -> Optional[ClaimRecord]:
    """One extracted statement -> ClaimRecord, with the content policy applied in code. None if it is malformed.

    Shared by the ClaimFilter stage and the streaming saver, so a statement is treated the same either way.
    The streamer passes log=False: ClaimFilter logs the guardrail events when it runs over the final list.
    """
    try:
        topics = normalize_topics(raw.get("topics") or raw.get("topic"), ec.policy)
        claim = ExtractedClaim.model_validate({**raw, "topics": topics, "topic": topics[0]})
    except Exception as e:  # schema guardrail: malformed statements are dropped, not guessed at
        if log:
            ec.log("extract", "claim_schema_invalid", "skipped", str(e)[:200], i)
        return None
    tier, reason = classify_statement(claim, ec.policy)
    rec = ClaimRecord(index=i, start_s=ts_to_seconds(claim.start_ts), claim=claim, effective_tier=tier, not_checked_reason=reason)
    if log and reason == "outside_policy":
        ec.log("policy", "never_show_topic", "skipped", claim.topic, i)
    return rec


class IngestGate(BaseAgent):
    """Stage 1: fetch metadata and reject what Gemini can't read, before any model call."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        meta = await fetch_metadata(ec.video_id, ec.settings)
        ok, reason = validate_metadata(meta, ec.policy)
        delta: dict[str, Any] = {"metadata": meta}
        if not ok:
            ec.log("ingest", "invalid_input", "skipped", reason)
            delta["gate"] = {"skip": True, "stage": "ingest", "reason": reason}
        else:
            # Title/description are untrusted: flag instruction-like text; the extractor only sees them delimited.
            hits = find_injections(meta.get("title", "") + "\n" + meta.get("description", ""))
            if hits:
                ec.log("ingest", "prompt_injection_in_metadata", "flagged", hits[0])
            delta["gate"] = {"skip": False}
            delta["video_title"] = wrap_untrusted("TITLE", meta.get("title", ""))
            delta["channel_title"] = wrap_untrusted("CHANNEL", meta.get("channel_title", ""))
        yield _event(self, ctx, delta, reason or "metadata ok")


class ClaimFilter(BaseAgent):
    """Stage 3: cap statements, re-apply the content policy in code, mark which can have sources."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        if st.get("gate", {}).get("skip"):
            yield _event(self, ctx, {"claim_records": []}, "gated")
            return
        raw = (st.get("extraction") or {}).get("claims", [])
        cap = ec.policy["claims"]["max_extracted"]
        if len(raw) > cap:
            ec.log("extract", "max_extracted", "skipped", f"{len(raw) - cap} statements over cap dropped")
        records: list[dict[str, Any]] = []
        for i, c in enumerate(raw[:cap]):
            rec = build_record(i, c, ec)
            if rec is not None:
                records.append(rec.model_dump())
        claims = sum(1 for r in records if r["not_checked_reason"] is None)
        yield _event(self, ctx, {"claim_records": records}, f"{claims} of {len(records)} statements are factual claims")


class Publisher(BaseAgent):
    """Stage 4: the only writer. Saves statements and guardrail events."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        gate = st.get("gate", {})
        meta = st.get("metadata", {})
        base = {"title": meta.get("title"), "duration_s": meta.get("duration_s"), "published_at": meta.get("published_at")}
        if gate.get("skip"):
            await ec.store.update_episode(ec.episode_id, {**base, "status": "skipped", "skip_reason": gate.get("reason")})
            await ec.store.save_guardrail_events(ec.episode_id, ec.events)
            yield _event(self, ctx, {"published": False}, "skipped")
            return
        records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
        await ec.store.save_statements(ec.episode_id, records)
        await ec.store.save_guardrail_events(ec.episode_id, ec.events)
        statement_counts: dict[str, int] = {}
        for r in records:
            t = r.claim.statement_type or "other"
            statement_counts[t] = statement_counts.get(t, 0) + 1
        auto = ec.settings.auto_sources and any(r.claim.sourceable and not r.not_checked_reason for r in records)
        await ec.store.update_episode(ec.episode_id, {
            **base, "status": "done", "statement_counts": statement_counts,
            # Set in the same write that publishes the statements, so the page never shows a gap before the batch starts.
            "sources_batch_status": "running" if auto else None,
            "summary": ((st.get("extraction") or {}).get("summary") or "").strip()[:1200] or None,
            "cost_usd": round(ec.budget.spent_usd, 4), "tokens_in": ec.budget.tokens_in, "tokens_out": ec.budget.tokens_out,
        })
        yield _event(self, ctx, {"published": True, "statement_counts": statement_counts}, f"published: {statement_counts}")
