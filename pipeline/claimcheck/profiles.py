"""Creator and speaker profiles: matching them to a video, and turning them into context for the later steps.

Creators come from the `creators` table (top YouTube podcasts, matched by YouTube channel ID). Speakers come from the
`speakers` table, built from a web search the first time a named person appears (agents/speakers.py).

How the profiles are used:
  extraction   the show and its hosts, so the host can be named
  triage       statement + what was being discussed + speaker and show profiles -> how to look it up
  searches     who said it and where steer the first search; known positions and criticisms aim the second one
  summary      the context line only helps pick out relevant excerpts
Biases and criticisms are never shown to viewers (the database only exposes the neutral parts).
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Labels the extractor uses when no name was said or shown: these never get a profile.
_ROLE = re.compile(
    r"^(the\s+)?(co-?host|host|guest|panel+ist|speaker|narrator|moderator|interviewer|interviewee|anchor|caller|"
    r"audience( member)?|reporter|presenter|voice ?over|unknown|unidentified|participant|man|woman|person|expert|"
    r"commentator|announcer|off-?screen)\b", re.I)
_TITLES = re.compile(r"\b(dr|mr|mrs|ms|prof|professor|sir|shri|smt|sri|hon)\.?\s+", re.I)
_QUOTED = re.compile(r"[\"“”']([^\"“”']+)[\"“”']")  # Dan "Big Cat" Katz -> nickname
_PARENS = re.compile(r"\(([^)]*)\)")              # Adam Grandmaison (Adam22) -> alias


def is_role_label(label: str) -> bool:
    """True for 'Host', 'Guest 1', 'Panellist 2', 'Speaker (off-screen)'; False for a person's name."""
    t = (label or "").strip()
    return not t or bool(_ROLE.match(t)) or not re.search(r"[A-Za-zऀ-ॿ]{2,}", t)


def name_key(name: str) -> str:
    """Lower case, titles and punctuation dropped: 'Dr. Andrew Huberman' -> 'andrew huberman'."""
    t = _TITLES.sub("", (name or "").strip())
    t = re.sub(r"[^\w\s]+", " ", t.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def host_groups(creator: Optional[dict[str, Any]]) -> list[list[str]]:
    """Each host's names, nicknames and aliases first, full name last, from profile.hosts:
    'Dan "Big Cat" Katz & Eric Sollenberger' -> [["Big Cat", "Dan Katz"], ["Eric Sollenberger"]]."""
    hosts = ((creator or {}).get("profile") or {}).get("hosts") or ""
    groups: list[list[str]] = []
    for part in re.split(r",|&|\band\b|/", hosts):
        p = part.strip()
        if not p or re.search(r"\b(cast|crew|ensemble)\b", p, re.I):
            continue
        names = [m.strip() for m in _QUOTED.findall(p) + _PARENS.findall(p)]
        plain = " ".join(_PARENS.sub("", _QUOTED.sub("", p)).split())
        if plain:
            names.append(plain)
        names = [n for n in dict.fromkeys(names) if len(name_key(n)) > 2]
        if names:
            groups.append(names)
    return groups


def host_names(creator: Optional[dict[str, Any]]) -> list[str]:
    """Every name the creator's hosts go by."""
    return list(dict.fromkeys(n for g in host_groups(creator) for n in g))


def match_host(label: str, creator: Optional[dict[str, Any]]) -> Optional[str]:
    """The host name a speaker label refers to ('Joe Rogan', 'Rogan', 'Big Cat'), or None."""
    key = name_key(label)
    if not key:
        return None
    words = set(key.split())
    for host in host_names(creator):
        hk = name_key(host)
        if key == hk or (len(words) >= 1 and words <= set(hk.split()) and len(key) >= 4):
            return host
    return None


def usable_creator(creator: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The creator row, or None for a channel a web search couldn't describe (saved so it isn't searched again)."""
    if creator and (creator.get("profile") or {}).get("identified") is False:
        return None
    return creator


def creator_context(creator: Optional[dict[str, Any]]) -> dict[str, Any]:
    """What the later steps get about the show. Empty if the channel isn't a known creator."""
    if not creator:
        return {}
    p = creator.get("profile") or {}
    # Curated shows already carry notes on leaning (biases) and on how the show is received (criticism, controversies); a show
    # found by a live search has leaning and public_opinion. Either way the later steps get the same two fields.
    opinion = p.get("public_opinion") or " ".join(x for x in (p.get("criticism"), p.get("controversies")) if x)
    return {k: v for k, v in {
        "podcast": creator.get("podcast"), "summary": creator.get("summary"), "hosts": p.get("hosts"),
        "country": creator.get("country"), "biases": p.get("biases"), "criticism": p.get("criticism"),
        "controversies": p.get("controversies"), "leaning": p.get("leaning") or p.get("biases"),
        "leaning_basis": p.get("leaning_basis") or ("curated" if p.get("biases") else ""), "public_opinion": opinion,
    }.items() if v}


def speaker_context(speaker: Optional[dict[str, Any]], label: str = "") -> dict[str, Any]:
    """What the later steps get about the person who said a statement."""
    if not speaker or speaker.get("status") != "ready":
        return {"label": label} if label else {}
    p = speaker.get("profile") or {}
    return {k: v for k, v in {
        "name": speaker.get("name") or label, "summary": speaker.get("summary"), "role": p.get("role"),
        "affiliations": p.get("affiliations"), "known_positions": p.get("known_positions"), "criticisms": p.get("criticisms"),
        "leaning": p.get("leaning") or p.get("known_positions"),
        "leaning_basis": p.get("leaning_basis") or ("described" if p.get("known_positions") else ""),
        "public_opinion": p.get("public_opinion") or p.get("criticisms"),
    }.items() if v}


def extraction_context(creator: Optional[dict[str, Any]]) -> str:
    """One line for the extractor: the show and its hosts (so the host can be named). Neutral parts only."""
    if not creator:
        return ""
    hosts = ((creator.get("profile") or {}).get("hosts") or "").strip()
    return f"Show: {creator.get('podcast')}" + (f". Hosts: {hosts}." if hosts else ".")


# ISO 3166-1 alpha-2 codes for Parallel's geo-targeting, from creators.country.
_COUNTRY_CODES = {
    "us": "us", "india": "in", "uk": "gb", "brazil": "br", "spain": "es", "mexico": "mx", "canada": "ca",
    "germany": "de", "france": "fr", "saudi arabia": "sa", "australia": "au", "dominican rep.": "do", "japan": "jp",
}


def search_location(creator: Optional[dict[str, Any]], default: str = "in") -> str:
    """Where to geo-target searches: the creator's country ('UK / US' -> gb, 'Japan (Intl)' -> jp), else the default."""
    country = ((creator or {}).get("country") or "").lower()
    first = re.split(r"\s*/\s*|\s*\(", country)[0].strip()
    return _COUNTRY_CODES.get(first, default)


def section_for(start_s: int, sections: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The section a moment falls in: the last one starting at or before it."""
    hit = None
    for s in sorted(sections or [], key=lambda x: x.get("start_s", 0)):
        if s.get("start_s", 0) <= start_s:
            hit = s
    return hit
