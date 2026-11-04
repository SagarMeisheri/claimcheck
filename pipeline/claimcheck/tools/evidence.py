"""Sources for one claim: Parallel web searches on the claim's own words.

related search   the claim's words; the objective says who said it, on which show, while discussing what, so the
                 search engine can tell which pages are about this statement
counter search   (data / contested statements, agents/sources.py) the same words plus a second query, with an
                 objective asking for official figures, different figures or other perspectives, aimed away from the
                 speaker's and show's known positions. Links the related search already found are left out.

Whatever Parallel returns is used, in Parallel's order (most relevant first): title, link, date and the excerpt
Parallel took from the page. No model reads the pages and nothing is filtered afterwards except duplicates. The only
rule is in the request itself: social media and video sites are excluded (policy.yaml sources.blocklist), because a
post is not a source.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from ..policy import blocklist, source_tier
from ..schemas import Source

_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")   # [text](url) -> text
_MD_MARKS = re.compile(r"[#*_`>]+")              # emphasis, headings, code, quotes: dropped
_WS = re.compile(r"[\s|]+")                       # whitespace and table pipes: one space
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?)])")


def clean_excerpt(text: str, limit: int) -> str:
    """Parallel's excerpts are page text with some markdown; make one readable line of at most `limit` characters."""
    t = _MD_LINK.sub(r"\1", text or "")
    t = _SPACE_BEFORE_PUNCT.sub(r"\1", _WS.sub(" ", _MD_MARKS.sub("", t))).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut + "…"


_SEGMENT = re.compile(r"(?<=[.!?])\s+|\s*\n+\s*|\s+\.\.\.\s+|\s+…\s+")
_WORD = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*")
_STOP = set("a an and are as at be by for from has have in is it its of on or that the this to was were will with".split())


# PDF titles sometimes carry LaTeX spacing at either end: "-1cmMacroeconomic Implications ...?1cm"
_TEX_SPACING = re.compile(r"^\s*-?\d+(?:\.\d+)?(?:cm|mm|pt|em)|-?\d+(?:\.\d+)?(?:cm|mm|pt|em)\s*$")


def clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", _TEX_SPACING.sub("", title)).strip()[:300]


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and (len(w) > 2 or w[0].isdigit())}


def best_excerpt(excerpts: list[str], claim_text: str, limit: int) -> str:
    """The part of the page text that shares the most words and numbers with the claim, so the excerpt shows the
    relevant passage rather than the page's menu. Plain word overlap (numbers count double); no model. Always returns
    something when there is text: this picks a passage, it never hides a source."""
    wanted = _terms(claim_text)
    segments = [seg for e in excerpts for seg in _SEGMENT.split(clean_excerpt(e, 100_000).replace(" …", ".")) if len(seg) > 20]
    if not segments:
        return clean_excerpt(excerpts[0], limit) if excerpts else ""

    def score(i: int) -> float:
        terms = _terms(segments[i])
        return sum(2 if t[0].isdigit() else 1 for t in terms & wanted) - 0.001 * i  # ties: earlier passage
    best = max(range(len(segments)), key=score)
    text = segments[best]
    if best + 1 < len(segments) and len(text) < limit * 0.6:  # short hit: add the next sentence for context
        text = f"{text} {segments[best + 1]}"
    return clean_excerpt(text, limit)


def _client(settings: Any):
    from parallel import Parallel

    return Parallel(api_key=settings.parallel_api_key)


def to_sources(results: list[Any], policy: dict[str, Any], limit: int, excerpt_chars: int, claim_text: str = "") -> list[Source]:
    """Parallel results -> Sources, in Parallel's order, one per URL, at most `limit`."""
    out: list[Source] = []
    seen: set[str] = set()
    for r in results:
        url = getattr(r, "url", "") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        excerpts = [e for e in (getattr(r, "excerpts", None) or []) if e and e.strip()]
        out.append(Source(url=url, title=clean_title(getattr(r, "title", None) or ""),
                          excerpt=best_excerpt(excerpts, claim_text, excerpt_chars),
                          publish_date=getattr(r, "publish_date", None), tier=source_tier(url, policy), rank=len(out)))
        if len(out) >= limit:
            break
    return out


