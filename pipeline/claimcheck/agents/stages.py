"""Custom (code-only) agents: gates, filters and publishing.

These run inside the ADK pipeline like any agent, but contain no LLM calls, so
the rules they enforce cannot be talked around.
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
from ..policy import normalize_topics, strictest_tier
from ..schemas import ClaimRecord, ExtractedClaim
from ..store import ts_to_seconds
from ..tools.youtube import fetch_metadata


def _event(agent: BaseAgent, ctx: InvocationContext, delta: dict[str, Any], text: str = "", escalate: bool = False) -> Event:
    return Event(author=agent.name, invocation_id=ctx.invocation_id,
                 actions=EventActions(state_delta=delta, escalate=escalate or None),
                 content=types.Content(role="model", parts=[types.Part(text=text or agent.name)]))


def classify_statement(claim: ExtractedClaim, policy: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Content policy in code: (effective tier, not_checked_reason). A None reason means verifiable.

    Never-check topics are redacted whatever the statement type; other non-factual statements are
    tagged with their type and never verified.
    """
    tier = strictest_tier(claim.policy_tier, claim.topics, claim.claim_type, policy)
    if claim.policy_tier == "never" or any(t in policy["never_topics"] for t in claim.topics):
        return tier, "outside_policy"
    if not claim.verifiable:
        return tier, claim.statement_type  # opinion / forecast / analogy / loaded_language / hearsay / other
    return tier, None


def build_record(i: int, raw: dict[str, Any], ec: Any, log: bool = True) -> Optional[ClaimRecord]:
    """One extracted statement -> ClaimRecord, with the content policy applied in code. None if it is malformed.

    Shared by the ClaimFilter stage and the streaming saver, so a statement is treated the same either way.
    The streamer passes log=False: ClaimFilter logs the guardrail events when it runs over the final list.
    """
    try:
        topics = normalize_topics(raw.get("topics") or raw.get("topic"), ec.policy)
        claim = ExtractedClaim.model_validate({**raw, "topics": topics, "topic": topics[0]})
    except Exception as e:  # schema guardrail: malformed claims are dropped, not guessed at
        if log:
            ec.log("extract", "claim_schema_invalid", "skipped", str(e)[:200], i)
        return None
    tier, reason = classify_statement(claim, ec.policy)
    rec = ClaimRecord(index=i, start_s=ts_to_seconds(claim.start_ts), claim=claim, effective_tier=tier, not_checked_reason=reason)
    if not log:
        return rec
    if reason == "outside_policy":
        ec.log("policy", "never_check_tier", "skipped", claim.topic, i)
    if tier != claim.policy_tier and tier != "never":
        ec.log("policy", "tier_raised_in_code", "flagged", f"{claim.policy_tier} -> {tier} ({claim.topic})", i)
    return rec


class IngestGate(BaseAgent):
    """Stage 1: fetch metadata and reject invalid input before any model call."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        meta = await fetch_metadata(ec.video_id, ec.settings)
        ok, reason = validate_metadata(meta, ec.policy)
        delta: dict[str, Any] = {"metadata": meta}
        if not ok:
            ec.log("ingest", "invalid_input", "skipped", reason)
            delta["gate"] = {"skip": True, "stage": "ingest", "reason": reason}
        else:
            # Title/description are untrusted: flag instruction-like text, then pass them delimited.
            hits = find_injections(meta.get("title", "") + "\n" + meta.get("description", ""))
            if hits:
                ec.log("ingest", "prompt_injection_in_metadata", "flagged", hits[0])
            shown = {k: meta.get(k) for k in ("title", "channel_title", "description", "duration_s", "published_at", "default_audio_language")}
            delta["video_metadata"] = wrap_untrusted("VIDEO METADATA", json.dumps(shown, ensure_ascii=False))
            delta["video_title"] = meta.get("title", "")
            delta["channel_title"] = meta.get("channel_title", "")
        yield _event(self, ctx, delta, reason or "metadata ok")


class TriageGate(BaseAgent):
    """Stage 2 guardrail: skip low-value or mostly off-policy videos."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        if st.get("gate", {}).get("skip"):
            yield _event(self, ctx, {}, "already gated")
            return
        t = st.get("triage") or {}
        rules = ec.policy["triage"]
        reason = ""
        low = float(t.get("worthiness", 0)) < rules["min_worthiness"]
        if low and ec.settings.skip_worthiness:
            ec.log("triage", "worthiness_gate_bypassed", "flagged", f"score {float(t.get('worthiness', 0)):.2f} below {rules['min_worthiness']}")
            low = False
        if low:
            reason = f"Not enough checkable factual claims (score {float(t.get('worthiness', 0)):.2f}). {t.get('reason', '')}".strip()
        elif float(t.get("never_share", 0)) > rules["max_never_share"]:
            reason = "Most of this video covers topics ClaimCheck doesn't check (beliefs, communities, satire or live cases)."
        if reason:
            ec.log("triage", "triage_gate", "skipped", reason)
            yield _event(self, ctx, {"gate": {"skip": True, "stage": "triage", "reason": reason}}, reason)
        else:
            yield _event(self, ctx, {"gate": {"skip": False}}, "passed triage")


