"""Stage 8 guardrails: rules every verdict must pass before it can be published.

All deterministic code. The model proposes a verdict; these rules can only keep
it or downgrade it (never upgrade).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from ..policy import source_tier
from ..schemas import Citation, ExtractedClaim, FinalVerdict, JudgeResult

# --- Text normalisation ----------------------------------------------------------

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


# --- Number extraction (handles Indian units) -------------------------------------

_UNITS = {
    "thousand": 1e3, "k": 1e3,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "million": 1e6, "mn": 1e6,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "billion": 1e9, "bn": 1e9,
    "trillion": 1e12, "tn": 1e12,
}
_NUM_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|per\s*cent|percent)?\s*"
    r"(lakh\s+crore|thousand|lakhs?|lacs?|million|mn|crores?|cr|billion|bn|trillion|tn|k)?(?![a-z])",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


_PERIOD_RE = re.compile(r"\b(?:FY\s?)?(?:19|20)\d{2}\s?[-\u2013/]\s?\d{2,4}\b|\bFY\s?\d{2,4}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE)


def extract_numbers(text: str) -> list[float]:
    """Returns canonical values. Years, fiscal years (FY2025-26) and dates are ignored."""
    out: list[float] = []
    text = _PERIOD_RE.sub(" ", text or "")
    for m in _NUM_RE.finditer(text):
        raw, pct, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        if _YEAR_RE.match(raw) and not pct and not unit:
            continue
        val = float(raw.replace(",", ""))
        if unit:
            unit = re.sub(r"\s+", " ", unit)
            val *= 1e12 if unit == "lakh crore" else _UNITS.get(unit, 1)
        out.append(val)
    return out


def numbers_consistent(claim_text: str, quote_text: str, tolerance: float) -> Optional[bool]:
    """None if the claim has no numbers; True if any claim number matches a quote number."""
    cn = extract_numbers(claim_text)
    if not cn:
        return None
    qn = extract_numbers(quote_text)
    if not qn:
        return False
    for a in cn:
        for b in qn:
            if a == b or (max(abs(a), abs(b)) > 0 and abs(a - b) / max(abs(a), abs(b)) <= tolerance):
                return True
    return False


# --- Neutral wording ---------------------------------------------------------------

def neutral_reasoning(reasoning: str, citations: list[Citation], banned: list[str]) -> tuple[str, bool]:
    low = (reasoning or "").lower()
    if not any(term.lower() in low for term in banned):
        return reasoning, False
    if citations:
        c = citations[0]
        return f'The cited source ({c.title or c.url}) states: "{c.quote}"', True
    return "No reliable source addressing this claim was found.", True


# --- Main entry ----------------------------------------------------------------------

def apply_verdict_checks(
    judge: JudgeResult,
    claim: ExtractedClaim,
    tier: str,
    evidence: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    second_opinion: Optional[JudgeResult] = None,
) -> tuple[FinalVerdict, list[tuple[str, str]]]:
    """Returns the final verdict and a list of (rule, detail) downgrades applied."""
    rules = policy["verdicts"]
    downgrades: list[tuple[str, str]] = []

    # 1. Citations: tier computed from URL; quote must exist in the fetched text.
    citations: list[Citation] = []
    for c in judge.citations:
        doc = evidence.get(c.url)
        passed = bool(doc) and quote_in_source(c.quote, doc.get("text", ""), rules["min_quote_chars"])
        tier_n = source_tier(c.url, policy)
        if tier_n == 9:
            downgrades.append(("blocked_source", c.url))
            continue
        if not doc:
            downgrades.append(("citation_not_in_evidence", c.url))
        elif not passed:
            downgrades.append(("quote_check_failed", c.url))
        citations.append(Citation(url=c.url, title=c.title or (doc or {}).get("title", ""), tier=tier_n, quote=c.quote, quote_check_passed=passed))
    good = [c for c in citations if c.quote_check_passed]
    verdict, confidence = judge.verdict, judge.confidence

    def downgrade(new: str, rule: str, detail: str = "") -> None:
        nonlocal verdict
        if new != verdict:
            downgrades.append((rule, f"{verdict} -> {new}. {detail}".strip()))
            verdict = new

    if verdict != "unverifiable" and not good:
        downgrade("unverifiable", "no_valid_citation", "no quote found in fetched sources")

    # 2. Number check: a Supported claim's numbers must appear in a cited quote.
    if verdict == "supported":
        quotes = " ".join(c.quote for c in good)
        ok = numbers_consistent(claim.claim, quotes, rules["number_tolerance"])
        if ok is False:
            downgrade("unverifiable", "number_mismatch", "claim numbers not found in cited quotes")

    # 3. Stricter tier: Supported/False/Misleading need an official (tier-1) source.
    if tier == "stricter" and verdict in ("supported", "false", "misleading") and policy["tiers"]["stricter"].get("require_tier1_source"):
        if not any(c.tier == 1 for c in good):
            downgrade("unverifiable", "tier1_source_required", "stricter-tier claim without an official source")

    # 4. Disputed needs two independent sources that both pass the quote check.
    if verdict == "disputed" and len({c.url for c in good}) < 2:
        downgrade("unverifiable", "disputed_needs_two_sources")

    # 5. False rule: strong source, high confidence, and a second judge run agrees.
    if verdict == "false":
        strong = any(c.tier <= 2 for c in good)
        if not strong:
            downgrade("unverifiable", "false_needs_strong_source")
        elif confidence < rules["false_min_confidence"]:
            downgrade("unverifiable", "false_low_confidence", f"confidence {confidence:.2f}")
        elif rules.get("false_requires_second_judge"):
            if second_opinion is None:
                downgrade("unverifiable", "false_second_judge_missing")
            elif second_opinion.verdict != "false":
                downgrade("unverifiable", "false_second_judge_disagrees", f"second judge said {second_opinion.verdict}")

    # 6. Outdated needs a valid citation (already enforced) - nothing more in MVP.

    reasoning, rewritten = neutral_reasoning(judge.reasoning, good, rules["banned_reasoning_terms"])
    if rewritten:
        downgrades.append(("neutral_wording", "reasoning rewritten to neutral template"))

    if verdict == "unverifiable":
        confidence = min(confidence, 0.5)

    final = FinalVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        reasoning=reasoning,
        correction=judge.correction if verdict == "false" else "",
        evidence_grade=judge.evidence_grade or "not_applicable",
        citations=good if verdict != "unverifiable" else [],
        downgrades=[f"{r}: {d}" for r, d in downgrades],
    )
    return final, downgrades


_TIER_STRENGTH = {1: 1.0, 2: 0.7, 3: 0.4}


def truth_score(verdict: str, confidence: float, citations: list[Citation]) -> Optional[int]:
    """0-100 truthfulness, computed from the checked verdict, never asked of the model.

    100 = clearly supported by strong sources, 0 = clearly contradicted, None = unverifiable (no score is honest).
    Strength blends the judge's confidence, the best source tier and how many verified citations back it.
    """
    if verdict in ("unverifiable", "disputed"):
        return None
    good = [c for c in citations if c.quote_check_passed]
    best = max((_TIER_STRENGTH.get(c.tier, 0.2) for c in good), default=0.0)
    strength = 0.6 * confidence + 0.25 * best + 0.15 * min(1.0, len({c.url for c in good}) / 2)
    strength = max(0.0, min(1.0, strength))
    if verdict in ("supported", "outdated"):
        return round(50 + 50 * strength) if verdict == "supported" else round(25 + 25 * strength)
    if verdict == "misleading":
        return round(35 + 15 * (1 - strength))
    return round(50 - 50 * strength)  # false


def needs_second_opinion(judge: JudgeResult, policy: dict[str, Any]) -> bool:
    r = policy["verdicts"]
    return judge.verdict == "false" and judge.confidence >= r["false_min_confidence"] and r.get("false_requires_second_judge", False)
