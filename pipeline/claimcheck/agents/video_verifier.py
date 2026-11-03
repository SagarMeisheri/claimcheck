"""Automatic verification of a whole video, right after extraction: a short, bounded agentic loop.

Turn 0  code      claims that already have a similar verdict (cache) are published at once, free
Turn 1  triage    LLM (lite model): ONE call labels every claim: general knowledge / needs a search / skip,
                  and groups claims that one search can settle together
Turn 2  route     code: clamps the plan to the video's budget (claims, searches), keeps the rules the model can't
                  override (numbers, stricter-tier and political claims never go to the knowledge route)
Turn 3  work      parallel: one general-knowledge call for the easy claims, and one search + one batch judge call per
                  group of claims. Each claim is checked in code and published the moment it has a verdict
Turn 4  follow-up the claims still unsettled get ONE more search each, while the search budget lasts
Turn 5  (end)     anything left over goes back to 'not requested', so a viewer can still press Verify

Everything is an ADK Workflow (nodes: batch_triage, route, work, follow_route, follow_work). The model only proposes;
the same guardrails as the on-demand verifier decide the verdict (quote, number and source checks, neutral wording,
score, review flag). A claim is saved to the database as soon as it is done, and the web app shows it straight away.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from google.adk.agents.context import Context
from google.adk.runners import InMemoryRunner
from google.adk.workflow import RetryConfig, START, Workflow, node
from google.genai import types

from ..config import Settings
from ..context import Budget, EpisodeContext, get_context, is_budget_error, report_progress, set_context
from ..guardrails.verdict_checks import apply_verdict_checks, truth_score
from ..policy import load_policy, needs_review
from ..schemas import BatchJudgeOutput, BatchTriage, FinalVerdict, JudgeResult, KnowledgeResult
from ..store import embed_texts
from ..tools.evidence import run_search
from .llm_agents import batch_judge_agent, batch_triage_agent, knowledge_agent
from .on_demand import _lock, record_from_row

log = logging.getLogger("claimcheck")
APP = "claimcheck_video_verifier"
FOLLOW_UP_RESERVE = 1  # searches kept back for the follow-up turn


# --- Pure helpers (no model, no network) ---------------------------------------------------------

_YEAR = re.compile(r"\b(1[0-9]|20)\d{2}\b")


def knowledge_ok(claim_text: str, tier: str) -> bool:
    """Only plain, normal-tier claims with no figures may be answered from general knowledge. Years are fine."""
    return tier == "normal" and not re.search(r"\d", _YEAR.sub("", claim_text or ""))


def select_claims(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The claims to check: the most check-worthy `limit`, back in the order they were said."""
    best = sorted(rows, key=lambda r: (-(r.get("checkworthiness") or 0), r.get("start_s") or 0))[:max(0, limit)]
    return sorted(best, key=lambda r: r.get("start_s") or 0)


def claims_block(claims: list[dict[str, Any]]) -> str:
    return "\n".join(f"{c['n']}. [{c.get('speaker') or 'Speaker'}] {c['claim_text']}" for c in claims)


