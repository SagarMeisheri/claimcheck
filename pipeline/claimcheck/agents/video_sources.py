"""Sources for every claim in one video ("Check sources for all claims"): a short, bounded loop.

Turn 1  triage    LLM (lite model): ONE call plans a search per group of claims that one search can cover, or skips
                  claims too vague to look up
Turn 2  route     code: clamps the plan to the video's limits (claims, searches)
Turn 3  work      parallel: one search + one batch pick per group. Each claim's picks go through the same checks in code
                  as a single lookup (guardrails/source_checks.py) and are saved the moment they exist
Turn 4  follow-up claims with nothing found get ONE more search each, while the search budget lasts
Turn 5  (end)     anything left over goes back to 'not requested', so a viewer can still press "Check sources"

Everything is an ADK Workflow (nodes: batch_triage, route, work, follow_route, follow_work). The model only proposes
searches and sentences; code decides what is shown. Nothing here says whether a claim is right.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from google.adk.agents.context import Context
from google.adk.runners import InMemoryRunner
from google.adk.workflow import RetryConfig, START, Workflow, node
from google.genai import types

from ..config import Settings
from ..context import Budget, EpisodeContext, get_context, is_budget_error, report_progress, set_context
from ..guardrails.source_checks import check_sources
from ..policy import load_policy
from ..schemas import BatchPick, CheckedSource
from ..tools.evidence import run_search
from .llm_agents import batch_picker_agent, batch_triage_agent
from .sources_on_demand import lock_for

log = logging.getLogger("claimcheck")
APP = "claimcheck_video_sources"
FOLLOW_UP_RESERVE = 1  # searches kept back for the follow-up turn


# --- Pure helpers (no model, no network) ---------------------------------------------------------

def select_claims(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The claims to look up: the first `limit`, in the order they were said."""
    return sorted(rows, key=lambda r: r.get("start_s") or 0)[:max(0, limit)]


def claims_block(claims: list[dict[str, Any]]) -> str:
    return "\n".join(f"{c['n']}. {c['claim_text']}" for c in claims)


