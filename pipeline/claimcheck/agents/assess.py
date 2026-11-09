"""The answer set against its pages: one call per researched answer, with a reason for every verdict.

Replaces the grounding classifier, the match question, the missing-context question and the contradiction explainer. The call writes,
in this order (the order is the method):

  pages      a line (TLDR) for every page: what it says that bears on the answer's subject, with its own figures
  overview   what the pages say together, and where they differ from each other (written without reference to the answer)
  claims     the answer's 1-4 checkable claims, each compared with the pages: supported / partly / contradicted / not_found, the page that
             decides it, what that page says, a quote, and a reason ("the answer says X; the page says Y")

Code then checks what came back and decides the label; the model never picks it:
  - a page number must be one of the pages shown, else the claim is not_found; the page's site and link come from the page itself
  - a quote must really be on that page (ignoring case and spacing), else it is dropped
  - a "contradicted" claim needs a quote that is on the page, else it is recorded as "partly" (an incompatible figure that cannot be
    quoted is not enough to call it wrong)
  - label: contradicted if any claim is; grounded if every claim is supported; partly if some claim is supported or partly and none is
    contradicted; plausible when no page settles any claim
  - match: the share of pages that speak to a claim (high >= half, medium some, low none)
The self-report rule (agents/qa_tags.py) then uses `independent_support`: whether a page from outside the speaker's own organisation and
the episode supports or partly supports a claim.

A failed call leaves the answer without a grounding tag (it can be retried); a budget error is never swallowed.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text, wrap_untrusted
from ..schemas import AssessOut
from .correctness import evidence_level

log = logging.getLogger("claimcheck")

MAX_PAGES = 30
PAGE_TEXT_CHARS = 1200
MAX_CLAIMS = 4
TLDR_CHARS, OVERVIEW_CHARS, CLAIM_CHARS, SAYS_CHARS, REASON_CHARS, QUOTE_CHARS, CONTEXT_CHARS = 260, 420, 240, 260, 420, 240, 280
MIN_FRAGMENT = 8  # a quote's pieces (split at ellipses) shorter than this prove nothing
MAX_BASIS = 3
VERDICTS = ("supported", "partly", "contradicted", "not_found")
ORIGIN = {"independent": "independent site", "own_organisation": "the speaker's own organisation", "same_episode": "this episode itself"}


def _clean(text: Any, n: int) -> str:
    return " ".join(screen_text(str(text or ""))[0].split())[:n]


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"').split())


def on_page(quote: str, text: str) -> bool:
    """Whether the quote really is on the page: every piece of it (it may use ellipses) appears in the excerpt, ignoring case and spacing."""
    page = _norm(text)
    pieces = [_norm(p).strip(" \"'.,;:") for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote or "")]
    pieces = [p for p in pieces if p]
    return bool(pieces) and all(len(p) >= MIN_FRAGMENT and p in page for p in pieces)


def pages_text(pages: list[dict[str, Any]]) -> str:
    """The pages, numbered, as untrusted data (instruction-like lines removed): where each comes from, then its search excerpt."""
    return "\n\n".join(
        wrap_untrusted(f"PAGE {n}", f"Title: {_clean(pg.get('title'), 160)}\nSite: {pg.get('site', '')} ({ORIGIN.get(pg.get('independence') or 'independent', 'independent site')})\n"
                                    f"Date: {pg.get('date') or 'unknown'}\nExcerpt: {_clean(pg.get('text'), PAGE_TEXT_CHARS)}")
        for n, pg in enumerate(pages, 1))


@dataclass
class Assessment:
    label: str                                   # contradicted | grounded | partly | plausible (before the self-report rule)
    claims: list[dict[str, Any]]                 # verdict, reason and the page, per claim
    overview: str
    notes: list[dict[str, Any]]                  # per page, index-aligned with the pages shown: {"tldr", "relevant"}
    independent_support: bool                    # an independent page supports or partly supports a claim
    match: dict[str, Any]                        # {"label": high | medium | low, "p": share of pages that speak to a claim}
    missing_context: str = ""
    contradiction: Optional[dict[str, Any]] = field(default=None)   # the first contradicted claim, in the shape the page shows


def label_of(claims: list[dict[str, Any]]) -> str:
    verdicts = [c["verdict"] for c in claims]
    if "contradicted" in verdicts:
        return "contradicted"
    if verdicts and all(v == "supported" for v in verdicts):
        return "grounded"
    if any(v in ("supported", "partly") for v in verdicts):
        return "partly"
    return "plausible"


def check(out: Optional[AssessOut], pages: list[dict[str, Any]]) -> Optional[Assessment]:
    """What the model returned, kept only where it holds up (see the module docstring). None when there is nothing usable."""
    if out is None or not pages:
        return None
    by_page = {n.page: n for n in out.pages}
    notes = [{"tldr": _clean(by_page[i].tldr, TLDR_CHARS) if i in by_page else "", "relevant": bool(by_page[i].relevant) if i in by_page else False}
             for i in range(1, len(pages) + 1)]
    claims: list[dict[str, Any]] = []
    for f in out.claims[:MAX_CLAIMS]:
        text, reason = _clean(f.claim, CLAIM_CHARS), _clean(f.reason, REASON_CHARS)
        if not text or not reason:
            continue
        verdict = f.verdict if f.verdict in VERDICTS else "not_found"
        page = f.page if 1 <= f.page <= len(pages) else 0
        if not page and verdict != "not_found":
            verdict = "not_found"  # a verdict that names no real page rests on nothing
        entry: dict[str, Any] = {"claim": text, "verdict": verdict, "reason": reason}
        if page:
            pg = pages[page - 1]
            entry.update({"site": pg.get("site", ""), "url": pg.get("url", ""), "title": _clean(pg.get("title"), 160),
                          "independence": pg.get("independence") or "independent", "page_says": _clean(f.page_says, SAYS_CHARS)})
            quote = _clean(f.quote, QUOTE_CHARS)
            if quote and on_page(quote, _clean(pg.get("text"), PAGE_TEXT_CHARS)):
                entry["quote"] = quote
            if verdict == "contradicted" and "quote" not in entry:
                entry["verdict"] = "partly"
                entry["reason"] = _clean(f"{reason} (No exact line on the page could be quoted for this, so it is not treated as a contradiction.)", REASON_CHARS + 90)
        claims.append(entry)
    if not claims:
        return None
    relevant = sum(1 for n in notes if n["relevant"])
    share = relevant / len(pages)
    match = {"label": "high" if share >= 0.5 else "medium" if relevant else "low", "p": round(share, 2)}
    contradicted = next((c for c in claims if c["verdict"] == "contradicted"), None)
    contradiction = None
    if contradicted:
        contradiction = {"said": contradicted["claim"], "sources_say": contradicted.get("page_says") or "", "difference": contradicted["reason"],
                         "site": contradicted["site"], "url": contradicted["url"], "title": contradicted.get("title", ""), "quote": contradicted["quote"]}
    independent = any(c["verdict"] in ("supported", "partly") and c.get("independence") == "independent" for c in claims)
    return Assessment(label=label_of(claims), claims=claims, overview=_clean(out.overview, OVERVIEW_CHARS), notes=notes,
                      independent_support=independent, match=match, missing_context=_clean(out.missing_context, CONTEXT_CHARS),
                      contradiction=contradiction)


def basis_of(a: Assessment, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pages the label rests on: those that decide a claim, then the most relevant others, at most MAX_BASIS."""
    order: list[int] = []
    urls = {pg["url"]: i for i, pg in enumerate(pages)}
    for c in a.claims:
        i = urls.get(c.get("url", ""))
        if i is not None and i not in order:
            order.append(i)
    order += [i for i, n in enumerate(a.notes) if n["relevant"] and i not in order]
    out = []
    for i in order[:MAX_BASIS]:
        pg, quote = pages[i], next((c.get("quote") for c in a.claims if c.get("url") == pages[i]["url"] and c.get("quote")), "")
        out.append({"site": pg["site"], "url": pg["url"], "relation": "page", "finding": a.notes[i]["tldr"] or pg.get("title", ""),
                    "quote": quote or " ".join((pg.get("text") or "").split())[:240]})
    return out


