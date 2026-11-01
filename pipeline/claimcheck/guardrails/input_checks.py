"""Stage 1 guardrail: only valid, public, long-enough, non-live videos get in."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url: str) -> Optional[str]:
    """Accepts youtube.com/watch?v=, youtu.be/, /shorts/, /live/ and /embed/ URLs."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    vid = None
    if host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        else:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
                vid = parts[1]
    if vid and _ID_RE.match(vid):
        return vid
    return None


def parse_iso8601_duration(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def validate_metadata(meta: dict[str, Any], policy: dict[str, Any]) -> tuple[bool, str]:
    """Returns (ok, reason). Reason is shown to users when a video is rejected."""
    if meta.get("privacy_status") != "public":
        return False, "Only public videos can be checked (this one is private or unlisted)."
    if meta.get("live_broadcast_content") in ("live", "upcoming"):
        return False, "Live streams and premieres can't be checked until they finish."
    if meta.get("is_short"):
        return False, "Shorts aren't covered in this version."
    if int(meta.get("duration_s", 0)) < int(policy["triage"]["min_duration_s"]):
        return False, "Videos under 5 minutes aren't covered."
    return True, ""
