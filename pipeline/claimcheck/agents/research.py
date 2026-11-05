"""Researching one answer: what independent pages say about the points it makes, not what matches its wording.

A search on the answer's own words finds pages about the answer's topic or its best-known phrase (an answer on "steel cage" turns
up "steel frame"), repeats of the episode itself, and the speaker's own organisation saying the same thing. This does it in steps:

  plan      an agent turns the question and answer into the 1-2 most checkable points, each with new queries (not the answer's
            sentence) and challenge queries (other figures, periods, definitions, positions). When the issue itself is disputed
            it also names the positions people hold, to find a source for each.
  search    one web search per point (all its queries at once), and one for the positions
  filter    the episode's own pages are dropped; pages from the speaker's own organisation are labelled (independence.py)
  read      the best pages are fetched (passages focused on the points, not the 300-character search excerpt) and an agent
            writes findings: how each page relates to each point (same / different / different scope / other position), the
            figure or claim it gives, and a quote
  verify    in code: the quote must be in the page text, the figures in the finding must be in the quote, no judging words
  retry     a point nothing independent answered gets one retry with queries rewritten from a different angle

Nothing here says the speaker is right or wrong: the findings describe how sources relate to each point, and the other positions
found are shown with where they come from. Anything it can't do raises ResearchUnavailable, and the lookup falls back to the plain search.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import BudgetExceeded, get_context
from ..guardrails.injection import find_injections, wrap_untrusted
from ..policy import domain_of
from ..schemas import PageFinding, PageReading, PlanPoint, Position, QueryRewrite, ResearchPlan, Source
from ..tools.evidence import _said_by, extract_pages, search_sources
from .independence import EPISODE, INDEPENDENT, OWN, split_sources
from .sources import _JUDGING, MAX_SUMMARY_CHARS

log = logging.getLogger("claimcheck")
APP = "claimcheck_research"
MAX_QUERY_CHARS = 160
PAGE_CHARS = 3500
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")
PRIORITY = {"same": 0, "different": 1, "different_scope": 2, "other_position": 3}
ANSWERING = ("same", "different", "different_scope")  # relations that answer a point (an opposing reading alone doesn't)


class ResearchUnavailable(RuntimeError):
    """The research couldn't run (no usable plan, searches failed): the caller uses the plain search instead."""


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
    pages: list[dict[str, str]] = field(default_factory=list)  # the pages that were read
    opinion: Optional[dict[str, Any]] = None  # the opinion assessment (agents/opinion.py), when the answer got one

    def stored(self) -> dict[str, Any]:
        """What is saved in claims.research and shown in the detail panel."""
        out = {"version": 1, "points": self.points, "positions": self.positions, "queries": self.queries, "dropped": self.dropped,
               "pages": self.pages}
        if self.opinion:
            out["opinion"] = self.opinion
        return out


# --- Small checks (pure code) ---------------------------------------------------------------------

def numbers_in(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in _NUMBER.findall(text or "")}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[“”\"'‘’]", "", (text or "").lower())).strip()


def quote_in_page(quote: str, page_text: str) -> bool:
    """Whether a quote really is in the page text (ignoring case, spacing and quotation marks). A quote cut with '...' must
    have every part of at least 15 characters in the page."""
    parts = [p for p in re.split(r"\.\.\.|…", quote or "") if len(_norm(p)) >= 15]
    page = _norm(page_text)
    return bool(parts) and all(_norm(p) in page for p in parts)


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
            if label and q and not _JUDGING.search(label):
                positions.append(Position(label=label, query=q[0]))
    return ResearchPlan(points=points, disputed=plan.disputed and len(positions) >= 2, positions=positions if len(positions) >= 2 else [])


