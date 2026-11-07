"""Researching one answer: what pages say about the points it makes, not what matches its wording. Searches only.

A search on the answer's own words finds pages about the answer's topic or its best-known phrase (an answer on "steel cage" turns
up "steel frame"), repeats of the episode itself, and the speaker's own organisation saying the same thing. This does it in steps:

  plan    an agent turns the question and answer into the 1-2 most checkable points, each with new queries (not the answer's
          sentence) and challenge queries (other figures, periods, definitions, positions). When the issue itself is disputed it
          also names the positions people hold. An answer with nothing checkable gets no points: it is skipped (research_answer
          returns None), unless a viewer pressed the button, when its own wording is searched.
  search  at most settings.research_max_searches queries (default 3), each its own web search, all at the same time: the first query
          of each point, then the first challenge query, then the positions. The excerpts the searches return are the only page text
          used: no page is fetched.
  keep    every page returned is kept, in the order it came back, all treated alike. Pages that are the episode's own or the speaker's
          own organisation's carry a label (independence.py) for the reader, which changes nothing else.

The grounding classifier (agents/qa_tags.py) then reads every page's excerpt together with the Q&A and the profiles. Nothing here says
the speaker is right or wrong. If every search fails it raises ResearchUnavailable and the answer is marked failed (it can be retried).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import BudgetExceeded, get_context
from ..guardrails.injection import find_injections, wrap_untrusted
from ..policy import domain_of
from ..schemas import PlanPoint, Position, ResearchPlan, Source
from ..tools.evidence import _said_by, search_sources
from .independence import split_sources

log = logging.getLogger("claimcheck")
APP = "claimcheck_research"
MAX_QUERY_CHARS = 160
MAX_RESULTS = 20  # results kept per search
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
    searches: list[dict[str, Any]] = field(default_factory=list)  # per query: {"query", "urls" (in the order that search returned them), "failed"}

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


def interleave(groups: list[list[Source]]) -> list[Source]:
    """Every page of every search, one URL once, taking each search's results in turn so no query's results come last."""
    out: list[Source] = []
    seen: set[str] = set()
    for rank in range(max((len(g) for g in groups), default=0)):
        for g in groups:
            if rank < len(g) and g[rank].url not in seen:
                seen.add(g[rank].url)
                out.append(g[rank])
    return out


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


async def _run_agent(agent: Any, state: dict[str, Any], key: str, model: Any) -> Any:
    ec = get_context()
    runner = InMemoryRunner(agent=agent, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="research", state=state)
    async for _ in runner.run_async(user_id="research", session_id=session.id,
                                    new_message=types.Content(role="user", parts=[types.Part(text="Go.")])):
        pass
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
    return await search_sources(queries[0], s, ec.policy, objective=objective, extra_queries=queries[1:], location=location)


def _objective(points: list[str], ctx: dict[str, Any]) -> str:
    said = _said_by({k: v for k, v in ctx.items() if k != "question"})
    base = ("Find reports, data, official documents and news coverage on these points from an answer. Include sources that give other figures, "
            f"other periods or definitions, or other positions on them. Points: {' | '.join(points)}")
    return f"{base} Context: {said}"[:2000] if said else base


# --- The research ---------------------------------------------------------------------------------

async def research_answer(ctx: dict[str, Any], location: Optional[str], force: bool = False) -> Optional[Research]:
    """Researches one answer (ctx is the lookup context: statement, question, speaker, creator, video). Returns None when the planner
    finds nothing checkable (unless `force`). Raises ResearchUnavailable when every search failed; BudgetExceeded is not swallowed."""
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
    results = await asyncio.gather(*(_search([q], objective[:2000], location) for q in queries), return_exceptions=True)  # one search per query
    for r in results:
        if isinstance(r, BudgetExceeded):
            raise r
    for r in results:
        if isinstance(r, Exception):
            log.warning("research search failed: %s: %s", type(r).__name__, r)
    lists = [r for r in results if not isinstance(r, Exception)]
    if not lists:
        raise ResearchUnavailable("every search failed")
    sources = interleave([split_sources(lst, ctx, policy)[0] for lst in lists])  # nothing is removed; each source gets a label
    searches = [{"query": q, "urls": [] if isinstance(r, Exception) else [x.url for x in r], "failed": isinstance(r, Exception)}
                for q, r in zip(queries, results)]  # what each search returned, in its own order

    related = [x.model_copy(update={"kind": "related", "rank": i}) for i, x in enumerate(sources)]
    pages = [{"url": x.url, "site": domain_of(x.url), "title": x.title or domain_of(x.url), "independence": x.independence} for x in sources]
    all_pages = [{**pg, "date": x.publish_date, "text": x.excerpt} for pg, x in zip(pages, sources)]
    return Research(points=[{"text": p.text, "kind": p.kind, "status": "sources_found" if sources else "no_source"} for p in points],
                    positions=[p.label for p in plan.positions], queries=queries, related=related, counter=[], summary="", counter_summary="",
                    match="medium" if sources else "low", pages=pages, all_pages=all_pages, searches=searches)
