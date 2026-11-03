"""Sources for claims: one Parallel web search per claim, whatever it returns is shown, plus a short summary of them.

One claim ("Check sources")                                  POST /claims/{id}/sources
  precheck (code)  a factual claim, not redacted, not already done, video under its cost cap
  search           tools/evidence.search_sources: the claim's own words -> up to 5 results with title, link, date
                   and the passage of the page text that best matches the claim
  summarize (ADK)  one cheap model call writes 1-2 sentences on what the sources together say about the subject, with
                   their own figures and dates, citing them as [1], [2]. Checked in code: citations to sources that
                   don't exist are removed, and a summary using judging words (confirms, contradicts, true, false, ...)
                   is dropped. If this step fails or the budget runs out, the sources are saved without a summary
  save             on the claim, for everyone (an empty result is saved too: "No sources found")

Every claim of a video ("Check sources for all claims")      POST /episodes/{id}/sources-all
  the same search + summary for each claim that has none yet, a few at a time (settings.sources_concurrency), each
  saved the moment it is ready. Limits: at most settings.sources_all_max_searches searches per press (earliest claims
  first; press again for the rest), never more than the video's remaining budget pays for, and claims with the same
  wording share one search. Claims not reached go back to 'not requested'.

  Why not one search for many claims: Parallel accepts several queries per request but returns one merged result
  list with no link back to the query that found each result, so results can't be attributed to a claim without a
  model guessing. One search per claim is the unit that gives each claim its own links.

Nothing is filtered after the search and nothing says whether a claim is right: when a source gives a different figure
or period, the summary states the source's own numbers and the reader compares. Both paths hold a per-video lock, so
two runs can't both pass the cost check and overspend.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..config import Settings
from ..context import Budget, EpisodeContext, get_context, is_budget_error, set_context
from ..policy import domain_of, load_policy
from ..schemas import Source, SourcesSummary
from ..tools.evidence import search_sources

log = logging.getLogger("claimcheck")
APP = "claimcheck_sources"

# Statuses from which sources may be looked up (again). 'queued' is set by the web app when the button is pressed.
STARTABLE = ("queued", "not_requested", "failed")
RETRY_MESSAGE = "Couldn't look up sources right now. Try again later."
MAX_SUMMARY_CHARS = 360
# A summary describes the pages; one that grades the statement is dropped (the sources are shown without it).
_JUDGING = re.compile(
    r"\b(confirm(s|ed|ing)?|corroborat\w*|support(s|ed|ing)?|back(s|ed)? up|contradict\w*|disput\w*|refut\w*|debunk\w*|"
    r"true|false|accurate|inaccurate|correct|incorrect|wrong|misleading|verif\w*|consistent with|inconsistent)\b", re.I)

_episode_locks: dict[str, asyncio.Lock] = {}


def lock_for(episode_id: str) -> asyncio.Lock:
    return _episode_locks.setdefault(episode_id, asyncio.Lock())


def same_wording(text: str) -> str:
    """Key for claims that should share one search: lower case, letters and digits only."""
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


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


# --- Summaries ------------------------------------------------------------------------------------

def acceptable_summary(text: str, n_sources: int) -> str:
    """The summary with citations to sources that don't exist removed; "" if it grades the statement or is empty."""
    t = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", text or "")
    t = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", t)).strip()
    if not t or _JUDGING.search(t):
        return ""
    return t if len(t) <= MAX_SUMMARY_CHARS else t[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


async def summarize(claim_text: str, sources: list[Source]) -> str:
    """What the sources say, in 1-2 sentences citing them as [n] (ADK step, cheap model). Never raises; "" on failure."""
    ec = get_context()
    if not sources or not ec.settings.summarize_sources:
        return ""
    from .llm_agents import summarizer_agent

    pages = [{"n": i + 1, "title": s.title, "site": domain_of(s.url), "text": s.page_text or s.excerpt}
             for i, s in enumerate(sources)]
    try:
        runner = InMemoryRunner(agent=summarizer_agent(ec.settings, name=f"source_summarizer_{uuid.uuid4().hex[:6]}"),
                                app_name=APP, plugins=ec.plugins_factory())
        session = await runner.session_service.create_session(app_name=APP, user_id="sources",
                                                              state={"claim_text": claim_text, "pages": pages})
        msg = types.Content(role="user", parts=[types.Part(text="Summarize the pages.")])
        async for _ in runner.run_async(user_id="sources", session_id=session.id, new_message=msg):
            pass
        done = await runner.session_service.get_session(app_name=APP, user_id="sources", session_id=session.id)
        raw = done.state.get("summary")
        text = SourcesSummary.model_validate(raw).summary if raw else ""
    except Exception as e:
        reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
        ec.log("sources", "summary_failed", "skipped", reason[:200])
        return ""
    summary = acceptable_summary(text, len(sources))
    if text.strip() and not summary:
        ec.log("sources", "summary_judging_words", "skipped", text[:200])
    return summary


async def _search(claim_text: str, settings: Settings, policy: dict[str, Any]) -> tuple[list[Source], str]:
    """Search (charged to the video's budget) then the summary. Raises only if the search itself fails."""
    ec = get_context()
    ec.budget.add(settings.search_cost_usd)
    found = await search_sources(claim_text, settings, policy)
    return found, await summarize(claim_text, found)


def _context(episode_id: str, ep: dict[str, Any], settings: Settings, store: Any) -> EpisodeContext:
    from .pipeline import make_plugins_factory

    return EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), settings=settings,
                          policy=load_policy(), store=store,
                          budget=Budget(cap_usd=settings.max_cost_usd_per_episode, spent_usd=float(ep.get("cost_usd") or 0)),
                          plugins_factory=make_plugins_factory(settings))


