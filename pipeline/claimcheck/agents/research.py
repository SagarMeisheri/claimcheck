"""Researching one answer: what pages say about the points it makes, not what matches its wording. Searches only.

A search on the answer's own words finds pages about the answer's topic or its best-known phrase (an answer on "steel cage" turns
up "steel frame"), repeats of the episode itself, and the speaker's own organisation saying the same thing. This does it in steps:

  plan    an agent turns the question and answer into the 1-2 most checkable points, each with new queries (not the answer's
          sentence) and challenge queries (other figures, periods, definitions, positions). When the issue itself is disputed it
          also names the positions people hold. An answer with nothing checkable gets no points: it is skipped (research_answer
          returns None), unless a viewer pressed the button, when its own wording is searched.
  search  at most settings.research_max_searches queries (default 3): the first query of each point, then the first challenge
          query, then the positions. They go to Parallel in ONE request (one base fee, MAX_RESULTS pages in all, which the base fee
          covers), so the pages are not split by query. The excerpts the search returns are the only page text used: no page is fetched.
  keep    every page returned is kept, in the order it came back, all treated alike. Pages that are the episode's own or the speaker's
          own organisation's carry a label (independence.py) for the reader, which changes nothing else.

The grounding classifier (agents/qa_tags.py) then reads every page's excerpt together with the Q&A and the profiles. Nothing here says
the speaker is right or wrong. If the search fails it raises ResearchUnavailable and the answer is marked failed (it can be retried).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import BudgetExceeded, get_context, is_budget_error
from ..guardrails.injection import find_injections, screen_text, wrap_untrusted
from ..policy import domain_of
from ..schemas import AnswerPoints, PlanPoint, Position, ResearchPlan, Source, VideoPlan
from ..tools import evidence
from ..tools.evidence import _said_by, search_sources
from .independence import split_sources
from .streaming import ObjectStream, StatementStreamer

log = logging.getLogger("claimcheck")
APP = "claimcheck_research"
MAX_QUERY_CHARS = 160
MAX_RESULTS = 10  # pages in the one request; Parallel's base fee covers 10, each extra result costs more
EXCERPT_CHARS = 1200  # of each result's excerpt, which is all the page text the tags get


class ResearchUnavailable(RuntimeError):
    """Every search failed: the lookup is marked failed so it can be retried."""


@dataclass
class Research:
    points: list[dict[str, Any]]
    positions: list[str]
    queries: list[str]
    related: list[Source]
    counter: list[Source]
    summary: str
    counter_summary: str
    match: str
    dropped: dict[str, int] = field(default_factory=dict)
    pages: list[dict[str, str]] = field(default_factory=list)  # every page the searches returned
    all_pages: list[dict[str, Any]] = field(default_factory=list, repr=False)  # every page with its search excerpt, for the classifier (not stored)
    searches: list[dict[str, Any]] = field(default_factory=list)  # one entry for the single request: {"query" (all queries joined), "queries" (each one), "urls" (in the order returned), "failed"}

    def stored(self) -> dict[str, Any]:
        """What is saved in claims.research and shown in the detail panel."""
        out = {"version": 3, "points": self.points, "positions": self.positions, "queries": self.queries, "dropped": self.dropped,
               "pages": self.pages, "searches": self.searches}
        return out


# --- Small checks (pure code) ---------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def clean_queries(queries: list[str], answer: str) -> list[str]:
    """Search queries tidied: short, no repeats, never the answer's own sentence, nothing that reads as an instruction."""
    out: list[str] = []
    for q in queries or []:
        q = " ".join((q or "").split())[:MAX_QUERY_CHARS]
        nq = _norm(q)
        copies_answer = len(nq) >= 40 and nq in _norm(answer)  # the answer's own words, or a cut of them
        if len(q) < 4 or find_injections(q) or copies_answer or q.lower() in (x.lower() for x in out):
            continue
        out.append(q)
    return out