def plan_items(triage: dict[str, Any] | None, claims: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    """The model proposes; code decides. Returns the work items plus the claim numbers left out.

    - knowledge route only for claims that pass `knowledge_ok`; the rest are searched
    - claims with the same group label share one search; groups are ordered by priority
    - at most (max searches - 1) groups run now; the last search is kept for the follow-up turn
    """
    by_n = {int(i["n"]): i for i in (triage or {}).get("items", []) if str(i.get("n", "")).isdigit() or isinstance(i.get("n"), int)}
    knowledge: list[int] = []
    skipped: list[int] = []
    groups: dict[str, dict[str, Any]] = {}
    for c in claims:
        n = c["n"]
        item = by_n.get(n, {})
        route = item.get("route", "search")
        if route == "skip":
            skipped.append(n)
            continue
        if route == "knowledge" and knowledge_ok(c["claim_text"], c.get("policy_tier") or "normal"):
            knowledge.append(n)
            continue
        key = (item.get("group") or "").strip().lower() or f"solo-{n}"
        g = groups.setdefault(key, {"label": key, "query": "", "ns": [], "priority": 3, "first": n})
        g["ns"].append(n)
        g["priority"] = min(g["priority"], int(item.get("priority") or 2))
        if not g["query"] and (item.get("query") or "").strip():
            g["query"] = item["query"].strip()[:300]
    ordered = sorted(groups.values(), key=lambda g: (g["priority"], g["first"]))
    now = max(1, settings.auto_verify_max_searches - FOLLOW_UP_RESERVE)
    run_now, later = ordered[:now], ordered[now:]
    by_claim = {c["n"]: c for c in claims}
    for g in run_now:
        g["query"] = g["query"] or by_claim[g["ns"][0]]["claim_text"][:300]
    return {"knowledge": knowledge, "groups": run_now, "skipped": skipped,
            "unresolved": [n for g in later for n in g["ns"]]}


def follow_up_items(results: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    """After the first work turn: which unsettled claims get one more search, and which verdicts are published as they are."""
    used = sum(int(r.get("searches") or 0) for r in results)
    left = max(0, settings.auto_verify_max_searches - used)
    wanted: dict[str, list[dict[str, Any]]] = {}  # query -> claim rows
    deferred_by_id: dict[str, dict[str, Any]] = {}
    for r in results:
        for d in r.get("deferred", []):
            deferred_by_id[d["claim"]["id"]] = d
            wanted.setdefault(d["query"], []).append(d["claim"])
        for c in r.get("escalate", []):
            wanted.setdefault(c["claim_text"][:300], []).append(c)
    items, taken = [], set()
    for q, rows in list(wanted.items())[:left]:
        items.append({"kind": "group", "label": "follow-up", "query": q, "claims": rows, "last": True})
        taken.update(c["id"] for c in rows)
    publish_now = [d for cid, d in deferred_by_id.items() if cid not in taken]
    return {"items": items, "publish_now": publish_now}


# --- Publishing ----------------------------------------------------------------------------------

async def publish(ec: EpisodeContext, row: dict[str, Any], final: FinalVerdict, model: str, cached_id: Optional[str] = None) -> None:
    """Saves one verdict the moment it exists. The web app polls and shows it."""
    await ec.store.save_claim_verdict(row["id"], final, cached_id, ec.embeddings.get(int(row["idx"])), model)
    await ec.store.refresh_episode_after_verify(ec.episode_id, final.review_status == "pending")
    ec.auto["published"].add(row["id"])
    done, total = len(ec.auto["published"]), ec.auto["total"]
    await report_progress(ec, f"Verifying claims: {done} of {total} done", int(100 * done / max(total, 1)))


def _finalise(judge: JudgeResult, row: dict[str, Any], evidence: dict[str, Any]) -> FinalVerdict:
    """The same code-side checks as the on-demand verifier: quotes, numbers, sources, wording, score, review flag."""
    ec = get_context()
    rec = record_from_row(row)
    final, downgrades = apply_verdict_checks(judge, rec.claim, rec.effective_tier, evidence, ec.policy)
    for rule, detail in downgrades:
        ec.log("verdict", rule, "downgraded" if "->" in detail else "flagged", detail, rec.index)
    if final.verdict != "false":
        final.correction = ""
    final.score = truth_score(final.verdict, final.confidence, final.citations)
    if needs_review(final.verdict, rec.effective_tier, ec.track, ec.policy):
        final.review_status = "pending"
        ec.log("review", "human_signoff_required", "flagged", final.verdict, rec.index)
    return final


# --- Running an agent in its own session (so parallel workers never share state) ------------------

async def _run_agent(agent: Any, state: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    runner = InMemoryRunner(agent=agent, app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="auto", state=state)
    msg = types.Content(role="user", parts=[types.Part(text="Go.")])
    async for _ in runner.run_async(user_id="auto", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="auto", session_id=session.id)
    return dict(done.state)


# --- Workers -------------------------------------------------------------------------------------

async def _knowledge(item: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    claims = item["claims"]
    st = await _run_agent(knowledge_agent(ec.settings), {"claims_block": claims_block(claims)})
    res = KnowledgeResult.model_validate(st["knowledge"]) if st.get("knowledge") else None
    by_n = {i.n: i for i in (res.items if res else [])}
    escalate = []
    for c in claims:
        k = by_n.get(c["n"])
        if k and k.tag == "TRUE" and k.confidence >= ec.settings.knowledge_min_confidence:
            final = FinalVerdict(verdict="supported", confidence=round(k.confidence, 3), basis="model_knowledge", score=None,
                                 reasoning=f"Based on well-established general knowledge; no source was searched. {k.explanation}".strip())
            ec.log("verdict", "answered_from_knowledge", "flagged", c["claim_text"][:120], int(c["idx"]))
            await publish(ec, c, final, ec.settings.lite_model)
        else:
            escalate.append(c)  # FALSE, UNSURE or low confidence: never published from memory, goes to a search
    return {"kind": "knowledge", "searches": 0, "deferred": [], "escalate": escalate}


async def _group(item: dict[str, Any]) -> dict[str, Any]:
    ec = get_context()
    claims, last = item["claims"], bool(item.get("last"))
    key = f"{ec.episode_id}:auto:{uuid.uuid4().hex[:8]}"
    objective = " | ".join(c["claim_text"] for c in claims)[:600]
    await run_search({"claim_key": key, "claim_index": None, "claim_text": objective,
                      "pestle_area": claims[0].get("pestle_area") or "economic", "query": item["query"],
                      "scope": "open", "purpose": "corroborate"})
    st = await _run_agent(batch_judge_agent(ec.settings, name=f"batch_judge_{uuid.uuid4().hex[:4]}"),
                          {"claim_key": key, "video_title": ec.auto.get("video_title", ""), "claims_block": claims_block(claims)})
    judged = next((v for k, v in st.items() if k.startswith("batch_judge") and v), None)
    out = BatchJudgeOutput.model_validate(judged) if judged else None
    by_n = {v.n: v for v in (out.verdicts if out else [])}
    evidence = ec.evidence.get(key, {})
    deferred = []
    for c in claims:
        v = by_n.get(c["n"])
        judge = v.to_result() if v else JudgeResult(verdict="unverifiable", confidence=0.0, reasoning="The judge returned no verdict.", citations=[])
        final = _finalise(judge, c, evidence)
        if final.verdict == "unverifiable" and not last and v and v.follow_up_query.strip():
            deferred.append({"claim": c, "final": final.model_dump(), "query": v.follow_up_query.strip()[:300]})
        else:
            await publish(ec, c, final, ec.settings.auto_judge_model)
    return {"kind": "group", "searches": 1, "deferred": deferred, "escalate": []}


async def _work(node_input: dict[str, Any]) -> dict[str, Any]:
    """One work item. Never raises: a failed item leaves its claims unpublished and the others carry on."""
    ec = get_context()
    try:
        return await (_knowledge(node_input) if node_input["kind"] == "knowledge" else _group(node_input))
    except Exception as e:
        if is_budget_error(e):
            ec.auto["budget_hit"] = True
        else:
            log.exception("automatic verification item failed")
        ec.log("auto_verify", "item_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        return {"kind": node_input.get("kind"), "searches": 1 if node_input.get("kind") == "group" else 0, "deferred": [], "escalate": [], "error": True}


# --- The workflow ----------------------------------------------------------------------------------

def build_video_verifier(settings: Settings) -> Workflow:
    async def route(ctx: Context, node_input: Any) -> list[dict[str, Any]]:
        claims = ctx.state["claims"]
        plan = plan_items(node_input if isinstance(node_input, dict) else None, claims, settings)
        by_n = {c["n"]: c for c in claims}
        ec = get_context()
        ec.auto["left_out"] = set(plan["skipped"]) | set(plan["unresolved"])
        items: list[dict[str, Any]] = []
        if plan["knowledge"]:
            items.append({"kind": "knowledge", "claims": [by_n[n] for n in plan["knowledge"]]})
        for g in plan["groups"]:
            items.append({"kind": "group", "label": g["label"], "query": g["query"], "claims": [by_n[n] for n in g["ns"]], "last": False})
        return items

    async def follow_route(node_input: Any) -> list[dict[str, Any]]:
        results = [r for r in (node_input or []) if isinstance(r, dict)]
        plan = follow_up_items(results, settings)
        ec = get_context()
        for d in plan["publish_now"]:  # unsettled and out of searches: publish the (unverifiable) verdict as it is
            await publish(ec, d["claim"], FinalVerdict.model_validate(d["final"]), settings.auto_judge_model)
        return plan["items"]

    timeout = settings.tool_timeout_s * 3
    work = node(_work, name="work", parallel_worker=True, max_parallel_workers=settings.auto_verify_max_searches + 1,
                retry_config=RetryConfig(max_attempts=1), timeout=timeout)
    follow_work = node(_work, name="follow_work", parallel_worker=True, max_parallel_workers=settings.auto_verify_max_searches,
                       retry_config=RetryConfig(max_attempts=1), timeout=timeout)
    return Workflow(name="video_verifier", edges=[(START, batch_triage_agent(settings), node(route, name="route"), work,
                                                   node(follow_route, name="follow_route"), follow_work)])


# --- Entry point -------------------------------------------------------------------------------------

async def run_video_verification(episode_id: str, *, settings: Settings, store: Any, manual: bool = False) -> dict[str, Any]:
    """Verifies the most check-worthy unverified claims of one video. Never raises; leftovers go back to 'not requested'.

    manual=True is the "Verify all claims" button: higher limits (verify_all_max_*) than the automatic run.
    """
    from dataclasses import replace

    from .pipeline import make_plugins_factory

    if manual:
        settings = replace(settings, auto_verify_max_claims=settings.verify_all_max_claims,
                           auto_verify_max_searches=settings.verify_all_max_searches)
    async with _lock(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            return {"status": "skipped", "reason": "The video hasn't finished its first pass."}
        rows = select_claims(await store.list_auto_verify_claims(episode_id), settings.auto_verify_max_claims)
        cap, spent = settings.max_cost_usd_per_episode, float(ep.get("cost_usd") or 0)
        if not rows or spent >= cap:
            await store.update_episode(episode_id, {"auto_verify_status": "done"})  # the Publisher set "running"
            return {"status": "skipped", "reason": "Nothing to verify." if not rows else "Over the video's budget."}
        claims = [{**r, "n": i + 1} for i, r in enumerate(rows)]
        track = ((ep.get("channels") or {}).get("track")) or "finance_health"
        ec = EpisodeContext(episode_id=episode_id, video_id=ep.get("youtube_video_id", ""), track=track, settings=settings,
                            policy=load_policy(), store=store, budget=Budget(cap_usd=cap, spent_usd=spent),
                            plugins_factory=make_plugins_factory(settings))
        ec.auto = {"published": set(), "total": len(claims), "video_title": ep.get("title") or "", "left_out": set(), "budget_hit": False}
        token = set_context(ec)
        failed = False
        try:
            for c in claims:  # show "verifying" on every selected claim straight away
                await store.set_claim_status(c["id"], "verifying")
            await store.update_episode(episode_id, {"auto_verify_status": "running"})
            await report_progress(ec, f"Verifying claims: 0 of {len(claims)} done", 0)

            # Turn 0: similar claims already judged (cache) cost nothing.
            todo = claims
            try:
                embs = await embed_texts([c["claim_text"] for c in claims], settings)
                ec.embeddings = {int(c["idx"]): e for c, e in zip(claims, embs)}
                todo = []
                for c in claims:
                    hit = await store.match_verdict(ec.embeddings[int(c["idx"])], settings.cache_similarity, settings.cache_max_age_days)
                    if not hit:
                        todo.append(c)
                        continue
                    verdict_id, fv = hit
                    fv.from_cache = True
                    fv.score = truth_score(fv.verdict, fv.confidence, fv.citations)
                    ec.log("cache", "verdict_reused", "flagged", verdict_id, int(c["idx"]))
                    await publish(ec, c, fv, settings.judge_model, cached_id=verdict_id)
            except Exception:
                log.exception("cache lookup failed during automatic verification; continuing without it")
                todo = [c for c in claims if c["id"] not in ec.auto["published"]]

            # Turns 1-4: the ADK workflow.
            if todo:
                wf = build_video_verifier(settings)
                runner = InMemoryRunner(node=wf, app_name=APP, plugins=ec.plugins_factory())
                session = await runner.session_service.create_session(app_name=APP, user_id="auto", state={
                    "claims": todo, "claims_block": claims_block(todo), "video_title": ec.auto["video_title"]})
                msg = types.Content(role="user", parts=[types.Part(text="Verify the claims.")])
                async for _ in runner.run_async(user_id="auto", session_id=session.id, new_message=msg):
                    pass
        except Exception as e:
            failed = True
            if not is_budget_error(e):
                log.exception("automatic verification of episode %s failed", episode_id)
            ec.log("auto_verify", "run_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        finally:
            try:
                for c in claims:  # anything not published goes back, so a viewer can still press Verify
                    if c["id"] not in ec.auto["published"]:
                        await store.set_claim_status(c["id"], "failed" if failed else "not_requested",
                                                     "Couldn't be verified automatically. Try again." if failed else None)
                await store.add_episode_cost(episode_id, ec.budget.spent_usd - spent, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
                await store.update_episode(episode_id, {"auto_verify_status": "done", "progress": {}})
            except Exception:
                log.exception("could not finish automatic verification bookkeeping for %s", episode_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        return {"status": "failed" if failed else "done", "verified": len(ec.auto["published"]), "of": len(claims),
                "cost_usd": round(ec.budget.spent_usd - spent, 4)}
