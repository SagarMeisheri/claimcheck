"""Answer tags: one ADK classifier call per tag, after an answer's sources are found.

Each tag is its own LlmClassifier call with one Choice or Binary question, shown only what that tag needs, at its own thinking level.
All of them run at the same time, so a tag can't colour another and one failing doesn't cost the rest.

  tag           answers                                            sees                                          thinking
  support       supported / partly / contradicted / unverified /   the question, the answer, its points and      medium
                opinion: what the pages show about the answer      every page's search excerpt (up to 30)
  match         high / medium / low: how directly the pages        the answer, its points and the excerpts       low
                address the answer's own points
  bias          balanced / leans / one_sided / cant_tell           the question, the answer, both profiles and   medium
                                                                   the first 10 excerpts
  stake         yes / no: the speaker or their organisation has    the answer and both profiles                  low
                an interest in the outcome, or the answer
                promotes their own company, product or channel
  question_type open / closed / leading / softball / challenging   the host's own words, who asks whom (the      low
                                                                   profiles), never the answer

Every page the searches returned is shown as its search excerpt, all treated alike (no page is fetched). Code keeps the tags honest:
"supported", "partly" and "contradicted" need at least one page, "contradicted" needs more confidence than the rest, a label the
classifier is unsure of falls back to the cautious one, and match can't contradict support. A tag whose call failed is left out.
The tags go on the research as research["tags"], and support is also saved as research["correctness"] (with the pages it was shown),
match as the answer's source match, and the two question tags go on the answer as claims.question_analysis =
{"type", "p", "spoken"} (spoken false: tagged from the AI's plain-words version of the question).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from google.adk.labs.classifiers import Binary, Choice

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text
from .correctness import build_correctness
from ..profiles import SHOW_KEYS, SPEAKER_KEYS, profile_text

log = logging.getLogger("claimcheck")

SUPPORT = ("supported", "partly", "contradicted", "unverified", "opinion")
MATCH = ("high", "medium", "low")
BIAS = ("balanced", "leans", "one_sided", "cant_tell")
QTYPES = ("open", "closed", "leading", "softball", "challenging")
PAGE_TEXT_CHARS = 1200  # per page shown to the classifier
MAX_PAGES_SHOWN = 30  # pages shown to the support and match classifiers, in the order the searches returned them (all are still saved)
BIAS_PAGES = 10  # pages the bias classifier sees, at BIAS_PAGE_CHARS each
BIAS_PAGE_CHARS = 500
SURE = 0.45  # a Choice whose top probability is below this falls back to the cautious label
YES = 0.6  # a Binary is "yes" at or above this
CONTRADICT_SURE = 0.6  # "contradicted" is the strongest support label: below this confidence it is shown as "partly"

QUESTIONS = {
    "support": Choice(
        instructions=("What do the pages show about the answer's main points? Judge only from the pages listed, all treated alike: don't "
                      "favour or discount a page for the kind of site it is. Old pages say little about a present-day point."),
        criteria={
            "supported": "Pages say the same as the answer's main points (the same reading, figure or outcome), and none contradicts them.",
            "partly": "Some main points are backed by pages and others are not, or the pages disagree with each other.",
            "contradicted": "Pages give a different figure, outcome or account for the main points, and none backs them.",
            "unverified": "No page speaks to the main points, or the pages found are about something else.",
            "opinion": "A value judgement or preference with no factual premise a source could address.",
        }),
    "match": Choice(
        instructions="How directly do the pages found address the answer's own points? This is relevance only; it says nothing about whether they agree.",
        criteria={
            "high": "Most pages speak to the answer's specific points.",
            "medium": "Some pages speak to the specific points; others are about the wider topic.",
            "low": "The pages are about the wider topic or something else, not the answer's points.",
        }),
    "bias": Choice(
        instructions=("Does the answer present its subject one-sidedly? Use the answer, the question, the speaker's and the show's profiles "
                      "and the pages. A leaning in a profile counts only as the profile states it."),
        criteria={
            "balanced": "It weighs other views, or is plain description, with little slant.",
            "leans": "Its wording or choice of facts favours one side, but it doesn't dismiss the other.",
            "one_sided": "It presents a contested matter as settled, or dismisses other views outright, with absolute or loaded wording.",
            "cant_tell": "Too little to say.",
        }),
    "stake": Binary(
        instructions=("Does the speaker, or an organisation they lead, work for or fund, have a financial, professional or political interest in the "
                      "outcome or the view the answer voices, or does the answer promote their own company, product, fund, book, course or channel?"),
        criteria="The speaker profile, the show profile or the answer itself shows such a role, interest or promotion. Not mere agreement with a view."),
    "question_type": Choice(
        instructions=("How was the host's question put? Judge by the question_as_asked words only, not by the answer. Use the profiles to see "
                      "who is asking whom (for example a host who works with the guest's company)."),
        criteria={
            "open": "Invites the guest to explain in their own terms and presumes no answer (\"How did you decide...?\").",
            "closed": "A yes/no or single-fact question that presumes no answer (\"Did you raise a seed round?\").",
            "leading": "The wording presumes or steers toward the answer wanted (\"Don't you think...\", \"Isn't it true that...\"), or states a view and asks the guest to agree.",
            "softball": "Invites praise or an easy self-description at no cost to the guest (\"What makes your product so special?\").",
            "challenging": "Puts a criticism, a counter-view, a contradiction or a demand for evidence to the guest (\"Critics say...\", \"What data supports that?\").",
        }),
}


LEVELS = {"support": "MEDIUM", "match": "LOW", "bias": "MEDIUM", "stake": "LOW", "question_type": "LOW"}


def _clean(text: Any, n: int) -> str:
    return screen_text((text or "")[:n])[0]


def _pages(research: Any, limit: int, chars: int) -> Any:
    """The pages' search excerpts, all alike. Text is screened for instruction-like lines."""
    pages = [{"site": pg["site"], "title": _clean(pg.get("title"), 160), "date": pg.get("date") or "unknown", "text": _clean(pg.get("text"), chars)}
             for pg in research.all_pages[:limit]]
    return pages or "the searches returned no pages"


