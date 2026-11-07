"""Incentive tags for one video's people, and the interview dynamic.

The tags themselves are written by the profile writers (prompts.PROFILE_SPEAKER, prompts.PROFILE_CREATOR) in the same model call as
the profile, each with the fact and the search page that shows it (profiles.v2_fields keeps only tags that cite a real page). This
module only puts them together for one video, in code:

  guest   the guest's own tags: commercial, financial, ideological, reputational, academic
  host    the host's tags plus the show's: sponsor_aligned, adversarial, (internal) access_preserving, audience_captured
          + invested_peer, worked out here: the host's businesses or financial interests name a company the guest founded, runs,
            owns or invests in.
Saved per video in episode_speakers.incentives (shown) and incentives_internal (never shown); the answer tags (agents/qa_tags.py)
read them as the skepticism multiplier.
No classifier call here: the interview dynamic is asked with the question types (agents/interview.py).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..guardrails.injection import screen_text

GUEST_TAGS = ("commercial", "financial", "ideological", "reputational", "academic")
HOST_TAGS = ("sponsor_aligned", "invested_peer", "adversarial", "access_preserving", "audience_captured", "ideological",
             "commercial", "financial")
_SPONSOR_LINE = re.compile(r"sponsor|brought to you|partner|use code|affiliate|discount|promo|paid|in association|powered by|#ad\b", re.I)
_WORD = re.compile(r"[a-z0-9]+")
_GENERIC = {"the", "inc", "ltd", "llc", "pvt", "private", "limited", "group", "company", "co", "labs", "ventures", "capital", "and",
            "of", "india", "global", "media", "technologies", "technology", "tech"}


def description_notes(description: str, listed_people: list[dict[str, str]]) -> list[str]:
    """What the description tells viewers that bears on a stake: how each person is introduced, and sponsor lines. Code only."""
    notes = [f"{p['name']}: {p['role']}" for p in listed_people if p.get("name") and p.get("role")]
    notes += [f"{p['name']} (promoted in the description): {'; '.join(p['promotes'])}" for p in listed_people if p.get("promotes")]
    for line in (description or "").splitlines():
        line = " ".join(line.split())
        if line and len(line) <= 200 and _SPONSOR_LINE.search(line):
            notes.append(screen_text(line)[0])
    return list(dict.fromkeys(notes))[:20]


def _profile(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    return ((row or {}).get("profile") or {}) if (row or {}).get("status", "ready") == "ready" else {}


def _org_key(name: str) -> str:
    return " ".join(w for w in _WORD.findall((name or "").lower()) if w not in _GENERIC)


def invested_peer(host: dict[str, Any], guests: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The invested_peer tag when the host's own businesses or financial interests name a guest's company. Code only."""
    hp = _profile(host)
    host_text = " ".join([_org_key(b.get("name", "")) for b in hp.get("businesses") or []]
                         + [_org_key(f.get("what", "")) for f in hp.get("financial_interests") or []])
    for g in guests:
        for b in _profile(g).get("businesses") or []:
            key = _org_key(b.get("name", ""))
            if len(key) >= 4 and re.search(rf"\b{re.escape(key)}\b", host_text):
                hit = next((x for x in (hp.get("businesses") or []) + (hp.get("financial_interests") or [])
                            if key in _org_key(x.get("name") or x.get("what") or "")), {})
                who = (g.get("name") or "the guest")
                return {"reason": f"The host is tied to {b.get('name')}, which {who} is {b.get('relation') or 'tied to'}.",
                        "url": hit.get("url", ""), "site": hit.get("site", "")}
    return None


def person_incentives(row: dict[str, Any], creator: Optional[dict[str, Any]], guests: list[dict[str, Any]],
                      video_url: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """(visible, internal) incentive tags of one episode_speakers working row, for this video."""
    sp = row.get("speaker") or {}
    p = _profile(sp)
    visible = dict(p.get("incentives") or {})
    internal = dict(p.get("incentives_internal") or {})
    if row.get("promotes") and "commercial" not in visible:
        # The video's own description promotes something of theirs: commercial, for this video, cited to the description.
        visible["commercial"] = {"reason": "The video's description promotes: " + "; ".join(row["promotes"][:3]) + ".",
                                 "url": video_url, "site": "the video's description"}
    if row.get("role") == "host":
        cp = (creator or {}).get("profile") or {}
        for k, v in (cp.get("incentives") or {}).items():
            visible.setdefault(k, v)
        for k, v in (cp.get("incentives_internal") or {}).items():
            internal.setdefault(k, v)
        peer = invested_peer(sp, [g.get("speaker") or {} for g in guests])
        if peer:
            visible["invested_peer"] = peer
        keep = set(HOST_TAGS)
    else:
        keep = set(GUEST_TAGS)
    return {k: v for k, v in visible.items() if k in keep}, {k: v for k, v in internal.items() if k in keep}


def tag_rows(rows: list[dict[str, Any]], everyone: list[dict[str, Any]], creator: Optional[dict[str, Any]], video_id: str = "") -> None:
    """Sets incentives / incentives_internal on each of `rows` (working rows), reading the guests among `everyone`."""
    guests = [r for r in everyone if r.get("role") != "host" and r.get("speaker")]
    url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    for r in rows:
        r["incentives"], r["incentives_internal"] = person_incentives(r, creator, guests, url)