def clean_plan(plan: ResearchPlan, answer: str, max_points: int) -> ResearchPlan:
    points: list[PlanPoint] = []
    for p in plan.points:
        text = " ".join((p.text or "").split())[:400]
        queries, challenge = clean_queries(p.queries, answer)[:3], clean_queries(p.challenge_queries, answer)[:2]
        if text and (queries or challenge):
            points.append(PlanPoint(text=text, kind=p.kind, queries=queries or challenge[:1], challenge_queries=challenge if queries else challenge[1:]))
        if len(points) >= max_points:
            break
    positions: list[Position] = []
    if plan.disputed:
        for pos in plan.positions[:3]:
            label, q = " ".join((pos.label or "").split())[:80], clean_queries([pos.query], answer)
            if label and q:
                positions.append(Position(label=label, query=q[0]))
    return ResearchPlan(points=points, disputed=plan.disputed and len(positions) >= 2, positions=positions if len(positions) >= 2 else [])


def own_words_plan(answer: str) -> ResearchPlan:
    """For a viewer who pressed the button on an answer with nothing checkable: search its own words, so something always comes back."""
    text = " ".join(answer.split())
    return ResearchPlan(points=[PlanPoint(text=text[:300], kind="other", queries=[" ".join(text.split()[:14])], challenge_queries=[])])


def pick_queries(plan: ResearchPlan, limit: int) -> list[str]:
    """At most `limit` queries from the plan, so no point is left without one: each point's first query, then each point's first
    challenge query (another figure, period or view), then the positions, then any query left."""
    rounds = [[p.queries[0] for p in plan.points if p.queries], [p.challenge_queries[0] for p in plan.points if p.challenge_queries],
              [pos.query for pos in plan.positions], [q for p in plan.points for q in p.queries[1:] + p.challenge_queries[1:]]]
    out: list[str] = []
    for q in (q for r in rounds for q in r):
        if q.lower() not in (x.lower() for x in out):
            out.append(q)
    return out[:max(1, limit)]


# --- Steps that call out (kept apart so tests can replace them) ------------------------------------

def _spend(usd: float) -> None:
    ec = get_context()
    if ec.budget.spent_usd + usd > ec.budget.cap_usd:
        raise BudgetExceeded(f"video cost ${ec.budget.spent_usd:.2f} would pass the cap ${ec.budget.cap_usd:.2f}")
    ec.budget.add(usd)


async def _run_agent(agent: Any, state: dict[str, Any], key: str, model: Any,
                     on_text: Optional[Callable[[str], Awaitable[None]]] = None) -> Any:
    """Runs one agent and returns its validated output. With `on_text` the reply is streamed and every piece of text is handed over as
    the model writes it (the final result is the same)."""
    ec = get_context()
    runner = InMemoryRunner(agent=agent, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="research", state=state)
    config = RunConfig(streaming_mode=StreamingMode.SSE) if on_text else RunConfig()
    async for ev in runner.run_async(user_id="research", session_id=session.id, run_config=config,
                                     new_message=types.Content(role="user", parts=[types.Part(text="Go.")])):
        if on_text and getattr(ev, "partial", False):
            piece = StatementStreamer.text_of(ev)
            if piece:
                await on_text(piece)
    done = await runner.session_service.get_session(app_name=APP, user_id="research", session_id=session.id)
    raw = done.state.get(key)
    return model.model_validate(raw) if raw else None


def context_text(ctx: dict[str, Any]) -> str:
    """What the planner may know about where the answer was said: the video, the speaker's name and role, the show. Never the
    profiles' notes on positions or criticisms: those must not steer what counts as the other side."""
    v, sp, cr = ctx.get("video") or {}, ctx.get("speaker") or {}, ctx.get("creator") or {}
    lines = []
    if v.get("title"):
        lines.append(f'Video: "{v["title"]}"' + (f" ({v['channel']})" if v.get("channel") else ""))
    who = sp.get("name") or sp.get("label")
    if who:
        lines.append(f"Answered by: {who}" + (f", {sp['role']}" if sp.get("role") else ""))
    if cr.get("podcast"):
        lines.append(f"Show: {cr['podcast']}")
    if ctx.get("discussing"):
        lines.append(f"Discussing: {ctx['discussing']}")
    return wrap_untrusted("CONTEXT", "\n".join(lines)) if lines else ""


