"""The interview as a whole, after extraction: how each question was asked, and how host and guest dealt with each other.

Batched ADK classifier calls (pipeline stage InterviewTagger, after the statements are saved):
  - one Choice per distinct question the host asked (agents/qa_tags.QUESTIONS["question_type"]: factual / explanatory /
    experiential / evaluative / speculative / challenging), up to BATCH questions per call. Every call is shown every question of the
    video (the host's own words and who asked), never an answer, and answers only its own batch.
  - in the first call, also a Choice for the dynamic: promotional / neutral / adversarial, with the host's and guests' incentive tags.
So a 50-question interview costs 2 calls. A question tagged below SURE is "unclear"; one tagged from the AI's plain-words rewrite
(no spoken words kept) has spoken = false.

Saved as claims.question_analysis = {"type", "p", "spoken"} on every answer to that question, and episodes.interaction.dynamic.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.labs.classifiers import Choice
from google.genai import types

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text
from ..profiles import name_key
from ..schemas import ClaimRecord
from .qa_tags import QTYPES, QUESTIONS, SURE

log = logging.getLogger("claimcheck")
BATCH = 25
MAX_QUESTIONS = 150
DYNAMICS = ("promotional", "neutral", "adversarial")
DYNAMIC = Choice(
    instructions=("How did the host and the guest deal with each other across all these questions? Judge the questions as asked; the "
                  "incentive tags only say who has a stake in what."),
    criteria={
        "promotional": "Friendly and aligned: the host sets up the guest's talking points, with soft or teed-up questions and little real pushback.",
        "neutral": "Genuine curiosity: open questions with occasional follow-ups or counter-views, and no shared stake on display.",
        "adversarial": "High friction: the host repeatedly presses, contradicts or stress-tests the guest's claims.",
    })


def exchanges(records: list[ClaimRecord]) -> list[dict[str, Any]]:
    """Distinct asked questions in the order asked: {"id", "question_as_asked", "asked_by", "spoken", "idxs": [record indexes]}."""
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(records, key=lambda r: r.start_s):
        c = r.claim
        if r.not_checked_reason == "outside_policy" or c.question_kind == "implied" or not c.question:
            continue
        key = name_key(c.question)
        if key not in out:
            spoken = (c.question_quote or "").strip()
            out[key] = {"id": f"q{len(out) + 1}", "question_as_asked": screen_text((spoken or c.question)[:400])[0],
                        "asked_by": c.asked_by or "the host", "spoken": bool(spoken), "idxs": []}
        out[key]["idxs"].append(r.index)
    return list(out.values())[:MAX_QUESTIONS]


def _questions(batch: list[dict[str, Any]], with_dynamic: bool) -> dict[str, Any]:
    base = QUESTIONS["question_type"]
    qs: dict[str, Any] = {x["id"]: Choice(instructions=f"For the question with id {x['id']} in the input: {base.instructions}", criteria=base.criteria)
                          for x in batch}
    if with_dynamic:
        qs["dynamic"] = DYNAMIC
    return qs


def payload(items: list[dict[str, Any]], host_tags: list[str], guest_tags: list[str]) -> dict[str, Any]:
    return {"questions": [{k: x[k] for k in ("id", "question_as_asked", "asked_by")} | ({} if x["spoken"] else {"plain_words_rewrite": True})
                          for x in items],
            "note": "plain_words_rewrite questions are the AI's rewrite, without the host's framing: don't infer a challenge that isn't visible.",
            "host_incentive_tags": host_tags or ["none"], "guest_incentive_tags": guest_tags or ["none"]}


async def _classify(input: dict[str, Any], questions: dict[str, Any]) -> Any:
    """One classifier call. A seam for tests."""
    from .llm_agents import tag_classifier

    return await tag_classifier(get_context().settings, "LOW").classify(input=input, questions=questions)


def _pick(answer: Any, valid: tuple[str, ...], fallback: str) -> Optional[dict[str, Any]]:
    if answer is None or answer.choice not in valid:
        return None
    p = round(float(answer.probabilities.get(answer.choice, 0.0)), 2)
    return {"type": answer.choice if p >= SURE else fallback, "p": p}


async def tag_interview(records: list[ClaimRecord], host_tags: list[str], guest_tags: list[str]) -> tuple[dict[int, dict[str, Any]], Optional[dict[str, Any]]]:
    """({record index: question_analysis}, dynamic or None). A failed batch leaves its questions untagged. Raises only for the budget."""
    ec = get_context()
    items = exchanges(records)
    if not items or ec.budget.spent_usd + ec.settings.tag_cost_estimate_usd > ec.budget.cap_usd:
        return {}, None
    inp = payload(items, host_tags, guest_tags)
    by_idx: dict[int, dict[str, Any]] = {}
    dynamic: Optional[dict[str, Any]] = None
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        try:
            res = await _classify(inp, _questions(batch, with_dynamic=start == 0 and len(items) >= 3))
        except Exception as e:
            if is_budget_error(e):
                raise
            ec.log("interview", "question_tags_failed", "skipped", f"{batch[0]['id']}-{batch[-1]['id']}: {type(e).__name__}: {e}"[:200])
            continue
        for x in batch:
            qa = _pick(res.answers.get(x["id"]), QTYPES, "unclear")
            if qa:
                for i in x["idxs"]:
                    by_idx[i] = {**qa, "spoken": x["spoken"]}
        d = _pick(res.answers.get("dynamic"), DYNAMICS, "neutral")
        if d:
            dynamic = {"dynamic": d["type"], "p": d["p"]}
    return by_idx, dynamic


class InterviewTagger(BaseAgent):
    """Pipeline stage after Publisher: the question types and the dynamic, saved on the answers and the video."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        text = "skipped"
        if not st.get("gate", {}).get("skip") and ec.settings.tag_answers:
            records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
            rows = list(ec.prepared_speakers.values())
            host = sorted({t for r in rows if r.get("role") == "host" for t in {**(r.get("incentives") or {}), **(r.get("incentives_internal") or {})}})
            guest = sorted({t for r in rows if r.get("role") != "host" for t in (r.get("incentives") or {})})
            try:
                by_idx, dynamic = await tag_interview(records, host, guest)
                ids = await ec.store.list_claim_ids(ec.episode_id)
                groups: dict[str, list[str]] = {}
                analyses: dict[str, dict[str, Any]] = {}
                for idx, qa in by_idx.items():
                    if idx in ids:
                        k = f"{qa['type']}|{qa['p']}|{qa['spoken']}"
                        groups.setdefault(k, []).append(ids[idx])
                        analyses[k] = qa
                for k, claim_ids in groups.items():
                    await ec.store.save_question_analysis(claim_ids, analyses[k])
                if dynamic:
                    await ec.store.update_episode(ec.episode_id, {"interaction": {"description_notes": ec.description_notes, **dynamic}})
                text = f"{len(by_idx)} answers' questions tagged; dynamic {(dynamic or {}).get('dynamic', 'unknown')}"
            except Exception as e:
                if is_budget_error(e):
                    raise
                log.exception("interview tags failed for %s", ec.episode_id)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta={}),
                    content=types.Content(role="model", parts=[types.Part(text=text)]))
