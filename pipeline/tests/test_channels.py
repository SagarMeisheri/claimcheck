"""A video from a channel we don't know yet gets a channel row (id and name) instead of 'Submitted video'."""

import asyncio

from claimcheck import channels
META = {"channel_id": "UC123", "channel_title": "Some Channel"}


class FakeStore:
    def __init__(self, existing=None):
        self.rows = {"UC123": existing} if existing else {}

    async def get_channel(self, yt_id):
        return self.rows.get(yt_id)

    async def add_channel(self, row):
        self.rows[row["youtube_channel_id"]] = {"id": "ch-new", **row}
        return self.rows[row["youtube_channel_id"]]


def test_known_channel_is_reused():
    got = asyncio.run(channels.resolve_channel(FakeStore({"id": "ch1"}), META))
    assert got["id"] == "ch1"


def test_unknown_channel_is_created_from_the_video_metadata_unpolled():
    store = FakeStore()
    got = asyncio.run(channels.resolve_channel(store, META))
    assert got["id"] == "ch-new" and got["name"] == "Some Channel" and got["polled"] is False
    assert got["youtube_channel_id"] == "UC123" and "track" not in got


def test_no_channel_id_or_name_means_no_channel():
    assert asyncio.run(channels.resolve_channel(FakeStore(), {})) is None
    assert asyncio.run(channels.resolve_channel(FakeStore(), {"channel_id": "UC123"})) is None
