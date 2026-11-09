"""A video's answers looked up together (settings.batch_lookups), instead of one lookup per answer.

The same lookup as agents/sources.lookup_answer gives for one answer (tag, plan, search, ground), in phases over the whole video:

  1 classify   the first classifier call (answer type, claim type, the stake checks), several answers by one speaker to a call
               (settings.tag_batch). A pure opinion is settled here: no planner, no search.
  2 plan       ONE planner call reads every answer that needs research (agents/research.research_video) and writes the points of each
               and the search requests, answers about the same subject sharing one request. A video longer than settings.plan_chunk
               answers is planned in chunks.
  3 search     each request once, a few at a time; a search made lately for the same queries is reused.
  4 assess     as an answer's requests come back, its assessment (one call per answer, agents/assess.py) and the rules in code.

Each answer is reported the moment it is finished (`on_done`), so the page fills in as it goes. Before that, what each stage finds is
reported as it arrives (`on_progress`): the tags as each classifier call returns, the planner's points as the model writes them, the
queries, the pages as each search comes back, the verdict as soon as the assessment is in. The caller saves these for the page to show; they are best-effort and change nothing about the result. An answer the budget didn't reach is
not reported at all: the caller puts it back to what it was. A lookup of one answer (the "Check sources" button) is unchanged.

Because the planner needs the whole video, these lookups start after the answers are all saved, not while the extractor is writing
(agents/pipeline.py does not start AutoSources when settings.batched).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Union

from ..context import get_context, is_budget_error

log = logging.getLogger("claimcheck")

Done = Callable[[int, Any], Awaitable[None]]  # (index in `claims`, a sources.Lookup or the exception that stopped it)
Progress = Callable[[int, Optional[dict[str, Any]], Optional[dict[str, Any]]], Awaitable[None]]  # (index, qa_tags so far, research so far)
Phase = Callable[[str], Awaitable[None]]


async def lookup_many(claims: list[dict[str, Any]], vctx: Any, on_done: Done, *, force: bool = False, fresh: bool = False,
                      on_progress: Optional[Progress] = None, on_phase: Optional[Phase] = None) -> None:
    """Looks up sources for these answers together. `claims` are claim rows (as lookup_answer takes them); `on_done(i, result)` is
    awaited once per answer that was finished: result is a sources.Lookup, or the exception (the answer is then marked failed). Never
    raises."""
    from .qa_tags import Job, batches, classify_answers, decide, ground, settle_route
    from .research import research_video
    from .sources import Lookup

    ec = get_context()
    s = ec.settings
    jobs = [Job(ctx=vctx.for_claim(c), location=vctx.location, force=force) for c in claims]
    index = {id(j): i for i, j in enumerate(jobs)}
    gate = asyncio.Semaphore(max(1, s.sources_concurrency))
    unreached: set[int] = set()

    locks: dict[int, asyncio.Lock] = {}

    async def show(i: int, tags: Optional[dict[str, Any]] = None, research: Optional[dict[str, Any]] = None) -> None:
        """Hands over what answer i has so far, one at a time per answer so an older snapshot never lands after a newer one."""
        if on_progress is None:
            return
        async with locks.setdefault(i, asyncio.Lock()):
            try:
                await on_progress(i, tags, research)
            except Exception as e:
                log.warning("could not show progress for answer %s: %s: %s", i, type(e).__name__, e)

    async def phase(label: str) -> None:
        if on_phase is not None:
            try:
                await on_phase(label)
            except Exception as e:
                log.warning("could not show the phase: %s: %s", type(e).__name__, e)

    async def report(i: int, found: Union[Any, BaseException]) -> None:
        try:
            await on_done(i, found)
        except Exception:
            log.exception("could not save the lookup of answer %s", i)

    # 1. classify: as each call returns, an opinion is settled and the rest show the tags they have
    research: list[tuple[int, dict[str, Any]]] = []

    async def classify(group: list[Any]) -> None:
        async with gate:
            if ec.budget.spent_usd + s.tag_cost_estimate_usd > ec.budget.cap_usd:
                unreached.update(index[id(j)] for j in group)
                return
            try:
                await classify_answers(group)
            except Exception as e:
                if not is_budget_error(e):
                    log.exception("batched answer tags crashed")
                unreached.update(index[id(j)] for j in group)
                return
        for job in group:
            i = index[id(job)]
            try:
                if settle_route(job) == "exempt":
                    await report(i, Lookup("skip", [], None, decide(job)))
                else:
                    research.append((i, job.ctx))
                    await show(i, tags=decide(job))
            except Exception as e:
                await report(i, e)

    await phase(f"Tagging {len(jobs)} answers")
    await asyncio.gather(*(classify(g) for g in batches(jobs, s.tag_batch)))
    research.sort(key=lambda x: x[0])
    if not research:
        return
    if ec.budget.spent_usd + s.research_plan_cost_estimate_usd > ec.budget.cap_usd:
        return  # no room for the planner: these answers go back to what they were

    # 2-4. plan, search, ground
    async def ready(i: int, result: Union[Any, BaseException, None]) -> None:
        job = jobs[i]
        try:
            if isinstance(result, BaseException):
                if not is_budget_error(result):
                    await report(i, result)
                return
            if result is None:  # the plan found nothing checkable
                job.route = "no_points"
                await report(i, Lookup("skip", [], None, decide(job)))
                return
            job.route, job.research = "researched", result
            await show(i, research={**result.stored(), "stage": "grounding"})  # every page is in; the verdict is being weighed
            async with gate:
                await ground(job, on_label=lambda: show(i, tags=decide(job)))  # the verdict shows as soon as the assessment is in
            tags = decide(job)
            result.match = (tags.get("match") or {}).get("label") or result.match
            await report(i, Lookup("related", result.related, result, tags))
        except Exception as e:
            if not is_budget_error(e):
                log.warning("answer %s could not be finished: %s: %s", i, type(e).__name__, e)
                await report(i, e)

    async def planned(i: int, data: dict[str, Any]) -> None:
        await show(i, research=data)

    await research_video(research, vctx.location, ready, force=force, fresh=fresh, on_progress=planned, on_phase=phase)