def _question(ctx: dict[str, Any]) -> dict[str, Any]:
    """The question as the host asked it (the AI's plain-words rewrite for older videos, with a note), and who asked."""
    spoken, plain = (ctx.get("question_spoken") or "").strip(), (ctx.get("question") or "").strip()
    return {"question_as_asked": _clean(spoken or plain or "(not asked directly)", 400),
            **({"note": "This is the AI's plain-words rewrite of the question, which leaves out framing, praise and loaded wording. Don't infer "
                        "leading or softball wording that isn't visible; use open or closed unless it is plain."} if plain and not spoken else {}),
            "asked_by": ctx.get("asked_by") or "the host"}


def _profiles(ctx: dict[str, Any]) -> dict[str, str]:
    return {"speaker_profile": profile_text(ctx.get("speaker") or {}, SPEAKER_KEYS) or "no profile found",
            "show_profile": profile_text(ctx.get("creator") or {}, SHOW_KEYS) or "no profile found"}


def tag_inputs(ctx: dict[str, Any], research: Any) -> dict[str, dict[str, Any]]:
    """What each tag's classifier sees: only what it needs, so a tag can't lean on something that isn't its business."""
    answer = {"answer": _clean(ctx.get("statement", ""), 900), "answer_type": ctx.get("statement_type") or ""}
    points = [{"point": i, "text": _clean(p["text"], 300)} for i, p in enumerate(research.points, 1)]
    q, prof = _question(ctx), _profiles(ctx)
    pages = _pages(research, MAX_PAGES_SHOWN, PAGE_TEXT_CHARS)
    return {
        "support": {"question_as_asked": q["question_as_asked"], **answer, "points": points, "pages": pages},
        "match": {**answer, "points": points, "pages": pages},
        "bias": {"question_as_asked": q["question_as_asked"], **answer, **prof, "pages": _pages(research, BIAS_PAGES, BIAS_PAGE_CHARS)},
        "stake": {**answer, **prof},
        "question_type": {**q, **prof},   # the host's words and who is asking whom; never the answer
    }


