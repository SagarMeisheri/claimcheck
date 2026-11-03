"""Rules every source must pass before it is shown next to a claim. All deterministic code.

The model only proposes a URL and a sentence. A source is kept when its page was really fetched, the sentence
is really on that page, and the site is official or an established news or research organisation. Nothing here
says whether the claim is right: the result is the sources, never a verdict.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from ..policy import source_tier
from ..schemas import CheckedSource, PickedSource

_MD_CHARS = re.compile(r"[*_`#>|\[\]]")
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "})


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    t = _MD_CHARS.sub(" ", t)
    return _WS.sub(" ", t).strip().lower()


def quote_in_source(quote: str, source_text: str, min_chars: int) -> bool:
    q = normalise(quote).strip(' ."\'')
    if len(q) < min_chars:
        return False
    return q in normalise(source_text)


def check_sources(picked: Iterable[PickedSource], evidence: dict[str, dict[str, Any]], policy: dict[str, Any],
                  log: Any = None, claim_index: int | None = None) -> list[CheckedSource]:
    """Keeps only sources that pass every rule, at most `max_per_claim`, one per URL. `log(rule, detail)` records drops."""
    rules = policy["sources_rules"]
    allowed = set(rules["allowed_tiers"])
    out: list[CheckedSource] = []
    seen: set[str] = set()
    for p in picked:
        def drop(rule: str) -> None:
            if log:
                log(rule, p.url)
        if p.url in seen:
            continue
        doc = evidence.get(p.url)
        tier = source_tier(p.url, policy)
        if tier == 9:
            drop("blocked_source")
            continue
        if not doc:
            drop("source_not_fetched")
            continue
        if not quote_in_source(p.quote, doc.get("text", ""), rules["min_quote_chars"]):
            drop("quote_not_on_page")
            continue
        if tier not in allowed:
            drop("source_tier_not_allowed")
            continue
        seen.add(p.url)
        out.append(CheckedSource(url=p.url, title=(p.title or doc.get("title") or "")[:300], tier=tier,
                                 quote=p.quote.strip()[:1000], publish_date=doc.get("publish_date")))
        if len(out) >= rules["max_per_claim"]:
            break
    return out
