"""Sources on request: look up sources for one factual claim when a viewer presses "Check sources".

The web app rate-limits requests and marks the claim 'queued'; this module checks the claim is eligible, enforces
the per-video cost cap (shared with the first pass), runs agents/sources.py and saves what it found on the claim,
so every later viewer sees it. The result is sources only: nothing is judged, so nothing waits for review.
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

# Statuses from which sources may be looked up (again). 'queued' is set by the web app when the button is pressed.
STARTABLE = ("queued", "not_requested", "failed")

# One lookup per video at a time, so two requests can't both pass the cost check and overspend.
_episode_locks: dict[str, asyncio.Lock] = {}


def lock_for(episode_id: str) -> asyncio.Lock:
    return _episode_locks.setdefault(episode_id, asyncio.Lock())


def budget_message(cap: float) -> str:
    return f"This video has used its budget for source lookups (${cap:.2f}). No more can be run for it."


def precheck(row: Optional[dict[str, Any]], settings: Settings) -> tuple[bool, str, int]:
    """Decides, in code, whether sources may be looked up now. Returns (ok, public message, HTTP status)."""
    if not row:
        return False, "Statement not found.", 404
    ep = row.get("episodes") or {}
    if ep.get("status") not in ("done", "in_review"):
        return False, "This video hasn't finished being analysed yet.", 409
    if row.get("statement_type") != "factual_claim":
        return False, "Sources can only be looked up for claims, not opinions or forecasts.", 409
    if row.get("policy_tier") == "never" or row.get("not_checked_reason") == "outside_policy":
        return False, "This statement is outside our content policy.", 409
    status = row.get("sources_status")
    if status == "done":
        return False, "Sources have already been looked up.", 409
    if status == "searching":
        return False, "Already searching.", 409
    if status not in STARTABLE:
        return False, "Sources can't be looked up for this statement.", 409
    if float(ep.get("cost_usd") or 0) >= settings.max_cost_usd_per_episode:
        return False, budget_message(settings.max_cost_usd_per_episode), 409
    return True, "", 200


def _clock(s: int) -> str:
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def record_from_row(row: dict[str, Any]) -> ClaimRecord:
    """Rebuilds the pipeline's ClaimRecord from a stored claims row."""
    claim = ExtractedClaim(
        start_ts=_clock(int(row.get("start_s") or 0)), speaker=row.get("speaker") or "Speaker",
        claim=row["claim_text"], context_quote=row.get("context_quote") or row["claim_text"],
        pestle_area=row.get("pestle_area") or "economic", topic=row.get("topic") or "general",
        topics=row.get("topics") or [], statement_type="factual_claim", policy_tier="normal",
        refers_to_visual=bool(row.get("refers_to_visual")),
    )
    return ClaimRecord(index=int(row.get("idx") or 0), start_s=int(row.get("start_s") or 0), claim=claim, effective_tier="normal")


async def run_claim_sources(claim_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for one claim. Never raises: failures are written to the claim as 'failed' with a message."""
    from .pipeline import make_plugins_factory
    from .sources import find_sources

    row = await store.get_claim_for_sources(claim_id)
    episode_id = (row or {}).get("episode_id", "")
    async with lock_for(episode_id):
        # Re-read inside the lock: an earlier lookup on this video may have just spent budget.
        row = await store.get_claim_for_sources(claim_id)
        if not row:
            return {"claim_id": claim_id, "status": "failed", "reason": "Statement not found."}
        ep = row.get("episodes") or {}
        cap = settings.max_cost_usd_per_episode
        spent = float(ep.get("cost_usd") or 0)
        if spent >= cap:
            await store.set_sources_status(claim_id, "failed", budget_message(cap))
            return {"claim_id": claim_id, "status": "failed", "reason": budget_message(cap)}

        ec = EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), settings=settings,
                            policy=load_policy(), store=store, budget=Budget(cap_usd=cap, spent_usd=spent),
                            plugins_factory=make_plugins_factory(settings))
        token = set_context(ec)
        result: dict[str, Any]
        try:
            rec = record_from_row(row)
            sources = await find_sources(rec, {"video_title": ep.get("title") or ""})
            await store.save_claim_sources(claim_id, sources)
            result = {"claim_id": claim_id, "status": "done", "sources": len(sources)}
        except Exception as e:
            if is_budget_error(e):
                msg = budget_message(cap)
            else:
                log.exception("source lookup for claim %s failed", claim_id)
                msg = "Couldn't look up sources right now. Try again later."
            ec.log("sources", "lookup_failed", "skipped", f"{type(e).__name__}: {e}")
            await store.set_sources_status(claim_id, "failed", msg)
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