# --- One claim ---------------------------------------------------------------------------------------

async def run_claim_sources(claim_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for one claim. Never raises: failures are written to the claim as 'failed' with a message."""
    row = await store.get_claim_for_sources(claim_id)
    episode_id = (row or {}).get("episode_id", "")
    async with lock_for(episode_id):
        row = await store.get_claim_for_sources(claim_id)  # re-read inside the lock: another run may have spent budget
        if not row:
            return {"claim_id": claim_id, "status": "failed", "reason": "Statement not found."}
        ep = row.get("episodes") or {}
        cap = settings.max_cost_usd_per_episode
        if float(ep.get("cost_usd") or 0) + settings.search_cost_usd > cap:
            await store.set_sources_status(claim_id, "failed", budget_message(cap))
            return {"claim_id": claim_id, "status": "failed", "reason": budget_message(cap)}
        ec = _context(episode_id, ep, settings, store)
        start = ec.budget.spent_usd
        token = set_context(ec)
        try:
            found, summary = await _search(row["claim_text"], settings, ec.policy)
            await store.save_claim_sources(claim_id, found, summary)
            result = {"claim_id": claim_id, "status": "done", "sources": len(found), "summary": bool(summary)}
        except Exception as e:
            log.warning("source search for claim %s failed: %s: %s", claim_id, type(e).__name__, e)
            await store.set_sources_status(claim_id, "failed", RETRY_MESSAGE)
            result = {"claim_id": claim_id, "status": "failed", "reason": RETRY_MESSAGE}
        finally:
            spent = round(ec.budget.spent_usd - start, 6)
            try:
                await store.add_episode_cost(episode_id, spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
            except Exception:
                log.exception("could not record source lookup cost for %s", claim_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        result["cost_usd"] = round(spent, 4)
        return result


# --- Every claim of a video --------------------------------------------------------------------------

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

        ec = _context(episode_id, ep, settings, store)
        start = ec.budget.spent_usd
        token = set_context(ec)  # the tasks below inherit it
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
                if ec.budget.spent_usd + settings.search_cost_usd > ec.budget.cap_usd:
                    return  # summaries used up the rest of the budget: these claims go back to 'not requested'
                try:
                    searched += 1
                    found, summary = await _search(group[0]["claim_text"], settings, ec.policy)
                    for c in group:  # claims with the same wording share the result
                        await store.save_claim_sources(c["id"], found, summary)
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
            spent = round(ec.budget.spent_usd - start, 6)
            try:
                for c in todo:  # anything not reached goes back, so a viewer can still press "Check sources"
                    if c["id"] not in finished:
                        await store.set_sources_status(c["id"], "not_requested")
                await store.add_episode_cost(episode_id, spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
                await store.update_episode(episode_id, {"sources_batch_status": None, "progress": {}})
            except Exception:
                log.exception("could not finish source lookup bookkeeping for %s", episode_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        return {"status": "done", "searched": searched, "claims": len(todo), "remaining": len(claims) - len(todo),
                "cost_usd": round(spent, 4)}
