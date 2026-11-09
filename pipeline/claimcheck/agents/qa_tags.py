"""Tagging one answer with the Q&A taxonomy: a classifier call, then (for an answer that can be checked) research and an assessment.

  [Question] -> [Answer] -> [Claim] -> [Grounding + conflict flag], read against the speakers' incentive tags (agents/profile_tags.py).
The question type is not here: every question of a video is classified in one batched call after extraction (agents/interview.py),
since that classifier must never see the answer. Here, per answer:

  1 classify   ONE classifier call: Choice answer_type (direct / narrative / structured / pivot / evasive),
               Choice claim_type (objective_fact / anchored_opinion / pure_opinion / prediction), and, for EVERY answer whose speaker has
               a profile: the answer set against the speaker's whole profile as numbered items (incentive tags with their reasons, roles,
               businesses, holdings, sponsors, offices, politics): Choice stake_link (benefits / touches / none), Choice stake_item,
               Binary self_serving_pivot and disclosed; plus staged_pushback when the host is tagged invested_peer or sponsor_aligned.
               A pure opinion the classifier is sure of is exempt: no planner, no search.
  2 research   plan + one search (agents/research.py); nothing checkable -> no pages
  3 assess     ONE call (agents/assess.py): a TLDR for every page, what the pages say together, then each claim of the answer compared with
               the pages, with a verdict and a reason. Code decides the label from the claims.
So an answer costs 1 classifier call, or 2 calls when it is researched (plus the planner and the search).

The same steps run for a whole video in agents/batch.py (answer_call, settle_route and ground are shared): the first call takes several
answers by one speaker (classify_answers), the plan covers every researched answer at once (agents/research.research_video).

Code then applies the rules (decide):
  - a Choice below SURE falls back to the cautious label.
  - Grounding comes from the assessment's claims (assess.label_of): contradicted (a claim a page contradicts, with a quote), grounded (every
    claim supported), partly (some claims backed, none contradicted), plausible (no page settles any claim).
  - Rule 1, self-report: an answer that benefits something in the speaker's profile (stake_link "benefits") and that no INDEPENDENT page
    supports (not even partly) is "ungrounded", conflict "self_report". The profile item it rests on is saved as `stake` (also for
    "touches", which is not a conflict), with how many items were compared (`profile_checked`). Rule 2, context: missing_context is a
    flag; the grounding stays. Rule 3, disclosure: "disclosed" / "undisclosed".
  - a conditional answer only counts where it applies: self_serving_pivot only for a pivot, disclosure only for a self-serving
    answer; staged_pushback is kept as a flag and shown only when the question was challenging (the web joins the two).
  - nothing checkable: a prediction is exempt, anything else plausible (no public record).
A call that fails is left out; budget errors are never swallowed.

Saved as claims.qa_tags (see QaTags in web/lib/types.ts); the question type is claims.question_analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.labs.classifiers import Binary, Choice, ClassifierResponse

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text
from ..profiles import numbered_profile
from . import assess
from .correctness import build_correctness

log = logging.getLogger("claimcheck")
APP = "claimcheck_qa_tags"

QTYPES = ("factual", "explanatory", "experiential", "evaluative", "speculative", "challenging")
ATYPES = ("direct", "narrative", "structured", "pivot", "evasive")
CTYPES = ("objective_fact", "anchored_opinion", "pure_opinion", "prediction")
GROUNDING = ("grounded", "partly", "plausible", "contradicted", "exempt")  # + "ungrounded", set only by the self-report rule

STAKE_LINKS = ("benefits", "touches", "none")
STAKE_SURE = 0.5          # the link (benefits / touches) needs this much confidence
ITEM_SURE = 0.25          # the item is the closest of a dozen or so, so its probability is spread thin: a lower floor
HIDDEN_TAGS = frozenset({"access_preserving"})  # incentive tags that are never shown, so never quoted as a stake
STAKE_KINDS = frozenset({"business", "financial_interest", "sponsor", "ownership", "political", "role", "affiliations"})
MAX_STAKE_ITEMS = 25
CONTEXT_TAGS = frozenset({"ideological", "financial"})    # missing_context
SOFT_HOST_TAGS = frozenset({"invested_peer", "sponsor_aligned", "access_preserving"})  # staged_pushback

MAX_PAGES_SHOWN = assess.MAX_PAGES  # what the assessment is shown
SURE = 0.45
YES = 0.6
PURE_OPINION_SURE = 0.6  # a pure opinion below this is researched anyway: skipping the search is the bigger mistake

QUESTIONS: dict[str, Any] = {
    "question_type": Choice(
        instructions=("What kind of question did the host ask? Judge by the question_as_asked words only. A question that voices a "
                      "counter-view or a critic's point before asking counts as challenging."),
        criteria={
            "factual": "Asks for an objective fact, a definition or a data point (what, who, when, how much).",
            "explanatory": "Asks for a process, a cause or a mechanism (how, why).",
            "experiential": "Asks for the guest's own story, history, decisions or past actions.",
            "evaluative": "Asks for a judgement, a preference, advice or a critique (is it good, what should, what matters).",
            "speculative": "Asks for a prediction, a hypothetical or a future outcome (what if, will it).",
            "challenging": "Tests a premise, points out a contradiction, puts a criticism or counter-view, or plays devil's advocate.",
        }),
    "answer_type": Choice(
        instructions="How did the speaker answer the question? Compare the answer with what was asked.",
        criteria={
            "direct": "Answers the exact question clearly and straight away.",
            "narrative": "Answers through a story, an example or an analogy.",
            "structured": "Breaks the answer into a list, a framework or step-by-step logic.",
            "pivot": "Shifts the topic or changes the question's premise before answering, so it answers a different question.",
            "evasive": "Dodges, deflects with humour, declines, or gives a vague generality instead of an answer.",
        }),
    "claim_type": Choice(
        instructions="What does the answer mainly assert? Judge the answer's main point, not its asides.",
        criteria={
            "objective_fact": "Checkable data, historical events, rules, quotes or the speaker's own past actions.",
            "anchored_opinion": "A judgement backed by a stated fact or figure (\"X is bad because of Y statistic\").",
            "pure_opinion": "Personal taste, feeling, belief or advice with no factual premise anyone could check.",
            "prediction": "A forward-looking guess about the future.",
        }),
    "stake_link": Choice(
        instructions=("Set the answer's main point against speaker_profile.items: the speaker's own roles, businesses, investments, "
                      "sponsors, offices and political ties. Judge what the point does for them, not whether they are an expert."),
        criteria={
            "benefits": ("The point favours, protects or promotes something listed: it backs a company, holding, sector, product, sponsor, "
                         "office, party or policy the speaker is tied to, or weakens a rival of it."),
            "touches": "The point is about a company, sector, policy or topic that an item lists, but does not clearly help or hurt it.",
            "none": "Nothing listed bears on the point. Expertise in the field alone is not a tie.",
        }),
    "staged_pushback": Binary(
        instructions=("If the host's question is a challenge (a criticism, counter-view or pushback): does it read as a tee-up rather than a test: the criticism is named in "
                      "general terms (\"critics say...\") and the guest rebuts it with a ready, promotional answer, with no specific "
                      "figure or evidence demanded? Use the host_interests to see how the host is tied to the guest."),
        criteria="The pushback is generic and invites a rehearsed rebuttal the host does not press."),
    "self_serving_pivot": Binary(
        instructions="If the speaker reframed or sidestepped the question before answering: does the reframe steer toward something in speaker_profile.items?",
        criteria="The new framing leads to something the speaker sells, runs, holds, backs or serves."),
    "disclosed": Binary(
        instructions=("If the answer ties to something in speaker_profile.items: was that tie made known to the audience: "
                      "stated in the answer or the spoken words, said when the speaker was introduced, or in description_notes?"),
        criteria="The tie itself (the company, holding, product, office or sponsor) is stated or plainly known from what viewers are told."),
}

LEVELS = {"question_type": "LOW", "answer_type": "LOW", "claim_type": "LOW", "stake_link": "LOW", "stake_item": "LOW", "staged_pushback": "LOW",
          "self_serving_pivot": "LOW", "disclosed": "LOW"}

WORDS = {
    "factual": "Factual", "explanatory": "Explanatory", "experiential": "Experiential", "evaluative": "Evaluative",
    "speculative": "Speculative", "challenging": "Challenging", "direct": "Direct", "narrative": "Narrative", "structured": "Structured",
    "pivot": "Pivot", "evasive": "Evasive", "objective_fact": "Objective fact", "anchored_opinion": "Anchored opinion",
    "pure_opinion": "Pure opinion", "prediction": "Prediction", "grounded": "Grounded", "partly": "Partly grounded", "plausible": "Plausible",
    "contradicted": "Contradicted", "exempt": "Exempt", "ungrounded": "Ungrounded", "unclear": "Unclear",
}


# --- Inputs: each classifier sees only what it needs ---------------------------------------------------

def _clean(text: Any, n: int) -> str:
    return screen_text(str(text or "")[:n])[0]


def _question(ctx: dict[str, Any]) -> dict[str, Any]:
    spoken, plain = (ctx.get("question_spoken") or "").strip(), (ctx.get("question") or "").strip()
    out = {"question_as_asked": _clean(spoken or plain or "(not asked directly)", 400), "asked_by": ctx.get("asked_by") or "the host"}
    if plain and not spoken:
        out["note"] = ("This is the AI's plain-words rewrite of the question, which leaves out framing and voiced views. Don't infer a "
                       "challenge or a lead-in that isn't visible.")
    return out


def _answer(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"answer": _clean(ctx.get("statement"), 900), "spoken_words": _clean(ctx.get("context_quote"), 400)}


def _interests(person: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any]:
    """A speaker's incentive tags and the profile items about their businesses, holdings, products and sponsors."""
    keep = {"business", "financial_interest", "sponsor", "ownership", "political", "role", "affiliations"}
    items = [{"kind": it["kind"], "text": it["text"]} for it in numbered_profile(person or {}, ("role", "affiliations")) if it["kind"] in keep]
    return {"name": (person or {}).get("name") or (person or {}).get("label") or "the speaker",
            "incentive_tags": sorted(tags) or ["none found"], "items": items[:20] or "no profile found"}