async def _plan(ctx: dict[str, Any]) -> Optional[ResearchPlan]:
    from .llm_agents import research_planner_agent

    ec = get_context()
    state = {"question": ctx.get("question") or "(not asked directly)", "answer": ctx["statement"], "context": context_text(ctx)}
    return await _run_agent(research_planner_agent(ec.settings, name=f"research_planner_{uuid.uuid4().hex[:6]}"), state, "plan", ResearchPlan)


async def _search(queries: list[str], objective: str, location: Optional[str]) -> list[Source]:
    ec = get_context()
    _spend(ec.settings.search_cost_usd)
    s = dataclasses.replace(ec.settings, sources_per_claim=MAX_RESULTS, excerpt_chars=EXCERPT_CHARS)  # keep what Parallel returns
    return await search_sources(queries[0], s, ec.policy, objective=objective, extra_queries=queries[1:], location=location, spare=0)


def _objective(points: list[str], ctx: dict[str, Any]) -> str:
    said = _said_by({k: v for k, v in ctx.items() if k != "question"})
    base = ("Find reports, data, official documents and news coverage on these points from an answer. Include sources that give other figures, "
            f"other periods or definitions, or other positions on them. Points: {' | '.join(points)}")
    return f"{base} Context: {said}"[:2000] if said else base


# --- The research ---------------------------------------------------------------------------------

async def research_answer(ctx: dict[str, Any], location: Optional[str], force: bool = False) -> Optional[Research]:
    """Researches one answer (ctx is the lookup context: statement, question, speaker, creator, video). Returns None when the planner
    finds nothing checkable (unless `force`). Raises ResearchUnavailable when the search failed; BudgetExceeded is not swallowed."""
    ec = get_context()
    s, policy = ec.settings, ec.policy
    answer = ctx["statement"]
    raw_plan = await _plan(ctx)
    plan = clean_plan(raw_plan, answer, s.research_max_points) if raw_plan else None
    if not plan or not plan.points:
        if not force:
            return None
        plan = own_words_plan(answer)
    points = plan.points
    queries = pick_queries(plan, s.research_max_searches)

    objective = _objective([p.text for p in points], ctx)
    if plan.positions:
        objective += " Positions people hold: " + "; ".join(p.label for p in plan.positions) + "."
    try:
        found = await _search(queries, objective[:2000], location)  # one request for all the queries
    except BudgetExceeded:
        raise
    except Exception as e:
        log.warning("research search failed: %s: %s", type(e).__name__, e)
        raise ResearchUnavailable("the search failed") from e
    searches = [{"query": " · ".join(queries), "queries": queries, "urls": [x.url for x in found], "failed": False}]  # the pages come back as one list
    return _assemble(ctx, policy, [{"text": p.text, "kind": p.kind} for p in points], [p.label for p in plan.positions], queries, found, searches)


def _page_rows(sources: list[Source]) -> list[dict[str, Any]]:
    return [{"url": x.url, "site": domain_of(x.url), "title": x.title or domain_of(x.url), "independence": x.independence} for x in sources]


def _assemble(ctx: dict[str, Any], policy: dict[str, Any], points: list[dict[str, Any]], positions: list[str], queries: list[str],
              found: list[Source], searches: list[dict[str, Any]]) -> Research:
    """The Research for one answer from the pages its searches returned. Nothing is removed; each source gets a label."""
    sources = split_sources(found, ctx, policy)[0]
    related = [x.model_copy(update={"kind": "related", "rank": i}) for i, x in enumerate(sources)]
    pages = _page_rows(sources)
    all_pages = [{**pg, "date": x.publish_date, "text": x.excerpt} for pg, x in zip(pages, sources)]
    return Research(points=[{"text": p["text"], "kind": p["kind"], "status": "sources_found" if sources else "no_source"} for p in points],
                    positions=positions, queries=queries, related=related, counter=[], summary="", counter_summary="",
                    match="medium" if sources else "low", pages=pages, all_pages=all_pages, searches=searches)


