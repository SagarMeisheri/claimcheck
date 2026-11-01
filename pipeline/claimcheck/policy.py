"""Loads policy.yaml and answers policy questions in code (never via the model)."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

_DEFAULT_PATH = Path(__file__).with_name("policy.yaml")


@functools.lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("CLAIMCHECK_POLICY_PATH", _DEFAULT_PATH))
    with p.open() as f:
        return yaml.safe_load(f)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def source_tier(url: str, policy: dict[str, Any] | None = None) -> int:
    """1 = official / peer-reviewed, 2 = major press, 3 = everything else. 9 = blocked."""
    pol = policy or load_policy()
    src = pol["sources"]
    host = domain_of(url)
    if not host:
        return 3
    if any(_matches(host, d) for d in src["blocklist"]):
        return 9
    if any(host.endswith(s) for s in src["tier1_suffixes"]) or any(_matches(host, d) for d in src["tier1_domains"]):
        return 1
    if any(_matches(host, d) for d in src["tier2_domains"]):
        return 2
    return 3


def effective_tier(model_tier: str, topic: str, claim_type: str, policy: dict[str, Any] | None = None) -> str:
    """Re-applies the content policy in code. The model's tier can only be made stricter."""
    pol = policy or load_policy()
    topic = (topic or "").lower().strip()
    if claim_type not in pol["claim_types_checked"]:
        return "never"
    if topic in pol["never_topics"] or model_tier == "never":
        return "never"
    if topic in pol["stricter_topics"] or model_tier == "stricter":
        return "stricter"
    return "normal"


def tier1_domains_for(area: str, policy: dict[str, Any] | None = None) -> list[str]:
    pol = policy or load_policy()
    return list(pol["sources"]["tier1_by_area"].get(area, pol["sources"]["tier1_by_area"]["economic"]))[:10]


def blocklist(policy: dict[str, Any] | None = None) -> list[str]:
    pol = policy or load_policy()
    return list(pol["sources"]["blocklist"])[:10]


def needs_review(verdict: str, tier: str, track: str, policy: dict[str, Any] | None = None) -> bool:
    pol = policy or load_policy()
    if verdict in pol["review"]["always"]:
        return True
    if track == "politics" and verdict in pol["review"]["politics_track"]:
        return True
    if tier == "stricter" and verdict in pol["tiers"]["stricter"]["review_verdicts"]:
        return True
    return False
