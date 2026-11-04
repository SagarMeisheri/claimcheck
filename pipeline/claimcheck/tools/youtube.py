"""YouTube Data API v3 metadata (one videos.list or channels.list call = 1 quota unit, up to 50 ids).

API data may be kept at most 30 days without refreshing (YouTube API Services Developer Policies III.E.4), so the
maintenance endpoint in server.py refreshes stored titles and channel names with fetch_many / fetch_channels.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..config import Settings
from ..guardrails.input_checks import parse_iso8601_duration

_API = "https://www.googleapis.com/youtube/v3/videos"
_CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
BATCH = 50  # ids per request, the API maximum
# One call per submitted video, cached so the channel lookup and the ingest gate share it.
_cache: dict[str, dict[str, Any]] = {}


async def fetch_metadata(video_id: str, settings: Settings) -> dict[str, Any]:
    if video_id in _cache:
        return _cache[video_id]
    meta = await _fetch(video_id, settings)
    if len(_cache) >= 256:  # only needs to live for one run; never let it grow without bound
        _cache.clear()
    _cache[video_id] = meta
    return meta


def _parse(it: dict[str, Any]) -> dict[str, Any]:
    sn, cd, st = it["snippet"], it["contentDetails"], it["status"]
    duration = parse_iso8601_duration(cd.get("duration", ""))
    return {
        "video_id": it["id"],
        "title": sn.get("title", ""),
        "description": (sn.get("description") or "")[:5000],  # YouTube's maximum; guest lists often sit at the end
        "channel_id": sn.get("channelId", ""),
        "channel_title": sn.get("channelTitle", ""),
        "published_at": sn.get("publishedAt"),
        "duration_s": duration,
        "privacy_status": st.get("privacyStatus"),
        "live_broadcast_content": sn.get("liveBroadcastContent", "none"),
        "default_audio_language": sn.get("defaultAudioLanguage"),
    }


async def _fetch(video_id: str, settings: Settings) -> dict[str, Any]:
    return (await fetch_many([video_id], settings))[video_id]


async def fetch_many(video_ids: list[str], settings: Settings) -> dict[str, dict[str, Any]]:
    """Metadata for many videos, 50 per videos.list call (1 quota unit each).

    Videos YouTube no longer returns (deleted, private) come back as {"privacy_status": "not_found"}.
    """
    out: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(video_ids), BATCH):
            chunk = video_ids[i:i + BATCH]
            r = await client.get(_API, params={"id": ",".join(chunk), "part": "snippet,contentDetails,status",
                                               "key": settings.youtube_api_key})
            r.raise_for_status()
            for it in r.json().get("items", []):
                out[it["id"]] = _parse(it)
    return {v: out.get(v, {"video_id": v, "privacy_status": "not_found"}) for v in video_ids}


async def fetch_channels(channel_ids: list[str], settings: Settings) -> dict[str, Optional[str]]:
    """Current channel names, 50 per channels.list call (1 quota unit each). None = channel no longer exists."""
    out: dict[str, Optional[str]] = {c: None for c in channel_ids}
    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(channel_ids), BATCH):
            chunk = channel_ids[i:i + BATCH]
            r = await client.get(_CHANNELS_API, params={"id": ",".join(chunk), "part": "snippet", "key": settings.youtube_api_key})
            r.raise_for_status()
            for it in r.json().get("items", []):
                out[it["id"]] = (it.get("snippet") or {}).get("title")
    return out