def stake_items(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """The speaker's whole profile as numbered items for the stake comparison: each shown incentive tag with its reason and page,
    then roles, affiliations, businesses, holdings, sponsors, ownership and politics. No filter: whatever the profile holds."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, text: str, url: str = "", site: str = "") -> None:
        text = " ".join(str(text or "").split())
        key = text.lower()
        if text and key not in seen and len(items) < MAX_STAKE_ITEMS:
            seen.add(key)
            items.append({"n": str(len(items) + 1), "kind": kind, "text": _clean(text, 300), "url": url or "", "site": site or ""})

    for tag, inc in (ctx.get("speaker_incentives") or {}).items():
        if tag in HIDDEN_TAGS or not isinstance(inc, dict):
            continue
        add(tag, f"{tag.replace('_', ' ')}: {inc.get('reason') or ''}", inc.get("url", ""), inc.get("site", ""))
    for it in numbered_profile(ctx.get("speaker") or {}, ("role", "affiliations")):
        if it["kind"] in STAKE_KINDS:
            add(it["kind"], it["text"], it.get("url", ""), it.get("site", ""))
    return items


def stake_item_question(items: list[dict[str, Any]]) -> Choice:
    """Which numbered profile item the answer rests on: one Choice with an option per item (built per answer)."""
    criteria = {i["n"]: i["text"][:200] for i in items}  # no "none": stake_link has already said there is a tie
    return Choice(instructions=("Which one numbered item of speaker_profile.items does the answer's main point most directly favour or "
                                "concern? Pick the closest, even when none is exact."), criteria=criteria)


def speaker_tags(ctx: dict[str, Any]) -> set[str]:
    return {k for k in (ctx.get("speaker_incentives") or {})}


def host_tags(ctx: dict[str, Any]) -> set[str]:
    return {k for k in (ctx.get("host_incentives") or {})}


# --- The run --------------------------------------------------------------------------------------------

@dataclass
class Job:
    """One answer's tagging run: what the nodes read and what they found."""

    ctx: dict[str, Any]
    location: Optional[str]
    force: bool
    answers: dict[str, Any] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    items: list = field(default_factory=list)  # the speaker's profile items compared with the answer (stake_items)
    route: str = ""             # "exempt" (not researched), "no_points" (researched, nothing checkable) or "researched"
    research: Any = None
    assessment: Optional[assess.Assessment] = None  # the answer checked against its pages (agents/assess.py)

    async def ask(self, names: list[str], payload: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> None:
        """One classifier call answering `names` about `payload`. A failure leaves them out; a budget error is raised."""
        ec = get_context()
        try:
            res = await _classify(names, payload, extra)
        except Exception as e:
            if is_budget_error(e):
                raise
            self.failed += names
            ec.log("qa_tags", "tag_failed", "skipped", f"{','.join(names)}: {type(e).__name__}: {e}"[:200])
            log.warning("qa tag %s failed: %s: %s", names, type(e).__name__, e)
            return
        self.answers.update({n: res.answers[n] for n in names if n in res.answers})


async def _classify(names: list[str], payload: Any, extra: Optional[dict[str, Any]] = None) -> ClassifierResponse:
    """One classifier call over several questions (they share the input); `extra` holds questions built for this answer. A seam for tests."""
    from .llm_agents import tag_classifier

    level = "MEDIUM" if any(LEVELS[n] == "MEDIUM" for n in names) else "LOW"
    return await tag_classifier(get_context().settings, level).classify(input=payload, questions={n: (extra or {}).get(n) or QUESTIONS[n] for n in names})


def answer_call(job: Job) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """What the first classifier call asks about one answer: (question names, the input, the questions built for this answer)."""
    ctx = job.ctx
    q, a = _question(ctx), _answer(ctx)
    job.items = stake_items(ctx)
    names = ["answer_type", "claim_type"]
    payload: dict[str, Any] = {**q, **a}
    extra: dict[str, Any] = {}
    if job.items:  # every answer is set against the speaker's profile; no tag decides whether to ask
        names += ["stake_link", "stake_item", "self_serving_pivot", "disclosed"]
        extra["stake_item"] = stake_item_question(job.items)
        payload["speaker_profile"] = {"name": (ctx.get("speaker") or {}).get("name") or "the speaker",
                                      "items": [{"n": i["n"], "kind": i["kind"], "text": i["text"]} for i in job.items]}
        payload["description_notes"] = ctx.get("description_notes") or "none"
    if host_tags(ctx) & SOFT_HOST_TAGS:
        names.append("staged_pushback")
        payload["host_interests"] = _interests(ctx.get("host") or {}, host_tags(ctx))
    return names, payload, extra


def settle_route(job: Job) -> str:
    """After the first call: "exempt" (a pure opinion the classifier is sure of: no planner, no search) or "research". A failed call, or
    a pure opinion it is not sure of, is researched: skipping the search is the bigger mistake."""
    claim = job.answers.get("claim_type")
    if getattr(claim, "choice", None) == "pure_opinion" and float(claim.probabilities.get("pure_opinion", 0.0)) >= PURE_OPINION_SURE:
        job.route = "exempt"
        return "exempt"
    return "research"


async def ground(job: Job, on_label: Optional[Any] = None) -> None:
    """The second call, for a researched answer: the assessment (agents/assess.py). Each page row of the research gets its TLDR.
    `on_label` is awaited once it is in, so the verdict can be shown at once."""
    ctx, r = job.ctx, job.research
    points = [_clean(p["text"], 300) for p in r.points]
    claim = _label(job.answers.get("claim_type")) or "unknown"
    if r.all_pages:  # no page came back: nothing to compare, and nothing failed (decide labels it plausible)
        job.assessment = await assess.assess(ctx.get("question") or "", _answer(ctx)["answer"], points, claim, r.all_pages)
        if job.assessment is None:
            job.failed.append("grounding")
    if job.assessment is not None:
        for row, note in zip(r.pages, job.assessment.notes):
            row["tldr"], row["relevant"] = note["tldr"], note["relevant"]
    if on_label is not None:
        await on_label()


# --- Several answers in one classifier call ---------------------------------------------------------------

def _for_answer(q: Any, aid: str) -> Any:
    """The same question, about the answer with this id in a batch."""
    text = f"For the answer with id {aid} in the input's answers list: {q.instructions}"
    return Binary(instructions=text, criteria=q.criteria) if isinstance(q, Binary) else Choice(instructions=text, criteria=q.criteria)


def batches(jobs: list[Job], size: int) -> list[list[Job]]:
    """Answers that can share a call: the same speaker (so the same profile items), at most `size` to a call, in the order given."""
    groups: dict[tuple, list[Job]] = {}
    for j in jobs:
        sp = j.ctx.get("speaker") or {}
        groups.setdefault((sp.get("name") or sp.get("label") or "", tuple(i["text"] for i in stake_items(j.ctx))), []).append(j)
    size = max(1, size)
    return [g[i:i + size] for g in groups.values() for i in range(0, len(g), size)]


async def _classify_many(payload: Any, questions: dict[str, Any], level: str = "LOW") -> ClassifierResponse:
    """One classifier call over the questions of several answers. A seam for tests."""
    from .llm_agents import tag_classifier

    return await tag_classifier(get_context().settings, level).classify(input=payload, questions=questions)


async def classify_answers(jobs: list[Job]) -> None:
    """The first call for several answers by one speaker, in ONE classifier call: each answer's questions are named by its id. A failed
    call is made again one answer at a time, so one bad answer doesn't cost the others their tags; a budget error is raised."""
    ec = get_context()
    questions: dict[str, Any] = {}
    answers_in: list[dict[str, Any]] = []
    shared: dict[str, Any] = {}
    plan: list[tuple[Job, str, list[str]]] = []
    for n, job in enumerate(jobs, 1):
        names, payload, extra = answer_call(job)
        aid = f"a{n}"
        answers_in.append({"id": aid, **{k: payload[k] for k in ("question_as_asked", "asked_by", "note", "answer", "spoken_words") if k in payload}})
        shared = {k: v for k, v in payload.items() if k not in ("question_as_asked", "asked_by", "note", "answer", "spoken_words")}
        for name in names:
            questions[f"{aid}_{name}"] = _for_answer((extra or {}).get(name) or QUESTIONS[name], aid)
        plan.append((job, aid, names))
    try:
        res = await _classify_many({"answers": answers_in, **shared}, questions)
    except Exception as e:
        if is_budget_error(e):
            raise
        if len(jobs) > 1:
            log.warning("batched answer tags failed (%d answers), retrying one at a time: %s: %s", len(jobs), type(e).__name__, e)
            for job in jobs:
                await classify_answers([job])
            return
        job, _, names = plan[0]
        job.failed += names
        ec.log("qa_tags", "tag_failed", "skipped", f"{','.join(names)}: {type(e).__name__}: {e}"[:200])
        return
    for job, aid, names in plan:
        job.answers.update({n: res.answers[f"{aid}_{n}"] for n in names if f"{aid}_{n}" in res.answers})


async def run_job(job: Job) -> None:
    """One answer, start to finish: classify, then research and assess unless it is a pure opinion. Raises what the research raises
    (ResearchUnavailable, budget errors)."""
    from .research import research_answer

    job.items = stake_items(job.ctx)
    names, payload, extra = answer_call(job)
    await job.ask(names, payload, extra)
    if settle_route(job) == "exempt":
        return
    r = await research_answer(job.ctx, job.location, force=job.force)
    if r is None:
        job.route = "no_points"
        return
    job.route, job.research = "researched", r
    await ground(job)


# --- Decisions in code ----------------------------------------------------------------------------------

def _label(answer: Any) -> Optional[str]:
    return getattr(answer, "choice", None)


def _yes(answer: Any) -> bool:
    return answer is not None and float(getattr(answer, "probability", 0.0)) >= YES


def _choice(answer: Any, valid: tuple[str, ...], fallback: str) -> Optional[dict[str, Any]]:
    if answer is None:
        return None
    label = getattr(answer, "choice", None)
    if label not in valid:
        return {"type": fallback, "p": 0.0}
    p = round(float(answer.probabilities.get(label, 0.0)), 2)
    return {"type": label if p >= SURE else fallback, "p": p}


def _p(answer: Any) -> float:
    return round(float(getattr(answer, "probability", 0.0)), 2)


def _stake(job: Job) -> Optional[dict[str, Any]]:
    """The profile item the answer benefits or touches, when the classifiers are sure of both the link and the item."""
    link, item = job.answers.get("stake_link"), job.answers.get("stake_item")
    if link is None or item is None or getattr(link, "choice", None) not in ("benefits", "touches"):
        return None
    p_link = float(link.probabilities.get(link.choice, 0.0))
    picked = next((i for i in job.items if i["n"] == getattr(item, "choice", None)), None)
    p_item = float(item.probabilities.get(item.choice, 0.0)) if picked else 0.0
    if not picked or p_link < STAKE_SURE or p_item < ITEM_SURE:
        return None
    return {"link": link.choice, "p": round(p_link, 2), "item": {k: picked[k] for k in ("kind", "text", "url", "site") if picked.get(k)}}


def decide(job: Job) -> dict[str, Any]:
    """The classifiers' answers turned into claims.qa_tags, with the evidence and skepticism rules applied."""
    ans, ctx, r = job.answers, job.ctx, job.research
    tags: dict[str, Any] = {"version": 4}
    at = _choice(ans.get("answer_type"), ATYPES, "unclear")
    if at:
        tags["answer"] = at
    claim_ans = ans.get("claim_type")
    claim = {"type": claim_ans.choice, "p": round(float(claim_ans.probabilities.get(claim_ans.choice, 0.0)), 2)} if claim_ans else None
    if claim:
        tags["claim"] = claim

    pages = r.all_pages if r is not None else []
    a = job.assessment
    if job.route == "exempt":
        grounding: Optional[dict[str, Any]] = {"label": "exempt"}
    elif job.route == "no_points":
        grounding = {"label": "exempt" if (claim or {}).get("type") in ("prediction", "pure_opinion") else "plausible"}
    elif a is not None:
        grounding = {"label": a.label}
    elif job.route == "researched" and not pages:
        grounding = {"label": "plausible"}  # the searches returned no page: nothing settles it
    else:
        grounding = None

    flags: list[str] = []
    conflict: dict[str, Any] = {}
    stake = _stake(job)
    self_serving = bool(stake and stake["link"] == "benefits")
    pivot = _yes(ans.get("self_serving_pivot")) and (at or {}).get("type") == "pivot"
    disclosure = ("disclosed" if _yes(ans["disclosed"]) else "undisclosed") if "disclosed" in ans else None
    if self_serving or pivot:
        conflict["kind"] = "self_report" if self_serving else "self_serving_pivot"
        if disclosure:
            conflict["disclosure"] = disclosure
    if stake:
        if disclosure:
            stake["disclosure"] = disclosure
        tags["stake"] = stake
    if job.items:
        tags["profile_checked"] = len(job.items)
    if grounding and self_serving:
        if grounding["label"] in ("plausible", "partly", "grounded") and not (a is not None and a.independent_support):
            grounding = {**grounding, "label": "ungrounded", "was": grounding["label"]}  # Rule 1: no independent page backs it
    if a is not None and a.missing_context and grounding and grounding["label"] == "grounded" and speaker_tags(ctx) & CONTEXT_TAGS:
        flags.append("missing_context")
    if _yes(ans.get("staged_pushback")):
        flags.append("staged_pushback")  # shown only when the question was challenging (web/lib/indicators.ts)
    if pivot:
        flags.append("self_serving_pivot")

    if grounding:
        if a is not None and grounding["label"] != "exempt":
            tags["grounding"] = {**grounding, "evidence": assess.evidence_of(pages), "basis": assess.basis_of(a, pages), "overview": a.overview,
                                 "claims": a.claims}
            if a.missing_context and "missing_context" in flags:
                tags["grounding"]["missing_context"] = a.missing_context
            if a.contradiction and grounding["label"] == "contradicted":
                tags["grounding"]["contradiction"] = a.contradiction
            tags["match"] = a.match
        else:
            basis = build_correctness("opinion" if grounding["label"] == "exempt" else grounding["label"], pages)
            tags["grounding"] = {**grounding, "evidence": basis["evidence"], "basis": basis["basis"]}
    if flags:
        tags["flags"] = flags
    if conflict:
        tags["conflict"] = conflict
    tags["chain"] = chain(tags)
    if job.failed:
        tags["failed"] = sorted(set(job.failed))
    return tags


def chain(tags: dict[str, Any]) -> str:
    """'Structured A → Anchored opinion → Plausible': the answer's part of the tagging string (the web puts the question in front)."""
    parts = []
    if tags.get("question"):
        parts.append(f"{WORDS[tags['question']['type']]} Q")
    if tags.get("answer"):
        parts.append(f"{WORDS[tags['answer']['type']]} A")
    if tags.get("claim"):
        parts.append(WORDS[tags["claim"]["type"]])
    g = tags.get("grounding")
    if g:
        extra = [x for x in ("missing context" if "missing_context" in tags.get("flags", []) else "",
                             {"self_report": "self-report", "self_serving_pivot": "self-serving pivot"}.get((tags.get("conflict") or {}).get("kind"), ""),
                             (tags.get("conflict") or {}).get("disclosure", "")) if x]
        parts.append(WORDS[g["label"]] + (f" ({', '.join(extra)})" if extra else ""))
    return " → ".join(parts)


# --- Entry point ------------------------------------------------------------------------------------------

@dataclass
class Tagged:
    tags: Optional[dict[str, Any]]
    research: Any  # research.Research, or None when nothing was searched


async def tag_answer(ctx: dict[str, Any], location: Optional[str], force: bool = False) -> Tagged:
    """Tags one answer and researches it when its claim type calls for it. Raises ResearchUnavailable when every search failed and
    budget errors; a failing classifier only leaves its tag out."""
    ec = get_context()
    s = ec.settings
    job = Job(ctx=ctx, location=location, force=force)
    if not s.tag_answers or ec.budget.spent_usd + s.tag_cost_estimate_usd > ec.budget.cap_usd:
        from .research import research_answer  # no tagging: the plain research, as before

        r = await research_answer(ctx, location, force=force)
        return Tagged(None, r)
    await run_job(job)
    tags = decide(job)
    if job.research is not None:
        job.research.match = (tags.get("match") or {}).get("label") or job.research.match
    return Tagged(tags, job.research)
