"""Loads policy.yaml and answers policy questions in code (never via the model)."""

from __future__ import annotations

import functools
import os
import re
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
    """Display label for a source: 1 = official / peer-reviewed, 2 = established news or research, 3 = other, 9 = blocklisted."""
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


def is_never(model_tier: str, topics: list[str], policy: dict[str, Any] | None = None) -> bool:
    """Re-applies the never-show policy in code. The model can mark a statement 'never'; code can only add to that."""
    pol = policy or load_policy()
    return model_tier == "never" or any((t or "").lower().strip() in pol["never_topics"] for t in topics or [])


def normalize_topics(values: Any, policy: dict[str, Any] | None = None, limit: int = 2) -> list[str]:
    """Subject tags the model chose, tidied: snake_case, at most 40 characters, unique, at most `limit`.

    The tags are free-form (anything the statement is about), so there is no fixed list to check against.
    """
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for v in values or []:
        t = re.sub(r"[^\w]+", "_", str(v).lower(), flags=re.UNICODE).strip("_")[:40].strip("_")
        if t and t not in out:
            out.append(t)
    return out[:limit] or ["general"]


def blocklist(policy: dict[str, Any] | None = None) -> list[str]:
    pol = policy or load_policy()
    return list(pol["sources"]["blocklist"])[:10]
