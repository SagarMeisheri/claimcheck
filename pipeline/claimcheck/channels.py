"""Finds the channel row for a video, creating it from the video's own metadata when we don't track it yet.

The channel's id and name come from the one videos.list call (no extra YouTube quota). Rows are polled=false
(nothing polls channels any more) and the name is refreshed every few weeks by the maintenance job. There is no
icon: the UI shows the channel's initial.
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
        return await store.add_channel({"youtube_channel_id": yt_id, "name": name, "polled": False})
    except Exception:  # the video still gets checked; it just shows without a channel
        log.exception("could not create channel %s", yt_id)
        return None
