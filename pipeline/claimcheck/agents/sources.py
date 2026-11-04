"""Sources for claims: a classifier decides how to look each statement up, then one or two Parallel searches run at
the same time, and a cheap model summarises what they found. Nothing says whether a claim is right.

Lookup workflow (ADK Workflow, one run per statement)                      build_lookup_workflow()
  prepare   code             the statement plus its context: what was being discussed, who said it (speaker profile),
                             which show (creator profile)
  triage    ClassifierNode   one Choice question (prompts.TRIAGE_CRITERIA); the label is the route:
              skip           background, self-description, too vague: no search (a viewer can still press the button)
              related        one search on the statement's own words, with who / where / what in the objective
              data           + a second search for original figures and different numbers for the same thing
              contested      + a second search for other perspectives, aimed away from the speaker's and show's known
                             positions and towards their known criticisms (from their profiles)
  lookup    code             the searches, both at once (tools/evidence.py); a failed second search never sinks the first
Then, in code: the summary (one ADK step, Gemini Flash) of the related excerpts and, separately, of the other ones,
with the source match (relevance only). A summary using judging words (confirms, contradicts, true, false, ...) is
dropped. If the summary fails or the budget runs out, the sources are saved without it.

The classifier calls its model directly, so it uses a Gemini model that charges its own tokens to the video
(guardrails/budget.metered_gemini). If it fails, the lookup still runs: statements with figures go to "data",
the rest to "contested", so a classifier problem never silently drops the second search.

One claim ("Check sources")                                  POST /claims/{id}/sources
  a viewer asked, so "skip" still gets the one related search.
Every statement of a video ("Check sources for all statements")      POST /episodes/{id}/sources-all
  the same lookup for each claim that has none yet, a few at a time (settings.sources_concurrency), each saved the
  moment it is ready. Statements the classifier skips go back to 'not requested' with sources_route 'skip', and the
  next press doesn't take them again. Limits: at most settings.sources_all_max_searches lookups per press (earliest
  claims first), never more than the video's remaining budget pays for, and claims with the same wording share one.

  Why not one search for many claims: Parallel accepts several queries per request but returns one merged result
  list with no link back to the query that found each result, so results can't be attributed to a claim without a
  model guessing. Within one claim that is fine, so the second search sends two queries in one request.

Both paths hold a per-video lock, so two runs can't both pass the cost check and overspend.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, NamedTuple, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from .. import prompts
from ..config import Settings
from ..context import Budget, EpisodeContext, get_context, is_budget_error, set_context
from ..policy import domain_of, load_policy
from ..profiles import creator_context, search_location, section_for, speaker_context
from ..schemas import COUNTER_ROUTES, NO_SOURCE_TYPES, TRIAGE_ROUTES, Source, SourcesSummary
from ..tools.evidence import _said_by, counter_request, related_objective, search_sources

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
_HAS_FIGURE = re.compile(r"\d")

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
    if row.get("statement_type") in NO_SOURCE_TYPES:
        return False, "Questions and personal stories don't have sources to look up.", 409
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


# --- Context for a lookup --------------------------------------------------------------------------

class VideoContext:
    """The creator and speaker profiles of one video, loaded once and shared by every lookup in it."""

    def __init__(self, store: Any, episode: dict[str, Any]) -> None:
        self.store, self.episode = store, episode or {}
        self._loaded = False
        self.creator: Optional[dict[str, Any]] = None
        self.speakers: dict[str, dict[str, Any]] = {}

    async def load(self) -> "VideoContext":
        if self._loaded:
            return self
        self._loaded = True
        try:
            if self.episode.get("creator_id"):
                self.creator = await self.store.get_creator(self.episode["creator_id"])
            for r in await self.store.get_episode_speakers(self.episode.get("id", "")):
                self.speakers[r.get("label") or ""] = r.get("speakers") or {}
        except Exception:  # context makes lookups better; it is never a reason for one to fail
            log.exception("could not load profiles for episode %s", self.episode.get("id"))
        return self

    def for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        """What triage and the searches get about one statement."""
        sections = self.episode.get("sections") or []
        idx = claim.get("section_idx")
        section = next((s for s in sections if s.get("idx") == idx), None) if idx is not None else None
        section = section or section_for(int(claim.get("start_s") or 0), sections)
        label = claim.get("speaker") or ""
        return {k: v for k, v in {
            "statement": claim.get("claim_text", ""), "statement_type": claim.get("statement_type"),
            "discussing": claim.get("statement_context") or (section or {}).get("summary") or "",
            "section": (section or {}).get("title") or "",
            "speaker": speaker_context(self.speakers.get(label), label),
            "creator": creator_context(self.creator),
        }.items() if v}

    @property
    def location(self) -> Optional[str]:
        return search_location(self.creator, get_context().settings.default_search_location)


# --- Summaries ------------------------------------------------------------------------------------

def acceptable_summary(text: str) -> str:
    """The summary, tidied; "" if it grades the statement or is empty."""
    t = re.sub(r"\s*\[\d+\]", "", text or "")  # no reference numbers: the summary is plain text
    t = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", t)).strip()
    if not t or _JUDGING.search(t):
        return ""
    return t if len(t) <= MAX_SUMMARY_CHARS else t[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


class Digest(NamedTuple):
    """The summary step's output: summary and source match for the related sources ("" if none), and a summary of
    the second search's sources."""
    summary: str = ""
    match: str = ""
    counter_summary: str = ""