def _choice(answers: dict[str, Any], name: str, valid: tuple[str, ...], fallback: str) -> dict[str, Any]:
    a = answers.get(name)
    label = getattr(a, "choice", None)
    if label not in valid:
        return {"label": fallback, "p": 0.0}
    p = round(float(a.probabilities.get(label, 0.0)), 2)
    return {"label": label if p >= SURE else fallback, "p": p}


def _binary(answers: dict[str, Any], name: str) -> dict[str, Any]:
    p = round(float(getattr(answers.get(name), "probability", 0.0)), 2)
    return {"yes": p >= YES, "p": p}


def decide(answers: dict[str, Any], research: Any) -> dict[str, Any]:
    """The classifiers' answers turned into tags, with the evidence rules applied. A tag whose call failed is absent."""
    tags: dict[str, Any] = {}
    if "support" in answers:
        support = _choice(answers, "support", SUPPORT, "unverified")
        if support["label"] == "contradicted" and support["p"] < CONTRADICT_SURE:
            support = {"label": "partly", "p": support["p"]}
        if support["label"] in ("supported", "partly", "contradicted") and not research.all_pages:
            support = {"label": "unverified", "p": support["p"]}  # no page at all: nothing to rest it on
        tags["support"] = support
    if "match" in answers:
        match = _choice(answers, "match", MATCH, "medium")
        label = (tags.get("support") or {}).get("label")
        if label == "unverified" and match["label"] == "high":
            match["label"] = "medium"  # pages that settle nothing about the points can't be a direct match
        if label in ("supported", "contradicted") and match["label"] == "low":
            match["label"] = "medium"  # a page that backs or contradicts a point speaks to it
        tags["match"] = match
    if "bias" in answers:
        tags["bias"] = _choice(answers, "bias", BIAS, "cant_tell")
    if "stake" in answers:
        tags["stake"] = _binary(answers, "stake")
    if "question_type" in answers:
        tags["question_type"] = _choice(answers, "question_type", QTYPES, "unclear")
    return tags


def question_analysis(ctx: dict[str, Any], tags: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The question tags as saved on the answer, or None when nobody asked the question (the AI wrote it for an unprompted passage)."""
    if ctx.get("question_kind") == "implied" or not (ctx.get("question") or ctx.get("question_spoken")) or "question_type" not in tags:
        return None
    return {"type": tags["question_type"]["label"], "p": tags["question_type"]["p"],
            "spoken": bool((ctx.get("question_spoken") or "").strip())}


async def _classify(name: str, payload: dict[str, Any]) -> Any:
    """One tag's classifier call. A seam for tests."""
    from .llm_agents import tag_classifier

    return await tag_classifier(get_context().settings, LEVELS[name]).classify(input=payload, questions={name: QUESTIONS[name]})


async def tag_answer(ctx: dict[str, Any], research: Any) -> None:
    """Tags one researched answer in place: every tag is its own classifier call, all at the same time. Never raises, except for the budget."""
    ec = get_context()
    s = ec.settings
    if not s.tag_answers or ec.budget.spent_usd + s.tag_cost_estimate_usd > ec.budget.cap_usd:
        return
    inputs = tag_inputs(ctx, research)
    names = list(inputs)
    results = await asyncio.gather(*(_classify(n, inputs[n]) for n in names), return_exceptions=True)
    answers: dict[str, Any] = {}
    for name, res in zip(names, results):
        if isinstance(res, BaseException):
            if is_budget_error(res):
                raise res
            ec.log("tags", "tag_failed", "skipped", f"{name}: {type(res).__name__}: {res}"[:200])
            log.warning("tag %s failed: %s: %s", name, type(res).__name__, res)
        elif name in res.answers:
            answers[name] = res.answers[name]
    if not answers:
        return
    tags = decide(answers, research)
    research.tags = tags
    if "support" in tags:
        research.correctness = build_correctness(tags["support"]["label"], research.all_pages)
    if "match" in tags:
        research.match = tags["match"]["label"]
    research.question_analysis = question_analysis(ctx, tags)
