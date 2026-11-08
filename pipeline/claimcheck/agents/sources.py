"""Sources for answers: one lookup per answer, shared by the button, "Check sources for all" and the automatic path.

Lookup (lookup_answer), per answer: the answer-tag Workflow (agents/qa_tags.py)
  tag      one ADK classifier call: answer type, claim type and the conflict checks the speakers' incentive tags call for.
           It routes the answer: a pure opinion is exempt (no planner, no search)
  plan     research.py: a planner writes the checkable points and up to 3 queries; nothing checkable -> no search
  search   one Parallel request carrying all the queries; every page returned is kept (research.py)
  ground   one classifier call: grounding, match (and missing context), then the skepticism rules in code
  save     the pages and claims.qa_tags; an answer with no search keeps its tags with sources_route 'skip'

So an answer costs 1 classifier call, or 1 planner call, 1 search request and 2 classifier calls when researched. How the question was
asked is tagged once per video for all questions (agents/interview.py).

One answer ("Check sources")                                  POST /claims/{id}/sources
Every answer of a video ("Check sources for all statements")  POST /episodes/{id}/sources-all
  a few at a time (settings.sources_concurrency), each saved the moment it is ready. Answers the planner skips go back to
  'not requested' with sources_route 'skip', and the next press doesn't take them again. Limits: settings.max_searches_per_video lookups
  per video in total, buttons and automatic ones together (0 = no limit; earliest answers first), never more than the video's remaining
  budget pays for, and answers with the same wording share one.
As the extractor writes (AutoSources): each saved answer starts its lookup at once, up to settings.max_streamed_lookups, because the
  extractor's own cost is only counted when it ends.

All paths hold a per-video lock, so two runs can't both pass the cost check and overspend.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, NamedTuple, Optional

from ..config import Settings
from ..context import Budget, EpisodeContext, get_context, is_budget_error, set_context
from ..policy import load_policy
from ..profiles import creator_context, is_role_label, name_key, search_location, section_for, speaker_context
from ..schemas import NO_SOURCE_TYPES, ClaimRecord, Source

log = logging.getLogger("claimcheck")
APP = "claimcheck_sources"

# Statuses from which sources may be looked up (again). 'queued' is set by the web app when the button is pressed.
STARTABLE = ("queued", "not_requested", "failed")
RETRY_MESSAGE = "Couldn't look up sources right now. Try again later."
# Text that grades a statement: the Q&A view's questions must not use it (agents/qa.py).
_JUDGING = re.compile(
    r"\b(confirm(s|ed|ing)?|corroborat\w*|support(s|ed|ing)?|back(s|ed)? up|contradict\w*|disput\w*|refut\w*|debunk\w*|"
    r"true|false|accurate|inaccurate|correct|incorrect|wrong|misleading|verif\w*|consistent with|inconsistent)\b", re.I)

_episode_locks: dict[str, asyncio.Lock] = {}


def lock_for(episode_id: str) -> asyncio.Lock:
    return _episode_locks.setdefault(episode_id, asyncio.Lock())


def same_wording(text: str) -> str:
    """Key for answers that should share one lookup: lower case, letters and digits only."""
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def search_cap_message(cap: int) -> str:
    return f"This video has used its {cap} source lookups. No more can be run for it."


async def search_room(store: Any, episode_id: str, settings: Settings, recheck: bool = False) -> Optional[int]:
    """How many more source lookups this video may have (None = no limit). A recheck replaces lookups, so it only has the cap itself."""
    cap = settings.max_searches_per_video
    if cap <= 0:
        return None
    return cap if recheck else max(0, cap - await store.count_looked_up(episode_id))


def budget_message(cap: float) -> str:
    return f"This video has used its budget for source searches (${cap:.2f}). No more can be run for it."


def precheck(row: Optional[dict[str, Any]], settings: Settings) -> tuple[bool, str, int]:
    """Decides, in code, whether sources may be looked up now. Returns (ok, public message, HTTP status)."""
    if not row:
        return False, "Statement not found.", 404
    ep = row.get("episodes") or {}
    if ep.get("status") not in ("done", "in_review"):
        return False, "This video hasn't finished being analysed yet.", 409
    if row.get("statement_type") in NO_SOURCE_TYPES:
        return False, "Questions don't have sources to look up.", 409
    if row.get("policy_tier") == "never" or row.get("not_checked_reason") == "outside_policy":
        return False, "This statement is outside our content policy.", 409
    status = row.get("sources_status")
    if status == "done":
        return False, "Sources have already been looked up.", 409
    if status == "searching":
        return False, "Already searching.", 409
    if status not in STARTABLE:
        return False, "Sources can't be looked up for this statement.", 409
    if float(ep.get("cost_usd") or 0) + settings.lookup_cost_estimate_usd > settings.max_cost_usd_per_episode:
        return False, budget_message(settings.max_cost_usd_per_episode), 409
    return True, "", 200


# --- Context for a lookup --------------------------------------------------------------------------

class VideoContext:
    """The creator and speaker profiles of one video, loaded once and shared by every lookup in it."""

    def __init__(self, store: Any, episode: dict[str, Any]) -> None:
        self.store, self.episode = store, episode or {}
        self._loaded = False
        self.creator: Optional[dict[str, Any]] = None
        self.speakers: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, dict[str, Any]] = {}  # episode_speakers rows by label, with the speakers row and the incentive tags

    async def load(self) -> "VideoContext":
        if self._loaded:
            return self
        self._loaded = True
        try:
            if self.episode.get("creator_id"):
                self.creator = await self.store.get_creator(self.episode["creator_id"])
            for r in await self.store.get_episode_speakers(self.episode.get("id", "")):
                self.speakers[r.get("label") or ""] = r.get("speakers") or {}
                self.rows[r.get("label") or ""] = r
        except Exception:  # context makes lookups better; it is never a reason for one to fail
            log.exception("could not load profiles for episode %s", self.episode.get("id"))
        return self

    def for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        """What the planner and the tags get about one answer."""
        sections = self.episode.get("sections") or []
        idx = claim.get("section_idx")
        section = next((s for s in sections if s.get("idx") == idx), None) if idx is not None else None
        section = section or section_for(int(claim.get("start_s") or 0), sections)
        label = claim.get("speaker") or ""
        row = self.row_for(label)
        host = self.host_row()
        return {k: v for k, v in {
            "statement": claim.get("claim_text", ""), "statement_type": claim.get("statement_type"),
            "context_quote": claim.get("context_quote"),
            "question": claim.get("question"), "question_spoken": claim.get("question_quote"),
            "question_kind": claim.get("question_kind"), "asked_by": claim.get("asked_by"),
            "video": {"id": self.episode.get("youtube_video_id"), "title": self.episode.get("title"),
                      "channel": (self.creator or {}).get("youtube_channel_name")},
            "discussing": claim.get("statement_context") or (section or {}).get("summary") or "",
            "section": (section or {}).get("title") or "",
            "speaker": speaker_context((row or {}).get("speakers"), label),
            "speaker_incentives": {**((row or {}).get("incentives") or {}), **((row or {}).get("incentives_internal") or {})},
            "host": speaker_context((host or {}).get("speakers"), (host or {}).get("label", "")),
            "host_incentives": {**((host or {}).get("incentives") or {}), **((host or {}).get("incentives_internal") or {})},
            "description_notes": (self.episode.get("interaction") or {}).get("description_notes") or [],
            "creator": creator_context(self.creator),
        }.items() if v}

    def row_for(self, label: str) -> Optional[dict[str, Any]]:
        """The episode_speakers row for a speaker label: by label, by name, or "Host" -> the one host."""
        if label in self.rows:
            return self.rows[label]
        key = name_key(label)
        hit = next((r for r in self.rows.values() if name_key(r.get("label") or "") == key), None)
        if hit or not is_role_label(label) or "host" not in label.lower():
            return hit
        hosts = [r for r in self.rows.values() if r.get("role") == "host"]
        return hosts[0] if len(hosts) == 1 else None

    def host_row(self) -> Optional[dict[str, Any]]:
        hosts = [r for r in self.rows.values() if r.get("role") == "host" and r.get("speakers")]
        return hosts[0] if hosts else None

    @property
    def location(self) -> Optional[str]:
        return search_location(self.creator, get_context().settings.default_search_location)


# --- One lookup ----------------------------------------------------------------------------------------

class Lookup(NamedTuple):
    route: str  # "skip" (no search: a pure opinion, or nothing checkable) or "related" (looked up)
    related: list[Source]
    research: Any = None  # the research.Research when the answer was looked up
    tags: Optional[dict[str, Any]] = None  # claims.qa_tags (agents/qa_tags.py)


async def lookup_answer(claim: dict[str, Any], vctx: VideoContext, *, force: bool) -> Lookup:
    """Tag, and research when the claim type calls for it. `force` (a viewer pressed the button) searches an answer the planner found
    nothing checkable in."""
    from .qa_tags import tag_answer

    t = await tag_answer(vctx.for_claim(claim), vctx.location, force=force)
    if t.research is None:
        return Lookup("skip", [], None, t.tags)
    return Lookup("related", t.research.related, t.research, t.tags)


async def _save(store: Any, claim_id: str, found: Lookup) -> None:
    if found.route == "skip":
        await store.save_sources_route(claim_id, "skip", qa_tags=found.tags)
        return
    r = found.research
    await store.save_claim_sources(claim_id, found.related, "", r.match, counter=[], counter_summary="", route="related",
                                   research=r.stored(), qa_tags=found.tags)


def _context(episode_id: str, ep: dict[str, Any], settings: Settings, store: Any) -> EpisodeContext:
    from .pipeline import make_plugins_factory

    return EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), settings=settings,
                          policy=load_policy(), store=store,
                          budget=Budget(cap_usd=settings.max_cost_usd_per_episode, spent_usd=float(ep.get("cost_usd") or 0)),
                          plugins_factory=make_plugins_factory(settings))


# --- One answer ---------------------------------------------------------------------------------------

async def run_claim_sources(claim_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for one answer. Never raises: failures are written to the answer as 'failed' with a message."""
    row = await store.get_claim_for_sources(claim_id)
    episode_id = (row or {}).get("episode_id", "")
    async with lock_for(episode_id):
        row = await store.get_claim_for_sources(claim_id)  # re-read inside the lock: another run may have spent budget
        if not row:
            return {"claim_id": claim_id, "status": "failed", "reason": "Statement not found."}
        ep = row.get("episodes") or {}
        cap = settings.max_cost_usd_per_episode
        if float(ep.get("cost_usd") or 0) + settings.lookup_cost_estimate_usd > cap:
            await store.set_sources_status(claim_id, "failed", budget_message(cap))
            return {"claim_id": claim_id, "status": "failed", "reason": budget_message(cap)}
        room = await search_room(store, episode_id, settings)
        if room is not None and room <= 0:
            msg = search_cap_message(settings.max_searches_per_video)
            await store.set_sources_status(claim_id, "failed", msg)
            return {"claim_id": claim_id, "status": "failed", "reason": msg}
        ec = _context(episode_id, ep, settings, store)
        start = ec.budget.spent_usd
        token = set_context(ec)
        try:
            vctx = await VideoContext(store, {**ep, "id": episode_id}).load()
            found = await lookup_answer(row, vctx, force=True)
            await _save(store, claim_id, found)
            result = {"claim_id": claim_id, "status": "done", "sources": len(found.related), "match": (found.research.match if found.research else ""),
                      "grounding": ((found.tags or {}).get("grounding") or {}).get("label", "")}
        except Exception as e:
            log.warning("source search for answer %s failed: %s: %s", claim_id, type(e).__name__, e)
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


