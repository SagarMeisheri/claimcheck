"""The pages an answer's correctness tag is shown with, and how many sites came back.

The label itself comes from the answer-tag classifier (agents/tags.py), which reads the search excerpts of every page. This module
only lists the pages the searches returned (the first few, each with its excerpt) and counts the sites, so a reader can see what the
label was made from. Every page counts alike: no kind of site is preferred or discounted.
"""

from __future__ import annotations

from typing import Any

LABELS = ("supported", "partly", "contradicted", "unverified", "opinion")
MAX_BASIS = 3
BASIS_CHARS = 240


def evidence_level(pages: list[dict[str, Any]]) -> str:
    """strong: pages from three or more sites came back; limited: one or two; none: none."""
    n = len({pg["site"] for pg in pages})
    return "strong" if n >= 3 else "limited" if n else "none"


def build_correctness(label: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    """{"label", "evidence", "basis": [{site, url, relation: "page", finding: title, quote: excerpt}]}. An opinion label has no basis."""
    basis = [{"site": pg["site"], "url": pg["url"], "relation": "page", "finding": pg["title"],
              "quote": " ".join((pg.get("text") or "").split())[:BASIS_CHARS]} for pg in pages[:MAX_BASIS]]
    return {"label": label, "evidence": evidence_level(pages), "basis": [] if label == "opinion" else basis}
