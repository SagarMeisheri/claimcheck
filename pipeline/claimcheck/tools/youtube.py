"""YouTube Data API v3 metadata fetch (one videos.list call = 1 quota unit)."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..guardrails.input_checks import parse_iso8601_duration

_API = "https://www.googleapis.com/youtube/v3/videos"
# The only YouTube Data API call in the pipeline, made once per manually submitted video
# (cached so the channel lookup and the ingest gate share one call).
_cache: dict[str, dict[str, Any]] = {}


async def fetch_metadata(video_id: str, settings: Settings) -> dict[str, Any]:
    if video_id in _cache:
        return _cache[video_id]
    meta = await _fetch(video_id, settings)
    _cache[video_id] = meta
    return meta


async def _fetch(video_id: str, settings: Settings) -> dict[str, Any]:
    params = {"id": video_id, "part": "snippet,contentDetails,status", "key": settings.youtube_api_key}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(_API, params=params)
        r.raise_for_status()
        items = r.json().get("items", [])
    if not items:
        return {"video_id": video_id, "privacy_status": "not_found"}
    it = items[0]
    sn, cd, st = it["snippet"], it["contentDetails"], it["status"]
    duration = parse_iso8601_duration(cd.get("duration", ""))
    return {
        "video_id": video_id,
        "title": sn.get("title", ""),
        "description": (sn.get("description") or "")[:3000],
        "channel_id": sn.get("channelId", ""),
        "channel_title": sn.get("channelTitle", ""),
        "published_at": sn.get("publishedAt"),
        "duration_s": duration,
        "privacy_status": st.get("privacyStatus"),
        "live_broadcast_content": sn.get("liveBroadcastContent", "none"),
        "is_short": duration <= 60,
        "default_audio_language": sn.get("defaultAudioLanguage"),
    }


