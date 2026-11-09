"""How the pages contradict an answer: one more call, made only for an answer the grounding classifier tagged contradicted.

The grounding classifier (agents/qa_tags.py) only chooses a label, so a reader saw "Contradicted" and the first page's title. This call
reads the same answer, points and page excerpts and writes the part a reader needs:

  said          the specific claim of the answer the page contradicts, with its figures
  sources_say   what that page says about the same thing instead
  difference    one plain sentence: how they differ
  quote         a fragment of that page's excerpt that shows it

It describes the difference and never judges the speaker. Code then checks what the model returned: the page number must be one of
the pages shown (else nothing is saved), and the quote must really be on that page (else the quote is dropped, the rest is kept). The
page's site and link come from the page itself, never from the model. A failed call leaves the answer contradicted with no explanation
(the web falls back to the page's title); a budget error is never swallowed.

Saved inside claims.qa_tags.grounding.contradiction (see GroundingContradiction in web/lib/types.ts).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text, wrap_untrusted
from ..schemas import ContradictionOut

log = logging.getLogger("claimcheck")

MAX_PAGES = 30
PAGE_TEXT_CHARS = 1200
SAID_CHARS, SAYS_CHARS, DIFFERENCE_CHARS, QUOTE_CHARS = 260, 320, 260, 240
MIN_FRAGMENT = 8  # a quote's pieces (split at ellipses) shorter than this prove nothing


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
    """The pages, numbered, as untrusted data (instruction-like lines removed): the same pages and excerpts the grounding classifier saw."""
    return "\n\n".join(
        wrap_untrusted(f"PAGE {n}", f"Title: {_clean(pg.get('title'), 160)}\nSite: {pg.get('site', '')}\nDate: {pg.get('date') or 'unknown'}\n"
                                    f"Excerpt: {_clean(pg.get('text'), PAGE_TEXT_CHARS)}")
        for n, pg in enumerate(pages, 1))


async def _generate(state: dict[str, Any]) -> Optional[ContradictionOut]:
    """The call itself. A seam for tests."""
    from .llm_agents import contradiction_agent
    from .research import _run_agent

    ec = get_context()
    return await _run_agent(contradiction_agent(ec.settings, name=f"contradiction_{uuid.uuid4().hex[:6]}"), state, "contradiction", ContradictionOut)


def check(out: Optional[ContradictionOut], pages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """What the model returned, kept only if it points at a real page and says all three things; the quote only if it is on that page."""
    if out is None or not 1 <= out.page <= len(pages):
        return None
    pg = pages[out.page - 1]
    said, says, diff = _clean(out.said, SAID_CHARS), _clean(out.sources_say, SAYS_CHARS), _clean(out.difference, DIFFERENCE_CHARS)
    if not (said and says and diff):
        return None
    result: dict[str, Any] = {"said": said, "sources_say": says, "difference": diff, "site": pg.get("site", ""), "url": pg.get("url", ""),
                              "title": _clean(pg.get("title"), 160)}
    quote = _clean(out.quote, QUOTE_CHARS)
    if quote and on_page(quote, _clean(pg.get("text"), PAGE_TEXT_CHARS)):
        result["quote"] = quote
    return result


async def explain(question: str, answer: str, points: list[str], pages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The explanation for one contradicted answer, or None (no pages, a failed call, or an answer that doesn't hold up)."""
    shown = pages[:MAX_PAGES]
    if not shown:
        return None
    state = {"question": _clean(question, 400) or "(not asked directly)", "answer": _clean(answer, 900),
             "points": " | ".join(_clean(p, 300) for p in points) or "(none)", "pages": pages_text(shown)}
    try:
        out = await _generate(state)
    except Exception as e:
        if is_budget_error(e):
            raise
        get_context().log("qa_tags", "contradiction_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        log.warning("contradiction explainer failed: %s: %s", type(e).__name__, e)
        return None
    return check(out, shown)