async def summarize(claim_text: str, sources: list[Source], counter: Optional[list[Source]] = None,
                    ctx: Optional[dict[str, Any]] = None) -> Digest:
    """A plain 1-2 sentence summary of each group of excerpts, and how directly the related ones address the claim
    (ADK step, Gemini 3.8 Flash). Never raises; an empty Digest on failure."""
    ec = get_context()
    counter = counter or []
    if not (sources or counter) or not ec.settings.summarize_sources:
        return Digest()
    from .llm_agents import summarizer_agent

    # Only the excerpts the reader sees, so every sentence of the summary can be checked against them.
    pages = [{"n": i + 1, "group": "RELATED", "title": s.title, "site": domain_of(s.url), "text": s.excerpt}
             for i, s in enumerate(sources) if s.excerpt]
    pages += [{"n": i + 1, "group": "OTHER", "title": s.title, "site": domain_of(s.url), "text": s.excerpt}
              for i, s in enumerate(counter) if s.excerpt]
    if not pages:
        return Digest()
    said = _said_by(ctx or {})
    try:
        runner = InMemoryRunner(agent=summarizer_agent(ec.settings, name=f"source_summarizer_{uuid.uuid4().hex[:6]}"),
                                app_name=APP, plugins=ec.plugins_factory())
        session = await runner.session_service.create_session(app_name=APP, user_id="sources", state={
            "claim_text": claim_text, "pages": pages, "claim_context": f"Context: {said}" if said else ""})
        msg = types.Content(role="user", parts=[types.Part(text="Summarize the pages.")])
        async for _ in runner.run_async(user_id="sources", session_id=session.id, new_message=msg):
            pass
        done = await runner.session_service.get_session(app_name=APP, user_id="sources", session_id=session.id)
        raw = done.state.get("summary")
        out = SourcesSummary.model_validate(raw) if raw else None
    except Exception as e:
        reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
        ec.log("sources", "summary_failed", "skipped", reason[:200])
        return Digest()
    if out is None:
        return Digest()
    summary, counter_summary = acceptable_summary(out.summary), acceptable_summary(out.counter_summary)
    for raw_text, kept in ((out.summary, summary), (out.counter_summary, counter_summary)):
        if raw_text.strip() and not kept:
            ec.log("sources", "summary_judging_words", "skipped", raw_text[:200])
    return Digest(summary if sources else "", out.match if sources else "", counter_summary if counter else "")


# --- Triage and searches ----------------------------------------------------------------------------

def fallback_route(statement: str) -> str:
    """If the classifier fails: figures go to 'data', anything else to 'contested', so the second search still runs."""
    return "data" if _HAS_FIGURE.search(statement or "") else "contested"


def _safe_classifier(inner: Any) -> Any:
    """Wraps the triage classifier so a failure (refusal, bad JSON, API error, budget) becomes the fallback route
    instead of failing the workflow. A budget error is not swallowed: the lookup must stop."""
    from google.adk.labs.classifiers import BaseClassifier, ChoiceAnswer, ClassifierResponse

    class SafeClassifier(BaseClassifier):
        model: str = "triage"
        inner_classifier: Any = None

        async def classify(self, *, input, questions):
            try:
                return await self.inner_classifier.classify(input=input, questions=questions)
            except Exception as e:
                if is_budget_error(e):
                    raise
                get_context().log("sources", "triage_failed", "flagged", f"{type(e).__name__}: {e}"[:200])
                label = fallback_route((input or {}).get("statement", "") if isinstance(input, dict) else str(input))
                return ClassifierResponse(answers={
                    name: ChoiceAnswer(choice=label, probabilities={k: float(k == label) for k in q.criteria})
                    for name, q in questions.items()})

    return SafeClassifier(inner_classifier=inner)