# --- The whole video at once ------------------------------------------------------------------------
# One planner call reads every answer that needs research and plans the search requests together: answers about the same subject
# share ONE request, so a video with 25 researched answers needs far fewer than 25 searches. Each answer then gets the pages of
# the requests that serve it, and the grounding classifier reads them exactly as before.

MAX_SHARED = 4             # answers one request may serve
MAX_REQUEST_QUERIES = 5    # queries in one request
RESULTS_PER_EXTRA_ANSWER = 4
MAX_SHARED_RESULTS = 20    # pages in one request; a request over MAX_RESULTS is charged once per MAX_RESULTS
MAX_PAGES_PER_ANSWER = 30  # what the grounding classifier is shown (qa_tags.MAX_PAGES_SHOWN)

Ready = Callable[[Any, "Research | None | BaseException"], Awaitable[None]]


@dataclass
class CleanSearch:
    """One request of a video's plan, after the code's checks."""

    topic: str
    answers: list[int]   # numbers in the planned chunk
    queries: list[str]
    positions: list[str]


@dataclass
class CleanVideoPlan:
    points: dict[int, list[dict[str, Any]]]  # answer number -> its points (empty = nothing checkable); only answers the planner wrote
    searches: list[CleanSearch]
    fallback: list[int]                      # answers the plan did not cover: they are planned and searched on their own


def request_results(n_answers: int) -> int:
    """Pages asked for in a request serving n answers: a shared request gets a few more than a single one."""
    return min(MAX_RESULTS + RESULTS_PER_EXTRA_ANSWER * (max(1, n_answers) - 1), MAX_SHARED_RESULTS)


def clean_points(points: list[Any], max_points: int) -> list[dict[str, Any]]:
    """An answer's points in plain words: whitespace tidied, at most 400 characters each, at most max_points."""
    out: list[dict[str, Any]] = []
    for p in points:
        text = " ".join((p.text or "").split())[:400]
        if text:
            out.append({"text": text, "kind": p.kind})
        if len(out) >= max_points:
            break
    return out


