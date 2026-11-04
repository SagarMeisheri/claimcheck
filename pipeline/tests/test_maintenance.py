"""YouTube API data upkeep: batched metadata calls and the 30-day refresh. No network: a mock HTTP transport."""

import asyncio

import httpx

from claimcheck import maintenance
from claimcheck.config import Settings
from claimcheck.tools import youtube

SETTINGS = Settings(youtube_api_key="k", youtube_refresh_days=25)


def _video(vid, privacy="public"):
    return {"id": vid, "snippet": {"title": f"T {vid}", "channelId": "UC1", "channelTitle": "C", "publishedAt": "2026-01-01T00:00:00Z"},
            "contentDetails": {"duration": "PT10M"}, "status": {"privacyStatus": privacy}}


def _mock(monkeypatch, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    real = httpx.AsyncClient
    monkeypatch.setattr(youtube.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw))
    return calls


def test_fetch_many_batches_50_ids_per_call_and_marks_missing_videos(monkeypatch):
    ids = [f"v{i:09d}xx" for i in range(120)]
    gone = {ids[3], ids[77]}

    def handler(request):
        asked = request.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [_video(v) for v in asked if v not in gone]})
    calls = _mock(monkeypatch, handler)
    out = asyncio.run(youtube.fetch_many(ids, SETTINGS))
    assert [len(c.url.params["id"].split(",")) for c in calls] == [50, 50, 20]  # 3 quota units, not 120
    assert out[ids[0]]["title"] == f"T {ids[0]}" and out[ids[0]]["duration_s"] == 600
    assert out[ids[3]] == {"video_id": ids[3], "privacy_status": "not_found"}


class FakeStore:
    def __init__(self, unlinked=()):
        self.refreshed, self.removed, self.channels = [], [], []
        self.unlinked, self.rows, self.updates = list(unlinked), {}, []

    async def list_episodes_without_channel(self, limit=500):
        return self.unlinked

    async def get_channel(self, yt_id):
        return self.rows.get(yt_id)

    async def add_channel(self, row):
        self.rows[row["youtube_channel_id"]] = {"id": "ch-" + row["youtube_channel_id"], **row}
        return self.rows[row["youtube_channel_id"]]

    async def get_creator_by_channel(self, yt_id):
        return {"id": "cr1", "podcast": "Show"} if yt_id == "UC1" else None

    async def update_episode(self, eid, fields):
        self.updates.append((eid, fields))

    async def list_stale_episodes(self, days, limit=500):
        assert days == 25
        return [{"id": "e1", "youtube_video_id": "aaaaaaaaaaa"}, {"id": "e2", "youtube_video_id": "bbbbbbbbbbb"},
                {"id": "e3", "youtube_video_id": "ccccccccccc"}]

    async def list_stale_channels(self, days, limit=500):
        return [{"id": "c1", "youtube_channel_id": "UC1"}, {"id": "c2", "youtube_channel_id": "UCgone"}]

    async def refresh_episode_metadata(self, eid, fields):
        self.refreshed.append((eid, fields["title"]))

    async def mark_episode_removed(self, eid):
        self.removed.append(eid)

    async def refresh_channel(self, cid, fields):
        self.channels.append((cid, fields))


def test_refresh_updates_stale_data_and_hides_videos_youtube_no_longer_serves(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "New name"}}]})
        return httpx.Response(200, json={"items": [_video("aaaaaaaaaaa"), _video("bbbbbbbbbbb", privacy="private")]})
    _mock(monkeypatch, handler)
    store = FakeStore()
    counts = asyncio.run(maintenance.refresh_youtube_data(store, SETTINGS))
    assert counts == {"videos": 1, "removed": 2, "channels": 2, "relinked": 0, "creators": 0}
    assert store.refreshed == [("e1", "T aaaaaaaaaaa")] and store.removed == ["e2", "e3"]  # private and deleted
    assert store.channels == [("c1", {"name": "New name", "active": True}),
                              ("c2", {"name": "Unavailable channel", "active": False})]


def test_videos_saved_without_a_channel_get_their_channel_and_creator(monkeypatch):
    _mock(monkeypatch, lambda request: httpx.Response(200, json={"items": [_video("aaaaaaaaaaa")]}))
    store = FakeStore(unlinked=[{"id": "e1", "youtube_video_id": "aaaaaaaaaaa"}, {"id": "e2", "youtube_video_id": "zzzzzzzzzzz"}])
    counts = asyncio.run(maintenance.relink_channels(store, SETTINGS))
    assert counts == {"relinked": 1, "creators": 1}  # the deleted video has no channel to link
    assert store.updates == [("e1", {"channel_id": "ch-UC1", "creator_id": "cr1"})]
    assert store.rows["UC1"]["name"] == "C" and "track" not in store.rows["UC1"]
