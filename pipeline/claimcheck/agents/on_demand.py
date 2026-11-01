"""On-demand verification: verify one factual claim when a viewer presses Verify.

The web app rate-limits requests and marks the claim 'queued'; this module checks the claim is
verifiable, enforces the per-video cost cap (shared with the original run), runs the same
ClaimVerifier as the pipeline, and saves the verdict on the claim row so every later viewer sees it.
False verdicts (and the other review rules) still wait for a person: the claim shows as
'awaiting_review' and the verdict stays hidden by RLS until it's approved.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from ..config import Settings
from ..context import Budget, EpisodeContext, is_budget_error, set_context
from ..policy import load_policy
from ..schemas import ClaimRecord, ExtractedClaim

log = logging.getLogger("claimcheck")

# Statuses from which a claim may be (re)verified. 'queued' is set by the web app when Verify is pressed.
STARTABLE = ("queued", "not_requested", "failed")

# One verification per video at a time, so two requests can't both pass the cost check and overspend.
_episode_locks: dict[str, asyncio.Lock] = {}


def _lock(episode_id: str) -> asyncio.Lock:
    return _episode_locks.setdefault(episode_id, asyncio.Lock())


def budget_message(cap: float) -> str:
    return f"This video has reached its verification budget (${cap:.2f}). No more claims can be verified for it."


def precheck(row: Optional[dict[str, Any]], settings: Settings, policy: Optional[dict[str, Any]] = None) -> tuple[bool, str, int]:
    """Decides, in code, whether a claim may be verified now. Returns (ok, public message, HTTP status)."""
    pol = policy or load_policy()
    if not row:
        return False, "Claim not found.", 404
    ep = row.get("episodes") or {}
    if ep.get("status") not in ("done", "in_review"):
        return False, "This video hasn't finished its first pass yet.", 409
    allowed = pol.get("on_demand", {}).get("statement_types", ["factual_claim"])
    if row.get("statement_type") not in allowed:
        return False, "Only factual claims can be verified. Opinions, forecasts and rhetoric are tagged instead.", 409
    if row.get("policy_tier") == "never" or row.get("not_checked_reason") == "outside_policy":
        return False, "This claim is outside our content policy.", 409
    status = row.get("verification_status")
    if status == "verified":
        return False, "Already verified.", 409
    if status == "awaiting_review":
        return False, "Already verified; a reviewer is checking the verdict before it's shown.", 409
    if status == "verifying":
        return False, "Already being verified.", 409
    if status not in STARTABLE:
        return False, "This claim can't be verified.", 409
    if float(ep.get("cost_usd") or 0) >= settings.max_cost_usd_per_episode:
        return False, budget_message(settings.max_cost_usd_per_episode), 409
    return True, "", 200


def _clock(s: int) -> str:
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def record_from_row(row: dict[str, Any]) -> ClaimRecord:
    """Rebuilds the pipeline's ClaimRecord from a stored claims row."""
    tier = row.get("policy_tier") or "normal"
    claim = ExtractedClaim(
        start_ts=_clock(int(row.get("start_s") or 0)), speaker=row.get("speaker") or "Speaker",
        claim=row["claim_text"], context_quote=row.get("context_quote") or row["claim_text"],
        pestle_area=row.get("pestle_area") or "economic", topic=row.get("topic") or "general",
        statement_type=row.get("statement_type") or "factual_claim", claim_type="fact", policy_tier=tier,
        refers_to_visual=bool(row.get("refers_to_visual")),
    )
    return ClaimRecord(index=int(row.get("idx") or 0), start_s=int(row.get("start_s") or 0), claim=claim,
                       effective_tier=tier, checkworthiness=row.get("checkworthiness"))


async def run_claim_verification(claim_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Verifies one claim. Never raises: failures are written to the claim row as 'failed' with a message."""
    from .pipeline import make_plugins_factory
    from .verifier import verify_claim

    policy = load_policy()
    row = await store.get_claim_for_verification(claim_id)
    episode_id = (row or {}).get("episode_id", "")
    async with _lock(episode_id):
        # Re-read inside the lock: an earlier verification of this video may have just spent budget.
        row = await store.get_claim_for_verification(claim_id)
        if not row:
            return {"claim_id": claim_id, "status": "failed", "reason": "Claim not found."}
        ep = row.get("episodes") or {}
        cap = settings.max_cost_usd_per_episode
        spent = float(ep.get("cost_usd") or 0)
        if spent >= cap:
            await store.set_claim_status(claim_id, "failed", budget_message(cap))
            return {"claim_id": claim_id, "status": "failed", "reason": budget_message(cap)}

        track = ((ep.get("channels") or {}).get("track")) or "finance_health"
        ec = EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), track=track,
                            settings=settings, policy=policy, store=store,
                            budget=Budget(cap_usd=cap, spent_usd=spent), plugins_factory=make_plugins_factory(settings))
        token = set_context(ec)
        result: dict[str, Any]
        try:
            rec = record_from_row(row)
            ec.log("on_demand", "verify_requested", "flagged", "", rec.index)
            fv, cached_id, emb = await verify_claim(rec, {"video_title": ep.get("title") or "", "track": track})
            await store.save_claim_verdict(claim_id, fv, cached_id, emb, settings.judge_model)
            pending = fv.review_status == "pending"
            await store.refresh_episode_after_verify(episode_id, pending)
            result = {"claim_id": claim_id, "status": "awaiting_review" if pending else "verified",
                      "from_cache": fv.from_cache}
        except Exception as e:
            if is_budget_error(e):
                msg = budget_message(cap)
            else:
                log.exception("on-demand verification of claim %s failed", claim_id)
                msg = "Couldn't verify this claim right now. Try again later."
            ec.log("on_demand", "verify_failed", "skipped", f"{type(e).__name__}: {e}")
            await store.set_claim_status(claim_id, "failed", msg)
            result = {"claim_id": claim_id, "status": "failed", "reason": msg}
        finally:
            try:
                await store.add_episode_cost(episode_id, ec.budget.spent_usd - spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
            except Exception:
                log.exception("could not record cost for claim %s", claim_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        result["cost_usd"] = round(ec.budget.spent_usd - spent, 4)
        return result