# --- Every answer of a video --------------------------------------------------------------------------

async def run_video_sources(episode_id: str, *, settings: Settings, store: Any, recheck: bool = False) -> dict[str, Any]:
    """Looks up sources for every answer of a video that has none yet. Never raises.
    recheck: every answer is looked up again (finished ones too, and ones the planner once skipped); each new result replaces the
    old one, and an answer not reached (over budget) keeps the result it had."""
    async with lock_for(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "The video hasn't finished being analysed."}
        claims = sorted(await store.list_batch_claims(episode_id, recheck) if recheck else await store.list_batch_claims(episode_id),
                        key=lambda r: r.get("start_s") or 0)
        before = {c["id"]: c.get("sources_status") or "not_requested" for c in claims}  # what an unreached answer goes back to
        groups: dict[str, list[dict[str, Any]]] = {}  # same wording -> answers sharing one lookup, earliest first
        for c in claims:
            groups.setdefault(same_wording(c["claim_text"]), []).append(c)
        left = settings.max_cost_usd_per_episode - float(ep.get("cost_usd") or 0)
        each = settings.lookup_cost_estimate_usd  # the most one lookup can cost
        affordable = max(0, int(left / each + 1e-9)) if each > 0 else len(groups)
        room = await search_room(store, episode_id, settings, recheck)
        limit = len(groups) if room is None else room  # None = no count limit: only the video's budget limits it
        searches = list(groups.values())[:max(0, min(limit, affordable))]
        todo = [c for g in searches for c in g]
        if not todo:
            await store.update_episode(episode_id, {"sources_batch_status": None})
            reason = ("Nothing to look up." if not claims else search_cap_message(settings.max_searches_per_video) if room == 0
                      else "Over the video's budget.")
            return {"status": "skipped", "reason": reason}

        ec = _context(episode_id, ep, settings, store)
        start = ec.budget.spent_usd
        token = set_context(ec)  # the tasks below inherit it
        vctx = await VideoContext(store, {**ep, "id": episode_id}).load()
        total, done, searched, skipped = len(searches), 0, 0, 0
        finished: set[str] = set()
        gate = asyncio.Semaphore(max(1, settings.sources_concurrency))
        progress_lock = asyncio.Lock()

        async def progress() -> None:
            await store.update_episode(episode_id, {"progress": {"label": f"Checking sources: {done} of {total} done",
                                                                 "pct": int(100 * done / total)}})

        async def one(group: list[dict[str, Any]]) -> None:
            nonlocal done, searched, skipped
            async with gate:
                if ec.budget.spent_usd + settings.search_cost_usd > ec.budget.cap_usd:
                    return  # the lookups before it used up the rest of the budget: these answers go back to 'not requested'
                try:
                    found = await lookup_answer(group[0], vctx, force=False)
                    if found.route == "skip":
                        skipped += 1
                    else:
                        searched += 1
                    for c in group:  # answers with the same wording share the result
                        await _save(store, c["id"], found)
                except Exception as e:
                    log.warning("source search for answer %s failed: %s: %s", group[0]["id"], type(e).__name__, e)
                    for c in group:
                        await store.set_sources_status(c["id"], "failed", RETRY_MESSAGE)
                finished.update(c["id"] for c in group)
                async with progress_lock:
                    done += 1
                    await progress()

        try:
            for c in todo:  # every selected answer shows "searching" straight away
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
                        await store.set_sources_status(c["id"], "done" if before.get(c["id"]) == "done" else "not_requested")
                await store.add_episode_cost(episode_id, spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
                await store.update_episode(episode_id, {"sources_batch_status": None, "progress": {}})
            except Exception:
                log.exception("could not finish source lookup bookkeeping for %s", episode_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        return {"status": "done", "searched": searched, "skipped": skipped, "claims": len(todo),
                "remaining": len(claims) - len(todo), "cost_usd": round(spent, 4)}


# --- As the extractor writes -----------------------------------------------------------------------------

class AutoSources:
    """Starts a source lookup for each answer as soon as it is saved, while the extractor is still writing the rest
    (settings.auto_sources_as_found). The same lookup as the button and the batch: an answer with nothing checkable costs one
    planner call.

    Lookups run in the extraction's own context, so they are charged to the same video budget. The extractor's cost is
    only counted when it ends, so at most settings.max_streamed_lookups start this way; the batch that follows the
    extraction (and the button) pick up the rest. Never raises into the extraction.
    """

    def __init__(self, ec: EpisodeContext) -> None:
        self.ec, self.settings, self.store = ec, ec.settings, ec.store
        self.limit = ec.settings.max_streamed_lookups
        self.started = 0
        self._gate = asyncio.Semaphore(max(1, ec.settings.sources_concurrency))
        self._tasks: set[asyncio.Task] = set()
        self._vctx: Optional[VideoContext] = None
        self._vctx_lock = asyncio.Lock()

    def submit(self, rec: ClaimRecord) -> None:
        """Called for every saved statement. Questions, redacted statements, answers by someone not profiled yet and anything past the
        limit are left for the batch after extraction."""
        if rec.not_checked_reason == "outside_policy" or rec.claim.statement_type in NO_SOURCE_TYPES or self.started >= self.limit:
            return
        label = (rec.claim.speaker or "").strip()
        if label and not is_role_label(label) and name_key(label) not in self.ec.prepared_speakers:
            return  # named, but not profiled yet: the batch after extraction takes it, once SpeakerProfiler has profiled them
        self.started += 1
        task = asyncio.create_task(self._one(rec.index))  # inherits the extraction's context (budget, settings)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _context(self) -> VideoContext:
        async with self._vctx_lock:
            if self._vctx is None:  # the creator's profile is known now; the speakers' are built after the extraction
                ep = await self.store.get_episode(self.ec.episode_id) or {}
                self._vctx = await VideoContext(self.store, {**ep, "id": self.ec.episode_id,
                                                            "creator_id": (self.ec.creator or {}).get("id") or ep.get("creator_id")}).load()
            return self._vctx

    async def _one(self, idx: int) -> None:
        ec, cid, final = self.ec, None, False
        try:
            if ec.budget.spent_usd + self.settings.search_cost_usd > ec.budget.cap_usd:
                return  # nothing marked yet, so there is nothing to undo
            room = await search_room(self.store, ec.episode_id, self.settings)
            if room is not None and room <= 0:
                return
            row = await self.store.get_claim_row(ec.episode_id, idx)
            if not row or row.get("sources_status") not in ("not_requested", "failed"):
                return
            cid = row["id"]
            await self.store.set_sources_status(cid, "searching")  # on screen as "searching" while it waits for a free slot
            async with self._gate:
                if ec.budget.spent_usd + self.settings.search_cost_usd > ec.budget.cap_usd:
                    return
                found = await lookup_answer(row, await self._context(), force=False)
                await _save(self.store, cid, found)
                final = True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if cid and not is_budget_error(e):
                log.warning("automatic source search for answer %s failed: %s: %s", idx, type(e).__name__, e)
                try:
                    await self.store.set_sources_status(cid, "failed", RETRY_MESSAGE)
                    final = True
                except Exception:
                    log.exception("could not mark answer %s as failed", idx)
        finally:
            if cid and not final:  # budget, cancelled or a failed write: back to "not requested", so the button still works
                try:
                    await asyncio.shield(self.store.set_sources_status(cid, "not_requested"))
                except Exception:
                    log.exception("could not release answer %s", idx)

    async def drain(self) -> None:
        """Waits for the lookups that are still running."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