def plan_items(triage: dict[str, Any] | None, claims: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    """The model proposes; code decides. Returns the search groups plus the claim numbers left out.

    - claims with the same group label share one search; groups are ordered by priority
    - at most (max searches - 1) groups run now; the last search is kept for the follow-up turn
    """
    by_n = {int(i["n"]): i for i in (triage or {}).get("items", []) if str(i.get("n", "")).isdigit() or isinstance(i.get("n"), int)}
    skipped: list[int] = []
    groups: dict[str, dict[str, Any]] = {}
    for c in claims:
        n = c["n"]
        item = by_n.get(n, {})
        if item.get("route") == "skip":
            skipped.append(n)
            continue
        key = (item.get("group") or "").strip().lower() or f"solo-{n}"
        g = groups.setdefault(key, {"label": key, "query": "", "ns": [], "priority": 3, "first": n})
        g["ns"].append(n)
        g["priority"] = min(g["priority"], int(item.get("priority") or 2))
        if not g["query"] and (item.get("query") or "").strip():
            g["query"] = item["query"].strip()[:300]
    ordered = sorted(groups.values(), key=lambda g: (g["priority"], g["first"]))
    now = max(1, settings.sources_all_max_searches - FOLLOW_UP_RESERVE)
    run_now, later = ordered[:now], ordered[now:]
    by_claim = {c["n"]: c for c in claims}
    for g in run_now:
        g["query"] = g["query"] or by_claim[g["ns"][0]]["claim_text"][:300]
    return {"groups": run_now, "skipped": skipped, "unresolved": [n for g in later for n in g["ns"]]}


def follow_up_items(results: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    """After the first work turn: which claims with nothing found get one more search, and which are saved as they are."""
    used = sum(int(r.get("searches") or 0) for r in results)
    left = max(0, settings.sources_all_max_searches - used)
    wanted: dict[str, list[dict[str, Any]]] = {}  # query -> claim rows
    deferred_by_id: dict[str, dict[str, Any]] = {}
    for r in results:
        for d in r.get("deferred", []):
            deferred_by_id[d["claim"]["id"]] = d
            wanted.setdefault(d["query"], []).append(d["claim"])
    items, taken = [], set()
    for q, rows in list(wanted.items())[:left]:
        items.append({"label": "follow-up", "query": q, "claims": rows, "last": True})
        taken.update(c["id"] for c in rows)
    save_now = [d["claim"] for cid, d in deferred_by_id.items() if cid not in taken]
    return {"items": items, "save_now": save_now}


# --- Saving --------------------------------------------------------------------------------------

async def save(ec: EpisodeContext, row: dict[str, Any], sources: list[CheckedSource]) -> None:
    """Saves one claim's sources the moment they exist (possibly none). The web app polls and shows them."""
    await ec.store.save_claim_sources(row["id"], sources)
    ec.batch["saved"].add(row["id"])
    done, total = len(ec.batch["saved"]), ec.batch["total"]
    await report_progress(ec, f"Checking sources: {done} of {total} done", int(100 * done / max(total, 1)))


# --- Running an agent in its own session (so parallel workers never share state) ------------------

async def _run_agent(agent: Any, state: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    runner = InMemoryRunner(agent=agent, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="batch", state=state)
    msg = types.Content(role="user", parts=[types.Part(text="Go.")])
    async for _ in runner.run_async(user_id="batch", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="batch", session_id=session.id)
    return dict(done.state)


# --- Worker --------------------------------------------------------------------------------------

async def _group(item: dict[str, Any]) -> dict[str, Any]:
    """One search for a group of claims, one batch pick, then the checks in code for each claim."""
    ec = get_context()
    claims, last = item["claims"], bool(item.get("last"))
    key = f"{ec.episode_id}:batch:{uuid.uuid4().hex[:8]}"
    objective = " | ".join(c["claim_text"] for c in claims)[:600]
    await run_search({"claim_key": key, "claim_index": None, "claim_text": objective,
                      "pestle_area": claims[0].get("pestle_area") or "economic", "query": item["query"],
                      "scope": "open", "purpose": "independent"})
    st = await _run_agent(batch_picker_agent(ec.settings, name=f"batch_picker_{uuid.uuid4().hex[:4]}"),
                          {"claim_key": key, "video_title": ec.batch.get("video_title", ""), "claims_block": claims_block(claims)})
    out = BatchPick.model_validate(st["batch_picked"]) if st.get("batch_picked") else None
    by_n = {i.n: i for i in (out.items if out else [])}
    evidence = ec.evidence.get(key, {})
    deferred = []
    for c in claims:
        picked = by_n.get(c["n"])
        idx = int(c.get("idx") or 0)
        sources = check_sources(picked.sources if picked else [], evidence, ec.policy,
                                log=lambda rule, url, i=idx: ec.log("sources", rule, "skipped", url, i), claim_index=idx)
        if not sources and not last and picked and picked.follow_up_query.strip():
            deferred.append({"claim": c, "query": picked.follow_up_query.strip()[:300]})
        else:
            await save(ec, c, sources)
    return {"searches": 1, "deferred": deferred}


async def _work(node_input: dict[str, Any]) -> dict[str, Any]:
    """One work item. Never raises: a failed item leaves its claims unsaved and the others carry on."""
    ec = get_context()
    try:
        return await _group(node_input)
    except Exception as e:
        if is_budget_error(e):
            ec.batch["budget_hit"] = True
        else:
            log.exception("source lookup item failed")
        ec.log("sources_all", "item_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        return {"searches": 1, "deferred": [], "error": True}


# --- The workflow ----------------------------------------------------------------------------------

def build_workflow(settings: Settings) -> Workflow:
    async def route(ctx: Context, node_input: Any) -> list[dict[str, Any]]:
        claims = ctx.state["claims"]
        plan = plan_items(node_input if isinstance(node_input, dict) else None, claims, settings)
        by_n = {c["n"]: c for c in claims}
        return [{"label": g["label"], "query": g["query"], "claims": [by_n[n] for n in g["ns"]], "last": False}
                for g in plan["groups"]]

    async def follow_route(node_input: Any) -> list[dict[str, Any]]:
        results = [r for r in (node_input or []) if isinstance(r, dict)]
        plan = follow_up_items(results, settings)
        ec = get_context()
        for row in plan["save_now"]:  # nothing found and out of searches: save the empty result
            await save(ec, row, [])
        return plan["items"]

    timeout = settings.tool_timeout_s * 3
    work = node(_work, name="work", parallel_worker=True, max_parallel_workers=settings.sources_all_max_searches,
                retry_config=RetryConfig(max_attempts=1), timeout=timeout)
    follow_work = node(_work, name="follow_work", parallel_worker=True, max_parallel_workers=settings.sources_all_max_searches,
                       retry_config=RetryConfig(max_attempts=1), timeout=timeout)
    return Workflow(name="video_sources", edges=[(START, batch_triage_agent(settings), node(route, name="route"), work,
                                                  node(follow_route, name="follow_route"), follow_work)])


# --- Entry point -------------------------------------------------------------------------------------

async def run_video_sources(episode_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Looks up sources for the claims of one video. Never raises; leftovers go back to 'not requested'."""
    from .pipeline import make_plugins_factory

    async with lock_for(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            return {"status": "skipped", "reason": "The video hasn't finished being analysed."}
        rows = select_claims(await store.list_batch_claims(episode_id), settings.sources_all_max_claims)
        cap, spent = settings.max_cost_usd_per_episode, float(ep.get("cost_usd") or 0)
        if not rows or spent >= cap:
            await store.update_episode(episode_id, {"sources_batch_status": None})
            return {"status": "skipped", "reason": "Nothing to look up." if not rows else "Over the video's budget."}
        claims = [{**r, "n": i + 1} for i, r in enumerate(rows)]
        ec = EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), settings=settings,
                            policy=load_policy(), store=store, budget=Budget(cap_usd=cap, spent_usd=spent),
                            plugins_factory=make_plugins_factory(settings))
        ec.batch = {"saved": set(), "total": len(claims), "video_title": ep.get("title") or "", "budget_hit": False}
        token = set_context(ec)
        failed = False
        try:
            for c in claims:  # show "searching" on every selected claim straight away
                await store.set_sources_status(c["id"], "searching")
            await store.update_episode(episode_id, {"sources_batch_status": "running"})
            await report_progress(ec, f"Checking sources: 0 of {len(claims)} done", 0)
            runner = InMemoryRunner(node=build_workflow(settings), app_name=APP, plugins=ec.plugins_factory())
            session = await runner.session_service.create_session(app_name=APP, user_id="batch", state={
                "claims": claims, "claims_block": claims_block(claims), "video_title": ec.batch["video_title"]})
            msg = types.Content(role="user", parts=[types.Part(text="Find sources for the claims.")])
            async for _ in runner.run_async(user_id="batch", session_id=session.id, new_message=msg):
                pass
        except Exception as e:
            failed = True
            if not is_budget_error(e):
                log.exception("source lookup for episode %s failed", episode_id)
            ec.log("sources_all", "run_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        finally:
            try:
                for c in claims:  # anything not saved goes back, so a viewer can still press "Check sources"
                    if c["id"] not in ec.batch["saved"]:
                        await store.set_sources_status(c["id"], "failed" if failed else "not_requested",
                                                       "Couldn't look up sources. Try again." if failed else None)
                await store.add_episode_cost(episode_id, ec.budget.spent_usd - spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
                await store.update_episode(episode_id, {"sources_batch_status": None, "progress": {}})
            except Exception:
                log.exception("could not finish source lookup bookkeeping for %s", episode_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        return {"status": "failed" if failed else "done", "saved": len(ec.batch["saved"]), "of": len(claims),
                "cost_usd": round(ec.budget.spent_usd - spent, 4)}