class Lookup(NamedTuple):
    route: str
    related: list[Source]
    counter: list[Source]
    triage: Optional[dict[str, Any]] = None


async def run_searches(statement: str, route: str, ctx: dict[str, Any], location: Optional[str]) -> tuple[list[Source], list[Source]]:
    """The related search and, for data / contested, the second search, at the same time. Each is charged to the
    video. Raises if the related search fails; a failed second search only leaves that group empty."""
    ec = get_context()
    s, policy = ec.settings, ec.policy
    ec.budget.add(s.search_cost_usd)
    tasks = [search_sources(statement, s, policy, objective=related_objective(statement, ctx), location=location)]
    if route in COUNTER_ROUTES and s.counter_enabled:
        ec.budget.add(s.search_cost_usd)
        queries, objective = counter_request(statement, route, ctx)
        tasks.append(search_sources(statement, s, policy, objective=objective, extra_queries=queries[1:], location=location))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(results[0], BaseException):
        raise results[0]
    related: list[Source] = results[0]
    counter: list[Source] = []
    if len(results) > 1:
        if isinstance(results[1], BaseException):
            ec.log("sources", "counter_search_failed", "skipped", f"{type(results[1]).__name__}: {results[1]}"[:200])
        else:
            seen = {x.url for x in related}
            counter = [x for x in results[1] if x.url not in seen]
            for i, x in enumerate(counter):
                x.rank, x.kind = i, "counter"
    return related, counter


