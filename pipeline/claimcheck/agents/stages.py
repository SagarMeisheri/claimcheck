"""Custom (code-only) agents: gates, filters, fan-out and publishing.

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

from ..context import get_context, is_budget_error, report_progress
from ..guardrails.injection import find_injections, wrap_untrusted
from ..guardrails.input_checks import validate_metadata
from ..policy import effective_tier
from ..schemas import ClaimRecord, ExtractedClaim
from ..store import ts_to_seconds
from ..tools.youtube import fetch_metadata
from .llm_agents import ranking_payload


def _event(agent: BaseAgent, ctx: InvocationContext, delta: dict[str, Any], text: str = "", escalate: bool = False) -> Event:
    return Event(author=agent.name, invocation_id=ctx.invocation_id,
                 actions=EventActions(state_delta=delta, escalate=escalate or None),
                 content=types.Content(role="model", parts=[types.Part(text=text or agent.name)]))


def classify_statement(claim: ExtractedClaim, policy: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Content policy in code: (effective tier, not_checked_reason). A None reason means verifiable.

    Never-check topics are redacted whatever the statement type; other non-factual statements are
    tagged with their type and never verified.
    """
    tier = effective_tier(claim.policy_tier, claim.topic, claim.claim_type, policy)
    if claim.policy_tier == "never" or (claim.topic or "").lower().strip() in policy["never_topics"]:
        return tier, "outside_policy"
    if not claim.verifiable:
        return tier, claim.statement_type  # opinion / forecast / analogy / loaded_language / hearsay / other
    return tier, None


def pick_auto_verify(records: list[ClaimRecord], priorities: list[dict[str, Any]], min_score: float, limit: int) -> list[int]:
    """Top `limit` check-worthy factual claims. Sets checkworthiness and auto_verified on the records."""
    pri = {p["index"]: p for p in priorities}
    eligible = []
    for r in records:
        if r.not_checked_reason:
            continue
        p = pri.get(r.index)
        if not p:
            continue
        r.checkworthiness = float(p["score"])
        if p["label"] == "checkworthy_factual" and r.checkworthiness >= min_score:
            eligible.append(r)
    eligible.sort(key=lambda r: r.checkworthiness or 0, reverse=True)
    selected = [r.index for r in eligible[:max(0, limit)]]
    for r in records:
        r.auto_verified = r.index in selected
    return selected


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
            yield _event(self, ctx, {"claim_records": [], "claims_for_ranking_list": []}, "gated")
            return
        raw = (st.get("extraction") or {}).get("claims", [])
        cap = ec.policy["claims"]["max_extracted"]
        if len(raw) > cap:
            ec.log("extract", "max_extracted", "skipped", f"{len(raw) - cap} claims over cap dropped")
        records: list[dict[str, Any]] = []
        rankable: list[dict[str, Any]] = []
        for i, c in enumerate(raw[:cap]):
            try:
                claim = ExtractedClaim.model_validate(c)
            except Exception as e:  # schema guardrail: malformed claims are dropped, not guessed at
                ec.log("extract", "claim_schema_invalid", "skipped", str(e)[:200], i)
                continue
            tier, rec_reason = classify_statement(claim, ec.policy)
            rec = ClaimRecord(index=i, start_s=ts_to_seconds(claim.start_ts), claim=claim, effective_tier=tier,
                              not_checked_reason=rec_reason)
            if rec_reason == "outside_policy":
                ec.log("policy", "never_check_tier", "skipped", claim.topic, i)
            if tier != claim.policy_tier and tier != "never":
                ec.log("policy", "tier_raised_in_code", "flagged", f"{claim.policy_tier} -> {tier} ({claim.topic})", i)
            records.append(rec.model_dump())
            if rec.not_checked_reason is None:
                rankable.append({"index": i, "claim": claim.claim, "speaker": claim.speaker, "topic": claim.topic})
        yield _event(self, ctx, {"claim_records": records, "claims_for_ranking_list": rankable,
                                 "claims_for_ranking": ranking_payload(rankable)},
                     f"{len(rankable)} of {len(records)} statements are verifiable factual claims")


class Selector(BaseAgent):
    """Stage 4 guardrail: auto-verify only the top few check-worthy factual claims.

    Every other factual claim is left verifiable on request (not_checked_reason stays empty), so a new
    video isn't an empty page but the run doesn't pay for claims nobody asks about.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
        rules = ec.policy["claims"]
        limit = ec.settings.auto_verify if ec.settings.auto_verify >= 0 else int(rules["auto_verify"])
        selected = pick_auto_verify(records, (st.get("priorities") or {}).get("priorities", []),
                                    rules["min_checkworthiness"], limit)
        minimum = ec.settings.min_statements
        if minimum and len(records) < minimum:
            reason = (f"Only {len(records)} substantive statement{'s' if len(records) != 1 else ''} found "
                      f"(minimum {minimum}).")
            ec.log("select", "too_few_statements", "skipped", reason)
            yield _event(self, ctx, {"claim_records": [r.model_dump() for r in records], "selected": [],
                                     "gate": {"skip": True, "stage": "select", "reason": reason}}, reason)
            return
        yield _event(self, ctx, {"claim_records": [r.model_dump() for r in records], "selected": selected},
                     f"{len(selected)} claims selected for automatic verification")


class ClaimFanOut(BaseAgent):
    """Stage 5-9: verifies each selected claim in its own isolated ADK session, max N at once."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import asyncio

        from .verifier import verify_claim

        ec = get_context()
        st = ctx.session.state
        records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
        selected = set(st.get("selected", []))
        sem = asyncio.Semaphore(ec.settings.max_concurrent_claims)
        meta = {"video_title": st.get("video_title", ""), "track": ec.track}

        total = len(selected)
        done = 0

        async def report() -> None:
            await report_progress(ec, f"Verifying the top claims ({done} of {total} done)", 60 + int(35 * done / max(total, 1)))

        async def run(rec: ClaimRecord) -> None:
            nonlocal done
            async with sem:
                try:
                    rec.verdict, cached_id, emb = await verify_claim(rec, meta)
                    if cached_id:
                        ec.cached_ids[rec.index] = cached_id
                    if emb is not None:
                        ec.embeddings[rec.index] = emb
                except Exception as e:  # one claim failing must not sink the episode
                    ec.log("verify", "claim_failed", "skipped", f"{type(e).__name__}: {e}", rec.index)
                    rec.not_checked_reason = "error"
                    if is_budget_error(e):
                        rec.not_checked_reason = "budget"
                finally:
                    done += 1
                    await report()

        if total:
            await report()
        await asyncio.gather(*(run(r) for r in records if r.index in selected))
        yield _event(self, ctx, {"claim_records": [r.model_dump() for r in records]}, "verification done")


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
            "cost_usd": round(ec.budget.spent_usd, 4), "tokens_in": ec.budget.tokens_in, "tokens_out": ec.budget.tokens_out,
        })
        yield _event(self, ctx, {"published": True, "tally": tally, "not_checked": not_checked, "pending_review": pending,
                                 "statement_counts": statement_counts},
                     f"published: {tally}")
