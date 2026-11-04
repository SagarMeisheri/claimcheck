"""What the creator already wrote in the YouTube description, reused instead of asking the model again.

  chapters   YouTube-style timestamps ("00:00 Introduction" ... at least 3, the first at 0:00, in order). When present
             they are the video's chapters as is; the extractor writes no sections of its own.
  people     the guest / host lines creators list near the end ("Rajesh Magow, Co-Founder & Group CEO, MakeMyTrip",
             "Nikhil Kamath - Co-founder of Zerodha"). The extractor may only use these names for speakers, and each
             listed person is shown in the video's People tab with the role the description gives.

Pure code: the description is untrusted text, so nothing here follows instructions in it; it only matches patterns.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .guardrails.injection import wrap_untrusted
from .profiles import name_key

MIN_CHAPTERS = 3   # YouTube's own rule for a chapter list
MAX_CHAPTERS = 60
MAX_PEOPLE = 8

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})"
# "00:00 Introduction", "1:03:05 - Bringing Small-Town India...", "(12:30) Title", "12:30 – Title"
_CHAPTER = re.compile(rf"^\s*[\[(]?{_TS}[\])]?\s*(?:[-–—:|•]\s*)?(.+?)\s*$")


def _seconds(h: str | None, m: str, s: str) -> int:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def parse_chapters(description: str, duration_s: int = 0) -> list[dict[str, Any]]:
    """The description's chapters as sections ({idx, start_s, end_s, title, summary: ""}), or [] if it has none.

    Follows YouTube's rules: the first chapter starts at 0:00, there are at least three, and they go forward in time.
    """
    found: list[tuple[int, str]] = []
    for line in (description or "").splitlines():
        m = _CHAPTER.match(line)
        if not m:
            continue
        start, title = _seconds(m.group(1), m.group(2), m.group(3)), " ".join(m.group(4).split())[:120]
        if not title or re.match(r"^https?://", title):
            continue
        if found and start <= found[-1][0]:
            if found[0][0] == 0 and len(found) >= MIN_CHAPTERS:
                break  # a second timestamp list further down (e.g. a "references" list): keep the first one
            found = []  # out of order: not a chapter list, start again from here
        if not found and start != 0:
            continue
        found.append((start, title))
        if duration_s and start > duration_s:
            found.pop()
            break
    if len(found) < MIN_CHAPTERS:
        return []
    found = found[:MAX_CHAPTERS]
    end = max(duration_s, found[-1][0])
    return [{"idx": i, "start_s": s, "end_s": found[i + 1][0] if i + 1 < len(found) else end, "title": t, "summary": ""}
            for i, (s, t) in enumerate(found)]


# A name: 2-4 capitalised words ("Rajesh Magow", "Dr. Ashok K. Seth"), then a separator, then their role.
# Words have no hyphens, so "Nikhil Kamath-Co-founder of Zerodha" splits after "Kamath".
_NAME = r"(?:(?:Dr|Prof|Mr|Mrs|Ms|Shri|Smt|Sir)\.?\s+)?[A-Z][\w'’.]+(?:\s+[A-Z][\w'’.]*){1,3}"
_PERSON = re.compile(rf"^\s*(?:[•*\-–—]\s*)?(?:(?:Guests?|Hosts?|Speakers?|Featuring|Ft\.?)\s*[:\-–]\s*)?({_NAME})\s*(?:,|\s[-–—|:]\s?|-|\|)\s*(.{{3,160}})$")
# The role must read like a job or a public role, so ordinary sentences aren't taken for people.
_ROLEISH = re.compile(
    r"\b(founder|co-?founder|ceo|cfo|cto|coo|md|managing director|director|chair(man|person|woman)?|president|partner|"
    r"head|chief|officer|minister|mp|mla|secretary|governor|professor|prof|dr|doctor|economist|author|writer|journalist|"
    r"editor|anchor|host|investor|analyst|scientist|researcher|fellow|advisor|adviser|consultant|lawyer|advocate|judge|"
    r"actor|actress|filmmaker|director|athlete|player|coach|entrepreneur|founder|executive|vp|vice president|lead|"
    r"historian|activist|strategist|diplomat|ambassador|commissioner|ias|ips|general|colonel|creator|comedian)\b", re.I)
_NOT_A_NAME = re.compile(r"^(watch|subscribe|follow|join|listen|access|download|check|click|read|get|use|visit|buy|"
                         r"the|this|our|my|your|in|on|at|for|and|with|from|about|why|how|what|who|when)\b", re.I)


def parse_people(description: str) -> list[dict[str, str]]:
    """People the description lists as appearing in the video: [{name, role, is_host}], in the order listed."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    lines = (description or "").splitlines()
    for i, line in enumerate(lines):
        if "http" in line or _CHAPTER.match(line):
            continue
        m = _PERSON.match(line)
        if not m:
            continue
        name, role = " ".join(m.group(1).split()).strip(" .,"), " ".join(m.group(2).split()).strip(" .,")
        if _NOT_A_NAME.match(name) or not _ROLEISH.search(role) or len(line) > 200:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        after = lines[i + 1] if i + 1 < len(lines) else ""  # "Host of 'WTF is' & 'People By WTF' Podcast"
        host = re.search(r"\bhost\b", role, re.I) or re.match(r"\s*host(ed)?\b", after, re.I)
        out.append({"name": name, "role": role[:160], "is_host": "1" if host else ""})
        if len(out) >= MAX_PEOPLE:
            break
    return out


def match_listed(label: str, people: list[dict[str, str]]) -> Optional[str]:
    """The listed person a speaker label refers to ("Puneet Chhatwal", "Puneet", "Mr. Chhatwal"), or None."""
    words = set(name_key(label).split())
    if not words or max(len(w) for w in words) < 3:
        return None
    for p in people:
        if words <= set(name_key(p["name"]).split()):
            return p["name"]
    return None


def people_context(people: list[dict[str, str]]) -> str:
    """The extractor's lines about who appears, from the description. The names and roles stay inside untrusted markers."""
    if not people:
        return ""
    listed = "\n".join(f"- {p['name']}: {p['role']}" for p in people)
    return ("The video's description lists the people who appear in it:\n" + wrap_untrusted("DESCRIPTION PEOPLE", listed)
            + "\nWhen you can tell which of them is speaking, use that exact name as the speaker. Never give a speaker any "
            "other person's name: people who are only mentioned or talked about are not speakers. If you can't tell who "
            "is speaking, use a role (Host, Guest 1).")