def build_lookup_workflow(settings: Settings, box: dict[str, Any], *, force: bool, location: Optional[str]) -> Any:
    """prepare -> triage (ClassifierNode) -> skip | lookup. The routed nodes write their result into `box`."""
    from google.adk.agents.context import Context
    from google.adk.labs.classifiers import Choice, ClassifierNode
    from google.adk.workflow import START, Workflow, node

    from .llm_agents import triage_classifier

    async def prepare(ctx: Context) -> dict[str, Any]:
        return ctx.state["triage_input"]

    async def lookup(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
        route = (ctx.state.get("triage") or {}).get("choice") or "related"
        box["route"] = route
        box["related"], box["counter"] = await run_searches(node_input["statement"], route, node_input, location)
        return node_input

    async def skip(node_input: dict[str, Any]) -> dict[str, Any]:
        if force:  # a viewer pressed Check sources: they get the related search
            box["route"] = "related"
            box["related"], box["counter"] = await run_searches(node_input["statement"], "related", node_input, location)
        else:
            box["route"] = "skip"
        return node_input

    triage = ClassifierNode(
        name="triage", classifier=_safe_classifier(triage_classifier(settings)), answer_key="triage",
        question=Choice(instructions=prompts.TRIAGE_INSTRUCTIONS, criteria=dict(prompts.TRIAGE_CRITERIA)))
    lookup_node = node(lookup, name="lookup")
    return Workflow(name="source_lookup", edges=[
        (START, node(prepare, name="prepare"), triage),
        (triage, {"skip": node(skip, name="skip"), **{r: lookup_node for r in TRIAGE_ROUTES if r != "skip"}}),
    ])


async def lookup_claim(claim: dict[str, Any], vctx: VideoContext, *, force: bool) -> Lookup:
    """Triage and search for one statement. Without triage (settings.triage_sources off) it is one related search."""
    ec = get_context()
    ctx = vctx.for_claim(claim)
    statement = claim["claim_text"]
    location = vctx.location
    if not ec.settings.triage_sources:
        related, counter = await run_searches(statement, "related", ctx, location)
        return Lookup("related", related, counter)
    box: dict[str, Any] = {}
    runner = InMemoryRunner(node=build_lookup_workflow(ec.settings, box, force=force, location=location),
                            app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="sources", state={"triage_input": ctx})
    msg = types.Content(role="user", parts=[types.Part(text="Look up sources for the statement.")])
    async for _ in runner.run_async(user_id="sources", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="sources", session_id=session.id)
    triage = done.state.get("triage")
    if "route" not in box:  # the workflow ended without a routed node running: never expected, but never silent
        raise RuntimeError("source lookup workflow ended without a route")
    return Lookup(box["route"], box.get("related", []), box.get("counter", []), triage)


async def _lookup_and_summarize(claim: dict[str, Any], vctx: VideoContext, *, force: bool) -> tuple[Lookup, Digest]:
    found = await lookup_claim(claim, vctx, force=force)
    if found.route == "skip":
        return found, Digest()
    return found, await summarize(claim["claim_text"], found.related, found.counter, vctx.for_claim(claim))


async def _save(store: Any, claim_id: str, found: Lookup, digest: Digest) -> None:
    if found.route == "skip":
        await store.save_sources_route(claim_id, "skip", found.triage)
        return
    await store.save_claim_sources(claim_id, found.related, digest.summary, digest.match, counter=found.counter,
                                   counter_summary=digest.counter_summary, route=found.route, triage=found.triage)


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
            vctx = await VideoContext(store, {**ep, "id": episode_id}).load()
            found, digest = await _lookup_and_summarize(row, vctx, force=True)
            await _save(store, claim_id, found, digest)
            result = {"claim_id": claim_id, "status": "done", "route": found.route, "sources": len(found.related),
                      "other_sources": len(found.counter), "summary": bool(digest.summary), "match": digest.match}
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
    """Looks up sources for every statement of a video that has none yet. Never raises."""
    async with lock_for(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "The video hasn't finished being analysed."}
        claims = sorted(await store.list_batch_claims(episode_id), key=lambda r: r.get("start_s") or 0)
        groups: dict[str, list[dict[str, Any]]] = {}  # same wording -> claims sharing one lookup, earliest first
        for c in claims:
            groups.setdefault(same_wording(c["claim_text"]), []).append(c)
        left = settings.max_cost_usd_per_episode - float(ep.get("cost_usd") or 0)
        each = settings.lookup_cost_estimate_usd  # the most one lookup can cost
        affordable = max(0, int(left / each + 1e-9)) if each > 0 else len(groups)
        searches = list(groups.values())[:max(0, min(settings.sources_all_max_searches, affordable))]
        todo = [c for g in searches for c in g]
        if not todo:
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "Nothing to look up." if not claims else "Over the video's budget."}

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
                    return  # summaries used up the rest of the budget: these claims go back to 'not requested'
                try:
                    found, digest = await _lookup_and_summarize(group[0], vctx, force=False)
                    if found.route == "skip":
                        skipped += 1
                    else:
                        searched += 1
                    for c in group:  # claims with the same wording share the result
                        await _save(store, c["id"], found, digest)
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
        return {"status": "done", "searched": searched, "skipped": skipped, "claims": len(todo),
                "remaining": len(claims) - len(todo), "cost_usd": round(spent, 4)}


# --- One-off: summaries for sources saved before summaries existed --------------------------------------

async def summarize_missing(*, settings: Settings, store: Any, limit: int = 200) -> dict[str, Any]:
    """Writes the sources summary and match for claims that have sources but no match yet, from their stored excerpts (no new
    search). Charged to each video's budget; a video over its cap is skipped."""
    done = skipped = 0
    cost = 0.0
    for row in await store.list_claims_missing_summary(limit):
        episode_id = row["episode_id"]
        async with lock_for(episode_id):
            ep = row.get("episodes") or {}
            ec = _context(episode_id, ep, settings, store)
            if ec.budget.spent_usd >= ec.budget.cap_usd:
                skipped += 1
                continue
            start = ec.budget.spent_usd
            token = set_context(ec)
            try:
                found = [Source(**s) for s in sorted(row["claim_sources"], key=lambda s: s.get("rank") or 0)]
                digest = await summarize(row["claim_text"], found)
                await store.save_sources_summary(row["id"], digest.summary, digest.match)
                done += bool(digest.summary or digest.match)
            finally:
                spent = round(ec.budget.spent_usd - start, 6)
                cost += spent
                await store.add_episode_cost(episode_id, spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
                token.var.reset(token)
    return {"summarised": done, "skipped_over_budget": skipped, "cost_usd": round(cost, 4)}