def partial_research(stage: str, points: list[dict[str, Any]], queries: Optional[list[str]] = None, searches: Optional[list[dict[str, Any]]] = None,
                     pages: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """What an answer's research has so far, in the shape of Research.stored() plus a `stage` (planning, searching, reading, grounding),
    saved while the lookup runs so the page can show it. Its points are `pending` until the pages are in."""
    return {"version": 3, "stage": stage, "points": [{"text": p["text"], "kind": p["kind"], "status": "pending"} for p in points], "positions": [],
            "queries": queries or [], "searches": searches or [], "pages": pages or []}


def clean_video_plan(plan: VideoPlan, answers: dict[int, str], max_points: int, max_queries: int) -> CleanVideoPlan:
    """The planner's output kept only where it holds up: answer numbers that exist, points in plain words, queries tidied like a single
    answer's (clean_plan / pick_queries), at most MAX_SHARED answers to a request and MAX_REQUEST_QUERIES queries. An answer the plan
    names with no points is left alone; one it forgot, or whose points no request serves, is planned on its own (fallback)."""
    points: dict[int, list[dict[str, Any]]] = {}
    for ap in plan.answers:
        if ap.answer not in answers or ap.answer in points:
            continue
        points[ap.answer] = clean_points(ap.points, max_points)
    searches: list[CleanSearch] = []
    by_queries: dict[tuple[str, ...], CleanSearch] = {}
    for sp in plan.searches:
        served = list(dict.fromkeys(n for n in sp.answers if points.get(n)))[:MAX_SHARED]
        if not served:
            continue
        topic = " ".join((sp.topic or "").split())[:200]
        rp = clean_plan(ResearchPlan(points=[PlanPoint(text=topic or (sp.queries[0] if sp.queries else ""), kind="other", queries=sp.queries,
                                                       challenge_queries=sp.challenge_queries)], disputed=sp.disputed, positions=sp.positions),
                        " ".join(answers[n] for n in served), 1)
        if not rp.points:
            continue
        queries = pick_queries(rp, min(MAX_REQUEST_QUERIES, max(1, max_queries + len(served) - 1)))
        key = tuple(q.lower() for q in queries)
        if key in by_queries:  # the same request twice: one request serving both sets of answers
            twin = by_queries[key]
            twin.answers = list(dict.fromkeys(twin.answers + served))[:MAX_SHARED]
            continue
        by_queries[key] = CleanSearch(topic, served, queries, [p.label for p in rp.positions])
        searches.append(by_queries[key])
    covered = {n for s in searches for n in s.answers}
    fallback = [n for n in answers if n not in points or (points[n] and n not in covered)]
    return CleanVideoPlan(points, searches, fallback)


def answers_text(entries: list[dict[str, Any]]) -> str:
    """The numbered answers as the planner reads them, as untrusted data."""
    blocks = []
    for e in entries:
        ctx = e["ctx"]
        sp = ctx.get("speaker") or {}
        who = sp.get("name") or sp.get("label") or "the speaker"
        head = f"[{e['n']}] Answered by {who}" + (f", {sp['role']}" if sp.get("role") else "")
        if ctx.get("discussing"):
            head += f". Discussing: {screen_text(str(ctx['discussing']))[0][:200]}"
        blocks.append(f"{head}\n    Question: {screen_text(str(ctx.get('question') or '(not asked directly)'))[0][:300]}\n"
                      f"    Answer: {screen_text(str(ctx['statement']))[0][:900]}")
    return wrap_untrusted("ANSWERS", "\n\n".join(blocks))


async def _plan_video(text: str, context: str, on_answer: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None) -> Optional[VideoPlan]:
    """The planner call for one chunk of answers. A seam for tests. With `on_answer` the reply is streamed and each answer's points are
    handed over (as the raw object) the moment the model has written them, long before the searches are planned."""
    from .llm_agents import video_planner_agent

    ec = get_context()
    stream = ObjectStream()  # the plan's first array is `answers`

    async def on_text(piece: str) -> None:
        for obj in stream.feed(piece):
            await on_answer(obj)  # type: ignore[misc]

    return await _run_agent(video_planner_agent(ec.settings, name=f"video_planner_{uuid.uuid4().hex[:6]}"),
                            {"answers": text, "context": context or "(no context)"}, "plan", VideoPlan, on_text=on_text if on_answer else None)


async def _search_shared(queries: list[str], objective: str, location: Optional[str], n_answers: int, fresh: bool = False) -> list[Source]:
    """One request for the queries of a search that serves n answers. A search made lately for the same queries is reused and not
    charged (`fresh`, a recheck, always searches). Raises on API errors; BudgetExceeded when the request would pass the cap."""
    ec = get_context()
    s = ec.settings
    n = request_results(n_answers)
    key = evidence.cache_key(queries, location, s.sources_search_mode, n)
    if s.search_cache_ttl_s > 0 and not fresh:
        hit = evidence.cache_get(key)
        if hit is not None:
            return hit
    _spend(s.search_cost_usd * math.ceil(n / MAX_RESULTS))
    st = dataclasses.replace(s, sources_per_claim=n, excerpt_chars=EXCERPT_CHARS)
    found = await search_sources(queries[0], st, ec.policy, objective=objective, extra_queries=queries[1:], location=location, spare=0)
    if s.search_cache_ttl_s > 0:
        evidence.cache_put(key, found, s.search_cache_ttl_s)
    return found


def _objective_shared(search: CleanSearch, points: list[str], show: str) -> str:
    base = ("Find reports, data, official documents and news coverage on these points from answers in a video. Include sources that give "
            f"other figures, other periods or definitions, or other positions on them. Points: {' | '.join(points)}")
    if search.topic:
        base += f" Subject: {search.topic}."
    if show:
        base += f" Said on {show}."
    if search.positions:
        base += " Positions people hold: " + "; ".join(search.positions) + "."
    return base[:2000]


async def research_video(items: list[tuple[Any, dict[str, Any]]], location: Optional[str], on_ready: Ready, *, force: bool = False,
                         fresh: bool = False, on_progress: Optional[Callable[[Any, dict[str, Any]], Awaitable[None]]] = None,
                         on_phase: Optional[Callable[[str], Awaitable[None]]] = None) -> None:
    """Researches many answers together. `items` are (key, lookup context); `on_ready(key, result)` is awaited as soon as an answer's
    searches are done, with its Research, None (the plan found nothing checkable; with `force` it is searched on its own words), or the
    exception that stopped it (ResearchUnavailable when every search serving it failed; a budget error as it is). Never raises.

    `on_progress(key, partial)` is awaited as an answer's research takes shape (partial_research: its points as the planner writes
    them, then its queries, then its pages as each search comes back); `on_phase(label)` with what the whole video is doing. Both are
    best-effort: a failure in either is logged and the research goes on."""
    ec = get_context()
    s, policy = ec.settings, ec.policy
    gate = asyncio.Semaphore(max(1, s.sources_concurrency))

    async def emit(key: Any, data: dict[str, Any]) -> None:
        if on_progress is not None:
            try:
                await on_progress(key, data)
            except Exception as e:
                log.warning("could not report progress: %s: %s", type(e).__name__, e)

    async def phase(label: str) -> None:
        if on_phase is not None:
            try:
                await on_phase(label)
            except Exception as e:
                log.warning("could not report the phase: %s: %s", type(e).__name__, e)

    async def alone(key: Any, ctx: dict[str, Any]) -> None:
        try:
            async with gate:
                result: Any = await research_answer(ctx, location, force=force)
        except Exception as e:
            result = e
        await on_ready(key, result)

    async def chunk(part: list[tuple[Any, dict[str, Any]]]) -> None:
        entries = [{"n": i, "key": k, "ctx": c} for i, (k, c) in enumerate(part, 1)]
        by_n = {e["n"]: e for e in entries}
        v = (part[0][1].get("video") or {})
        context = context_text({"video": v, "creator": part[0][1].get("creator") or {}})
        streamed: set[int] = set()

        async def points_written(obj: dict[str, Any]) -> None:
            """The planner has just written one answer's points: show them now, before the searches are even planned."""
            try:
                ap = AnswerPoints.model_validate(obj)
            except Exception:
                return
            pts = clean_points(ap.points, s.research_max_points)
            if ap.answer in by_n and ap.answer not in streamed and pts:
                streamed.add(ap.answer)
                await emit(by_n[ap.answer]["key"], partial_research("planning", pts))

        await phase(f"Planning the checks for {len(part)} answers")
        try:
            plan = await (_plan_video(answers_text(entries), context, on_answer=points_written) if on_progress is not None
                          else _plan_video(answers_text(entries), context))
        except Exception as e:
            if is_budget_error(e):
                await asyncio.gather(*(on_ready(x["key"], e) for x in entries))
                return
            log.warning("video plan failed: %s: %s", type(e).__name__, e)
            plan = None
        if plan is None:  # no plan: every answer in the chunk is planned on its own
            await asyncio.gather(*(alone(x["key"], x["ctx"]) for x in entries))
            return
        clean = clean_video_plan(plan, {e["n"]: e["ctx"]["statement"] for e in entries}, s.research_max_points, s.research_max_searches)
        show = ((part[0][1].get("creator") or {}).get("podcast")) or ""
        tasks: list[Any] = [alone(by_n[n]["key"], by_n[n]["ctx"]) for n in clean.fallback]
        for n, pts in clean.points.items():
            if not pts and n not in clean.fallback:
                tasks.append(on_ready(by_n[n]["key"], None) if not force else alone(by_n[n]["key"], by_n[n]["ctx"]))
        serving: dict[int, list[int]] = {}  # answer -> the requests that serve it
        got: dict[int, dict[int, tuple[Optional[list[Source]], Optional[BaseException]]]] = {}
        for si, sp in enumerate(clean.searches):
            for n in sp.answers:
                serving.setdefault(n, []).append(si)
                got.setdefault(n, {})

        def merged(n: int) -> tuple[list[Source], list[str], list[str], list[dict[str, Any]], set[int]]:
            """What answer n has from the requests that are back: (pages, queries, positions, a search entry per request, the ones that worked)."""
            outcomes = got[n]
            ok = {si for si, (f, exc) in outcomes.items() if exc is None and f is not None}
            seen: set[str] = set()
            found: list[Source] = []
            for si in sorted(ok):
                for x in outcomes[si][0] or []:
                    if x.url not in seen and len(found) < MAX_PAGES_PER_ANSWER:
                        seen.add(x.url)
                        found.append(x)
            queries = list(dict.fromkeys(q for si in serving[n] for q in clean.searches[si].queries))
            positions = list(dict.fromkeys(p for si in sorted(ok) for p in clean.searches[si].positions))
            searches = []
            for si in serving[n]:
                entry = {"query": " · ".join(clean.searches[si].queries), "queries": clean.searches[si].queries,
                         "urls": [x.url for x in outcomes[si][0] or []] if si in ok else [], "failed": si in outcomes and si not in ok}
                if si not in outcomes:
                    entry["pending"] = True  # still being searched
                searches.append(entry)
            return found, queries, positions, searches, ok

        async def finish(n: int) -> None:
            e, outcomes = by_n[n], got[n]
            found, queries, positions, searches, ok = merged(n)
            if not ok:
                exc = next(x for _, x in outcomes.values() if x is not None)
                await on_ready(e["key"], exc if is_budget_error(exc) else ResearchUnavailable("the search failed"))
                return
            for en in searches:
                en.pop("pending", None)
            await on_ready(e["key"], _assemble(e["ctx"], policy, clean.points[n], positions, queries, found, searches))

        async def run_search(si: int) -> None:
            sp = clean.searches[si]
            try:
                async with gate:
                    pts = [p["text"] for n in sp.answers for p in clean.points[n]]
                    found = await _search_shared(sp.queries, _objective_shared(sp, pts, show), location, len(sp.answers), fresh)
                outcome: tuple[Optional[list[Source]], Optional[BaseException]] = (found, None)
            except Exception as ex:
                if not is_budget_error(ex):
                    log.warning("research search failed: %s: %s", type(ex).__name__, ex)
                outcome = (None, ex)
            for n in sp.answers:
                got[n][si] = outcome
                if len(got[n]) == len(serving[n]):  # the last request serving this answer is back
                    await finish(n)
                else:  # some are still out: show the pages that are in
                    f, queries, _, searches, _ = merged(n)
                    await emit(by_n[n]["key"], partial_research("reading", clean.points[n], queries, searches, _page_rows(split_sources(f, by_n[n]["ctx"], policy)[0])))

        if clean.searches:
            await phase(f"Searching the web: {len(clean.searches)} requests for {len(serving)} answers")
        for n, sis in serving.items():  # the queries each answer will be searched with, before any comes back
            _, queries, _, searches, _ = merged(n)
            await emit(by_n[n]["key"], partial_research("searching", clean.points[n], queries, searches))
        tasks += [run_search(si) for si in range(len(clean.searches))]
        await asyncio.gather(*tasks)

    size = max(1, s.plan_chunk)
    parts = [items[i:i + size] for i in range(0, len(items), size)]
    results = await asyncio.gather(*(chunk(p) for p in parts), return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            log.error("video research crashed: %s: %s", type(r).__name__, r)