def _said_by(ctx: dict[str, Any]) -> str:
    """'Said by Raj Shamani on Figuring Out, while discussing India's chip subsidies.' from the lookup context."""
    who = (ctx.get("speaker") or {}).get("name") or (ctx.get("speaker") or {}).get("label") or ""
    show = (ctx.get("creator") or {}).get("podcast") or ctx.get("channel") or ""
    about = ctx.get("discussing") or ""
    parts = [f"Said by {who}" if who else "Said", f"on {show}" if show else "", f"while discussing: {about}" if about else ""]
    line = " ".join(p for p in parts if p).strip()
    return "" if line == "Said" else line + "."


def related_objective(query: str, ctx: Optional[dict[str, Any]] = None) -> str:
    base = f"Find reports, data, official releases or news coverage about this statement: {query}"
    said = _said_by(ctx or {})
    return f"{base} Context: {said}" if said else base


def counter_request(query: str, route: str, ctx: Optional[dict[str, Any]] = None) -> tuple[list[str], str]:
    """Queries and objective for the second search. data: original figures and different numbers. contested: other
    perspectives, aimed away from the speaker's and show's known positions (from their profiles)."""
    ctx = ctx or {}
    said = _said_by(ctx)
    if route == "data":
        queries = [query, f"{query} official statistics data"[:300]]
        objective = ("Find primary sources for the figures in this statement: official statistics, the original study "
                     "or dataset, regulators or international bodies, and sources that give different figures, periods "
                     f"or definitions for the same thing. Statement: {query}")
    else:
        queries = [query, f"{query} criticism analysis"[:300]]
        objective = ("Find independent analyses, official data and reporting that give other perspectives on, "
                     f"qualify, or dispute this statement, from sources that do not share the speaker's viewpoint. Statement: {query}")
    leanings = [x for x in [(ctx.get("speaker") or {}).get("known_positions"), (ctx.get("creator") or {}).get("biases")] if x]
    criticism = [x for x in [(ctx.get("speaker") or {}).get("criticisms"), (ctx.get("creator") or {}).get("criticism")] if x]
    if said:
        objective += f" Context: {said}"
    if leanings:
        objective += " The speaker or show is described as: " + "; ".join(leanings)[:500] + "."
    if criticism:
        objective += " They are often criticised for: " + "; ".join(criticism)[:400] + ". Prefer sources that address this."
    return queries, objective[:2000]


async def search_sources(claim_text: str, settings: Any, policy: dict[str, Any], *, objective: Optional[str] = None,
                         extra_queries: tuple[str, ...] | list[str] = (), location: Optional[str] = None,
                         exclude_urls: frozenset[str] | set[str] = frozenset()) -> list[Source]:
    """One search. Raises on API errors or timeout (the caller marks the claim 'failed' so it can be retried)."""
    query = claim_text.strip()[:300]
    client = _client(settings)
    queries = [query] + [q.strip()[:300] for q in extra_queries if q and q.strip() and q.strip() != query]

    def _run() -> list[Any]:
        res = client.search(
            search_queries=queries,
            objective=objective or related_objective(query),
            mode=settings.sources_search_mode,
            advanced_settings={"max_results": settings.sources_per_claim + 3 + len(exclude_urls),
                               "location": location or getattr(settings, "default_search_location", "in"),
                               "source_policy": {"exclude_domains": blocklist(policy)},
                               "excerpt_settings": {"max_chars_per_result": 1500}},
        )
        return [r for r in res.results if (getattr(r, "url", "") or "") not in exclude_urls]

    results = await asyncio.wait_for(asyncio.to_thread(_run), timeout=settings.tool_timeout_s)
    return to_sources(results, policy, settings.sources_per_claim, settings.excerpt_chars, query)