class ClaimFilter(BaseAgent):
    """Stage 3 guardrail: cap statements, re-apply the content policy in code, mark which can be verified."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        if st.get("gate", {}).get("skip"):
            yield _event(self, ctx, {"claim_records": []}, "gated")
            return
        raw = (st.get("extraction") or {}).get("claims", [])
        cap = ec.policy["claims"]["max_extracted"]
        if len(raw) > cap:
            ec.log("extract", "max_extracted", "skipped", f"{len(raw) - cap} claims over cap dropped")
        records: list[dict[str, Any]] = []
        for i, c in enumerate(raw[:cap]):
            rec = build_record(i, c, ec)
            if rec is not None:
                records.append(rec.model_dump())
        verifiable = sum(1 for r in records if r["not_checked_reason"] is None)
        yield _event(self, ctx, {"claim_records": records}, f"{verifiable} of {len(records)} statements are verifiable factual claims")


class Publisher(BaseAgent):
    """Stage 11: the only writer. Saves claims, verdicts, citations and guardrail events."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        gate = st.get("gate", {})
        meta = st.get("metadata", {})
        base = {"title": meta.get("title"), "duration_s": meta.get("duration_s"), "published_at": meta.get("published_at"),
                "worthiness_score": (st.get("triage") or {}).get("worthiness")}
        if gate.get("skip"):
            await ec.store.update_episode(ec.episode_id, {**base, "status": "skipped", "skip_reason": gate.get("reason")})
            await ec.store.save_guardrail_events(ec.episode_id, ec.events)
            yield _event(self, ctx, {"published": False}, "skipped")
            return
        records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
        await ec.store.save_results(ec.episode_id, records, ec.embeddings, ec.cached_ids,
                                    ec.settings.fast_model, ec.settings.judge_model)
        await ec.store.save_guardrail_events(ec.episode_id, ec.events)
        pending = sum(1 for r in records if r.verdict and r.verdict.review_status == "pending")
        tally: dict[str, int] = {}  # published verdicts only: pending ones stay hidden until reviewed
        for r in records:
            if r.verdict and r.verdict.review_status != "pending":
                tally[r.verdict.verdict] = tally.get(r.verdict.verdict, 0) + 1
        not_checked: dict[str, int] = {}
        statement_counts: dict[str, int] = {}
        for r in records:
            if r.not_checked_reason:
                not_checked[r.not_checked_reason] = not_checked.get(r.not_checked_reason, 0) + 1
            t = r.claim.statement_type or "other"
            statement_counts[t] = statement_counts.get(t, 0) + 1
        await ec.store.update_episode(ec.episode_id, {
            **base, "status": "in_review" if pending else "done", "tally": tally, "not_checked": not_checked,
            "statement_counts": statement_counts,
            "summary": ((st.get("extraction") or {}).get("summary") or "").strip()[:1200] or None,
            "cost_usd": round(ec.budget.spent_usd, 4), "tokens_in": ec.budget.tokens_in, "tokens_out": ec.budget.tokens_out,
        })
        yield _event(self, ctx, {"published": True, "tally": tally, "not_checked": not_checked, "pending_review": pending,
                                 "statement_counts": statement_counts},
                     f"published: {tally}")