def verify_findings(findings: list[PageFinding], n_points: int, pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The findings worth keeping, each with the page it came from, and how many were dropped and why."""
    kept: list[dict[str, Any]] = []
    dropped = {"bad_reference": 0, "unverified_quote": 0, "figure_not_in_quote": 0, "judging_words": 0}
    seen: set[tuple[Any, ...]] = set()
    for f in findings:
        if not (1 <= f.point <= n_points and 1 <= f.page <= len(pages)):
            dropped["bad_reference"] += 1
            continue
        page = pages[f.page - 1]
        finding, quote = " ".join(f.finding.split())[:400], " ".join(f.quote.split())[:400]
        position = " ".join((f.position or "").split())[:80] if f.relation in ("other_position", "different") else ""
        if not finding or not quote_in_page(quote, page["text"]):
            dropped["unverified_quote"] += 1
        elif _JUDGING.search(finding) or _JUDGING.search(position):
            dropped["judging_words"] += 1
        elif not numbers_in(finding) <= numbers_in(quote):
            dropped["figure_not_in_quote"] += 1
        elif (key := (f.point, f.page, f.relation, _norm(quote))) in seen:
            continue
        else:
            seen.add(key)
            kept.append({"point": f.point, "url": page["url"], "site": page["site"], "title": page["title"],
                         "independence": page["independence"], "relation": f.relation, "finding": finding, "quote": quote,
                         "position": position})
    return kept, dropped


def point_status(findings: list[dict[str, Any]]) -> str:
    """How the independent pages relate to a point, in one word. Own-organisation pages never count as independent."""
    rel = {f["relation"] for f in findings if f["independence"] == INDEPENDENT}
    if "same" in rel and rel & {"different", "different_scope", "other_position"}:
        return "mixed"
    for r in ("same", "different", "different_scope", "other_position"):
        if r in rel:
            return r
    return "own_organisation_only" if findings else "no_independent_source"


def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _join(lines: list[str], limit: int) -> str:
    """Whole findings that fit in `limit`; the first is cut only if it alone is too long."""
    out = ""
    for line in lines:
        joined = f"{out} {line}".strip()
        if len(joined) <= limit:
            out = joined
        elif not out:
            return _trim(line, limit)
        else:
            break
    return out


def _best(findings: list[dict[str, Any]], independent: bool) -> Optional[dict[str, Any]]:
    pool = [f for f in findings if (f["independence"] == INDEPENDENT) == independent]
    return min(pool, key=lambda f: PRIORITY[f["relation"]], default=None)


def assemble(points: list[dict[str, Any]], pages: list[dict[str, Any]], fallback: list[Source]) -> tuple[list[Source], list[Source], str, str, str]:
    """(related, counter, summary, counter_summary, match) in the shapes the page already shows. Only findings that passed
    verification are used; the summaries are their findings, not new model text."""
    findings = [f for p in points for f in p["findings"]]
    by_url: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_url.setdefault(f["url"], []).append(f)
    src_by_url = {p["url"]: p["source"] for p in pages}
    related: list[Source] = []
    counter: list[Source] = []
    for url, fs in sorted(by_url.items(), key=lambda kv: min(PRIORITY[f["relation"]] for f in kv[1])):
        best = min(fs, key=lambda f: PRIORITY[f["relation"]])
        same = best["relation"] == "same"
        # The excerpt is the verified quote, so the card shows the passage that matters, not the page's opening.
        src = src_by_url[url].model_copy(update={"excerpt": best["quote"], "kind": "related" if same else "counter"})
        (related if same else counter).append(src)
    for i, s in enumerate(related):
        s.rank = i
    for i, s in enumerate(counter):
        s.rank = i
    used: set[int] = set()
    lines: list[str] = []
    for p in points[:2]:
        f = _best(p["findings"], True) or _best(p["findings"], False)
        if f:
            used.add(id(f))
            lines.append(f"{f['finding']} ({f['site']})" if f["independence"] == INDEPENDENT else f"From the speaker's own organisation: {f['finding']} ({f['site']})")
    others = [f for p in points for f in p["findings"] if f["independence"] == INDEPENDENT and f["relation"] != "same" and id(f) not in used]
    others.sort(key=lambda f: PRIORITY[f["relation"]])
    counter_lines = [f"{f['finding']} ({f['site']})" for f in others[:2]]
    summary, counter_summary = _join(lines, MAX_SUMMARY_CHARS), _join(counter_lines, MAX_SUMMARY_CHARS)
    statuses = [p["status"] for p in points]
    if statuses and statuses[0] in ("same", "different", "different_scope", "mixed"):
        match = "high"
    elif any(s in ("same", "different", "different_scope", "mixed", "other_position") for s in statuses):
        match = "medium"
    else:
        match = "low"
    if not related and not counter:  # nothing could be read: show the best pages the search found, unread
        related = [s.model_copy(update={"kind": "related", "rank": i}) for i, s in enumerate(fallback[:3])]
    return related, counter, summary, counter_summary, match


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


async def _read(points: list[PlanPoint], pages: list[dict[str, Any]]) -> list[PageFinding]:
    from .llm_agents import page_reader_agent

    ec = get_context()
    state = {"points": "\n".join(f"{i}. {p.text}" for i, p in enumerate(points, 1)),
             "pages": [{"n": i, "title": p["title"], "site": p["site"], "text": p["text"], "date": p.get("date"),
                        "origin": "the speaker's own organisation" if p["independence"] == OWN else "an independent site"}
                       for i, p in enumerate(pages, 1)]}
    out = await _run_agent(page_reader_agent(ec.settings, name=f"page_reader_{uuid.uuid4().hex[:6]}"), state, "reading", PageReading)
    return out.findings if out else []


async def _rewrite(point: PlanPoint, tried: list[str], titles: list[str]) -> list[str]:
    from .llm_agents import query_rewriter_agent

    ec = get_context()
    state = {"point": point.text, "tried": "; ".join(tried)[:600], "titles": wrap_untrusted("TITLES", "\n".join(titles[:8]))}
    out = await _run_agent(query_rewriter_agent(ec.settings, name=f"query_rewriter_{uuid.uuid4().hex[:6]}"), state, "rewrite", QueryRewrite)
    return out.queries if out else []


async def _search(queries: list[str], objective: str, location: Optional[str]) -> list[Source]:
    ec = get_context()
    _spend(ec.settings.search_cost_usd)
    s = dataclasses.replace(ec.settings, sources_per_claim=8)
    return await search_sources(queries[0], s, ec.policy, objective=objective, extra_queries=queries[1:], location=location)


def _objective(point_text: str, ctx: dict[str, Any]) -> str:
    said = _said_by({k: v for k, v in ctx.items() if k != "question"})
    base = ("Find independent primary sources and reporting on this point from an answer. Include sources that give other figures, "
            f"other periods or definitions, or other positions on it. Point: {point_text}")
    return f"{base} Context: {said}"[:2000] if said else base


def select_pages(groups: list[list[Source]], limit: int, read: set[str]) -> list[Source]:
    """The pages worth reading, taken from each search in turn so every point (and the positions) is represented: independent
    pages only, official sources a little ahead, at most two per site. One page from the speaker's own organisation is added
    only when there are fewer than two independent ones, so there is something to show."""
    pools = [sorted((s for s in g if s.independence == INDEPENDENT and s.url not in read),
                    key=lambda s: s.rank - (2 if s.tier == 1 else 0)) for g in groups]
    chosen: list[Source] = []
    taken: set[str] = set()
    per_site: dict[str, int] = {}
    while len(chosen) < limit and any(pools):
        for pool in pools:
            while pool:
                s = pool.pop(0)
                site = domain_of(s.url)
                if s.url in taken or per_site.get(site, 0) >= 2:
                    continue
                chosen.append(s)
                taken.add(s.url)
                per_site[site] = per_site.get(site, 0) + 1
                break
            if len(chosen) >= limit:
                break
    own = [s for g in groups for s in g if s.independence == OWN and s.url not in read]
    if len(chosen) < 2 and own:
        chosen.append(own[0])
    return chosen


async def _fetch(chosen: list[Source], points: list[PlanPoint], positions: list[Position]) -> list[dict[str, Any]]:
    """The pages as the reader sees them. A page that can't be fetched falls back to its search excerpt."""
    ec = get_context()
    objective = "; ".join(p.text for p in points) + ("; positions: " + "; ".join(p.label for p in positions) if positions else "")
    texts: dict[str, str] = {}
    try:
        _spend(ec.settings.extract_cost_usd)
        texts = await extract_pages([s.url for s in chosen], objective, ec.settings, max_chars=PAGE_CHARS)
    except BudgetExceeded:
        raise
    except Exception as e:
        log.warning("reading pages failed (%s: %s); using search excerpts", type(e).__name__, e)
    pages = []
    for s in chosen:
        text = texts.get(s.url) or s.excerpt
        if text:
            pages.append({"url": s.url, "site": domain_of(s.url), "title": s.title or domain_of(s.url), "text": text,
                          "date": s.publish_date, "independence": s.independence or INDEPENDENT, "source": s})
    return pages


# --- The research ---------------------------------------------------------------------------------

async def research_answer(ctx: dict[str, Any], location: Optional[str]) -> Research:
    """Researches one answer (ctx is the lookup context: statement, question, speaker, creator, video). Raises
    ResearchUnavailable when it can't; BudgetExceeded is not swallowed."""
    ec = get_context()
    s, policy = ec.settings, ec.policy
    answer = ctx["statement"]
    raw_plan = await _plan(ctx)
    plan = clean_plan(raw_plan, answer, s.research_max_points) if raw_plan else None
    if not plan or not plan.points:
        raise ResearchUnavailable("no usable plan")
    points = plan.points
    queries = [q for p in points for q in p.queries + p.challenge_queries] + [p.query for p in plan.positions]

    searches = [_search((p.queries + p.challenge_queries)[:5], _objective(p.text, ctx), location) for p in points]
    if plan.positions:
        searches.append(_search([p.query for p in plan.positions], "Find sources that state each of these positions on the issue: "
                                + "; ".join(p.label for p in plan.positions) + f". Issue: {points[0].text}", location))
    results = await asyncio.gather(*searches, return_exceptions=True)
    for r in results:
        if isinstance(r, BudgetExceeded):
            raise r
    for r in results:
        if isinstance(r, Exception):
            log.warning("research search failed: %s: %s", type(r).__name__, r)
    lists = [r for r in results if not isinstance(r, Exception)]
    if not lists:
        raise ResearchUnavailable("every search failed")
    groups: list[list[Source]] = []
    dropped = {"same_episode": 0, "own_organisation": 0}
    for lst in lists:  # each search kept apart, so pages can be read from every point's results
        kept, counts = split_sources(lst, ctx, policy)
        groups.append(kept)
        dropped["same_episode"] += counts[EPISODE]
        dropped["own_organisation"] += counts[OWN]
    found = [s for g in groups for s in g]
    sources = list({s.url: s for s in found}.values())

    findings: list[dict[str, Any]] = []
    read_urls: set[str] = set()
    pages_all: list[dict[str, Any]] = []

    async def read_round(chosen: list[Source], pts: list[PlanPoint], offset: int) -> None:
        pages = await _fetch(chosen, pts, plan.positions)
        if not pages:
            return
        read_urls.update(p["url"] for p in pages)
        pages_all.extend(pages)
        kept, drop = verify_findings(await _read(pts, pages), len(pts), pages)
        for f in kept:
            f["point"] += offset
        findings.extend(kept)
        for k, v in drop.items():
            dropped[k] = dropped.get(k, 0) + v

    await read_round(select_pages(groups, s.research_pages, read_urls), points, 0)

    def unanswered() -> list[int]:
        return [i for i in range(1, len(points) + 1)
                if not any(f["point"] == i and f["independence"] == INDEPENDENT and f["relation"] in ANSWERING for f in findings)]

    gap = unanswered()
    if gap and s.research_retry and ec.budget.spent_usd + s.lookup_cost_estimate_usd <= ec.budget.cap_usd:
        point = points[gap[0] - 1]
        try:
            new_q = clean_queries(await _rewrite(point, queries, [x.title for x in found]), answer)[:2]
            if new_q:
                queries += new_q
                extra, c2 = split_sources(await _search(new_q, _objective(point.text, ctx), location), ctx, policy)
                dropped["same_episode"] += c2[EPISODE]
                chosen = select_pages([extra], 3, read_urls)
                if chosen:
                    await read_round(chosen, [point], gap[0] - 1)
                    sources += [x for x in extra if x.url not in {y.url for y in sources}]
        except BudgetExceeded:
            raise
        except Exception as e:
            log.warning("research retry failed: %s: %s", type(e).__name__, e)

    out_points = []
    for i, p in enumerate(points, 1):
        fs = sorted((f for f in findings if f["point"] == i), key=lambda f: (f["independence"] != INDEPENDENT, PRIORITY[f["relation"]]))
        out_points.append({"text": p.text, "kind": p.kind, "status": point_status(fs), "findings": [{k: v for k, v in f.items() if k != "point"} for f in fs]})
    related, counter, summary, counter_summary, match = assemble(out_points, pages_all, [x for x in sources if x.independence == INDEPENDENT])
    return Research(points=out_points, positions=[p.label for p in plan.positions], queries=queries, related=related, counter=counter,
                    summary=summary, counter_summary=counter_summary, match=match, dropped={k: v for k, v in dropped.items() if v},
                    pages=[{"url": p["url"], "site": p["site"], "title": p["title"], "independence": p["independence"]} for p in pages_all])
