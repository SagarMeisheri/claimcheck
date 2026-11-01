"""Finds the channel row for a video, creating it from the video's own metadata when we don't track it yet.

A submitted video from an unknown channel used to be saved with no channel and show as "Submitted video".
Now the channel's id and name (already returned by the one videos.list call, so no extra YouTube quota) are
stored. These rows are polled=false, so the RSS cron keeps polling only the curated launch channels, and
they use the default track. There is no icon: the UI shows the channel's initial.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("claimcheck")


async def resolve_channel(store: Any, meta: dict[str, Any], settings: Any = None) -> Optional[dict[str, Any]]:
    yt_id, name = meta.get("channel_id") or "", meta.get("channel_title") or ""
    if not yt_id:
        return None
    channel = await store.get_channel(yt_id)
    if channel or not name:
        return channel
    try:
        return await store.add_channel({"youtube_channel_id": yt_id, "name": name, "track": "finance_health", "polled": False})
    except Exception:  # the video still gets checked; it just shows without a channel
        log.exception("could not create channel %s", yt_id)
        return None