def evidence_of(pages: list[dict[str, Any]]) -> str:
    return evidence_level(pages)


# --- The call -------------------------------------------------------------------------------------------

async def _generate(state: dict[str, Any]) -> Optional[AssessOut]:
    """The call itself. A seam for tests."""
    from .llm_agents import assess_agent
    from .research import _run_agent

    ec = get_context()
    return await _run_agent(assess_agent(ec.settings, name=f"assess_{uuid.uuid4().hex[:6]}"), state, "assess", AssessOut)


async def assess(question: str, answer: str, points: list[str], claim_type: str, pages: list[dict[str, Any]]) -> Optional[Assessment]:
    """The assessment of one researched answer, or None (no pages, a failed call, or nothing usable in what came back)."""
    shown = pages[:MAX_PAGES]
    if not shown:
        return None
    state = {"question": _clean(question, 400) or "(not asked directly)", "answer": _clean(answer, 900), "claim_type": claim_type or "unknown",
             "points": " | ".join(_clean(p, 300) for p in points) or "(none)", "pages": pages_text(shown)}
    try:
        out = await _generate(state)
    except Exception as e:
        if is_budget_error(e):
            raise
        get_context().log("qa_tags", "assess_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        log.warning("assessment failed: %s: %s", type(e).__name__, e)
        return None
    return check(out, shown)
