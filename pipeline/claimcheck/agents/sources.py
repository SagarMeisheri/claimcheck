"""Sources for claims: one Parallel web search per claim, whatever it returns is shown.

One claim ("Check sources")                                  POST /claims/{id}/sources
  precheck (code)  a factual claim, not redacted, not already done, video under its cost cap
  search           tools/evidence.search_sources: the claim's own words -> up to 5 results with title, link, date
                   and the excerpt Parallel took from the page
  save             on the claim, for everyone (an empty result is saved too: "No sources found")

Every claim of a video ("Check sources for all claims")      POST /episodes/{id}/sources-all
  the same search for each claim that has none yet, a few at a time (settings.sources_concurrency), each saved
  the moment it returns. Limits: at most settings.sources_all_max_searches searches per press (earliest claims
  first; press again for the rest), never more than the video's remaining budget pays for, and claims with the
  same wording share one search. Claims not reached go back to 'not requested'.

  Why not one search for many claims: Parallel accepts several queries per request but returns one merged result
  list with no link back to the query that found each result, so results can't be attributed to a claim without a
  model guessing. One search per claim is the unit that gives each claim its own links.

No model is involved and nothing is filtered after the search, so nothing here judges a claim or a speaker. Both
paths hold a per-video lock, so two runs can't both pass the cost check and overspend.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from ..config import Settings
from ..policy import load_policy
from ..tools.evidence import search_sources

log = logging.getLogger("claimcheck")

# Statuses from which sources may be looked up (again). 'queued' is set by the web app when the button is pressed.
STARTABLE = ("queued", "not_requested", "failed")
RETRY_MESSAGE = "Couldn't look up sources right now. Try again later."

_episode_locks: dict[str, asyncio.Lock] = {}


def same_wording(text: str) -> str:
    """Key for claims that should share one search: lower case, letters and digits only."""
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def lock_for(episode_id: str) -> asyncio.Lock:
    return _episode_locks.setdefault(episode_id, asyncio.Lock())


def budget_message(cap: float) -> str:
    return f"This video has used its budget for source searches (${cap:.2f}). No more can be run for it."


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
    if float(ep.get("cost_usd") or 0) + settings.search_cost_usd > settings.max_cost_usd_per_episode:
        return False, budget_message(settings.max_cost_usd_per_episode), 409
    return True, "", 200


async def _search_and_save(store: Any, claim: dict[str, Any], settings: Settings, policy: dict[str, Any]) -> int:
    """One search for one claim, saved straight away. Returns the number of sources (raises on search errors)."""
    sources = await search_sources(claim["claim_text"], settings, policy)
    await store.save_claim_sources(claim["id"], sources)
    return len(sources)


async def run_claim_sources(claim_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for one claim. Never raises: failures are written to the claim as 'failed' with a message."""
    row = await store.get_claim_for_sources(claim_id)
    episode_id = (row or {}).get("episode_id", "")
    async with lock_for(episode_id):
        row = await store.get_claim_for_sources(claim_id)  # re-read inside the lock: another run may have spent budget
        if not row:
            return {"claim_id": claim_id, "status": "failed", "reason": "Statement not found."}
        cap = settings.max_cost_usd_per_episode
        if float((row.get("episodes") or {}).get("cost_usd") or 0) + settings.search_cost_usd > cap:
            await store.set_sources_status(claim_id, "failed", budget_message(cap))
            return {"claim_id": claim_id, "status": "failed", "reason": budget_message(cap)}
        try:
            n = await _search_and_save(store, row, settings, load_policy())
            result = {"claim_id": claim_id, "status": "done", "sources": n}
        except Exception as e:
            log.warning("source search for claim %s failed: %s: %s", claim_id, type(e).__name__, e)
            await store.set_sources_status(claim_id, "failed", RETRY_MESSAGE)
            result = {"claim_id": claim_id, "status": "failed", "reason": RETRY_MESSAGE}
        # A search is billed whether or not it returned anything.
        await store.add_episode_cost(episode_id, settings.search_cost_usd, 0, 0)
        result["cost_usd"] = settings.search_cost_usd
        return result


async def run_video_sources(episode_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for every claim of a video that has none yet. Never raises."""
    async with lock_for(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "The video hasn't finished being analysed."}
        claims = sorted(await store.list_batch_claims(episode_id), key=lambda r: r.get("start_s") or 0)
        groups: dict[str, list[dict[str, Any]]] = {}  # same wording -> claims sharing one search, earliest first
        for c in claims:
            groups.setdefault(same_wording(c["claim_text"]), []).append(c)
        left = settings.max_cost_usd_per_episode - float(ep.get("cost_usd") or 0)
        affordable = max(0, int(left / settings.search_cost_usd + 1e-9)) if settings.search_cost_usd > 0 else len(groups)
        searches = list(groups.values())[:max(0, min(settings.sources_all_max_searches, affordable))]
        todo = [c for g in searches for c in g]
        if not todo:
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "Nothing to look up." if not claims else "Over the video's budget."}

        policy = load_policy()
        total, done, searched = len(searches), 0, 0
        finished: set[str] = set()
        gate = asyncio.Semaphore(max(1, settings.sources_concurrency))
        progress_lock = asyncio.Lock()

        async def progress() -> None:
            await store.update_episode(episode_id, {"progress": {"label": f"Checking sources: {done} of {total} done",
                                                                 "pct": int(100 * done / total)}})

        async def one(group: list[dict[str, Any]]) -> None:
            nonlocal done, searched
            async with gate:
                try:
                    searched += 1
                    found = await search_sources(group[0]["claim_text"], settings, policy)
                    for c in group:  # claims with the same wording share the result
                        await store.save_claim_sources(c["id"], found)
                except Exception as e:
                    log.warning("source search for claim %s failed: %s: %s", group[0]["id"], type(e).__name__, e)
                    for c in group:
                        await store.set_sources_status(c["id"], "failed", RETRY_MESSAGE)
                finished.update(c["id"] for c in group)
                async with progress_lock:
                    done += 1
                    await progress()

        try:
            for c in todo:  # every selected claim shows "searching" straight away
                await store.set_sources_status(c["id"], "searching")
            await store.update_episode(episode_id, {"sources_batch_status": "running"})
            await progress()
            await asyncio.gather(*(one(g) for g in searches))
        except Exception:
            log.exception("source lookup for episode %s failed", episode_id)
        finally:
            try:
                for c in todo:  # anything not reached goes back, so a viewer can still press "Check sources"
                    if c["id"] not in finished:
                        await store.set_sources_status(c["id"], "not_requested")
                await store.add_episode_cost(episode_id, searched * settings.search_cost_usd, 0, 0)
                await store.update_episode(episode_id, {"sources_batch_status": None, "progress": {}})
            except Exception:
                log.exception("could not finish source lookup bookkeeping for %s", episode_id)
        return {"status": "done", "searched": searched, "claims": len(todo), "remaining": len(claims) - len(todo),
                "cost_usd": round(searched * settings.search_cost_usd, 4)}
