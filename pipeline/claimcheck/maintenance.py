"""Upkeep of stored YouTube API data.

YouTube's API policies (III.E.4) allow API data to be stored for at most 30 days without refreshing, and ask that it
stay consistent with YouTube. This refreshes titles, lengths and channel names older than settings.youtube_refresh_days
and hides videos YouTube no longer serves publicly. Called daily via POST /maintenance/youtube-refresh.
"""

from __future__ import annotations

from typing import Any

from .channels import resolve_channel
from .profiles import usable_creator
from .tools.youtube import fetch_channels, fetch_many


async def relink_channels(store: Any, settings: Any) -> dict[str, int]:
    """Videos saved without a channel (e.g. when creating the channel row failed) get their channel, and their creator
    profile if the channel is a known show. One videos.list call per 50 videos."""
    counts = {"relinked": 0, "creators": 0}
    eps = await store.list_episodes_without_channel()
    if not eps:
        return counts
    meta = await fetch_many([e["youtube_video_id"] for e in eps], settings)
    for e in eps:
        m = meta[e["youtube_video_id"]]
        channel = await resolve_channel(store, m)
        if not channel:
            continue
        fields: dict[str, Any] = {"channel_id": channel["id"]}
        creator = usable_creator(await store.get_creator_by_channel(m.get("channel_id") or ""))
        if creator:
            fields["creator_id"] = creator["id"]
            counts["creators"] += 1
        await store.update_episode(e["id"], fields)
        counts["relinked"] += 1
    return counts


async def refresh_youtube_data(store: Any, settings: Any) -> dict[str, int]:
    """Refreshes stored YouTube API data older than settings.youtube_refresh_days (YouTube allows at most 30).

    Videos YouTube no longer serves publicly are marked 'removed' (hidden from the site, title cleared).
    """
    counts = {"videos": 0, "removed": 0, "channels": 0}
    counts.update(await relink_channels(store, settings))
    eps = await store.list_stale_episodes(settings.youtube_refresh_days)
    if eps:
        meta = await fetch_many([e["youtube_video_id"] for e in eps], settings)
        for e in eps:
            m = meta[e["youtube_video_id"]]
            if m.get("privacy_status") != "public":
                await store.mark_episode_removed(e["id"])
                counts["removed"] += 1
            else:
                await store.refresh_episode_metadata(e["id"], {"title": m.get("title") or None, "duration_s": m.get("duration_s") or None,
                                                               "published_at": m.get("published_at") or None})
                counts["videos"] += 1
    chans = await store.list_stale_channels(settings.youtube_refresh_days)
    if chans:
        names = await fetch_channels([c["youtube_channel_id"] for c in chans], settings)
        for c in chans:
            name = names.get(c["youtube_channel_id"])
            await store.refresh_channel(c["id"], {"name": name or "Unavailable channel", "active": bool(name)})
            counts["channels"] += 1
    return counts
