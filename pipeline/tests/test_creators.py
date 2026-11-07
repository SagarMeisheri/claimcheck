"""A creator profile found on the web for a channel that isn't on the curated list. No keys or network."""

import asyncio
from types import SimpleNamespace as NS

from claimcheck.agents import creators
from claimcheck.agents.creators import creator_row, profile_creator
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.policy import load_policy
from claimcheck.profiles import extraction_context, usable_creator
from claimcheck.schemas import CreatorProfileOut, IncentiveOut, Opinion, Sponsor

PAGES = [{"n": 1, "url": "https://press.example/review", "site": "press.example", "title": "Review", "text": "..."}]

META = {"channel_id": "UC123", "channel_title": "Figuring Out", "title": "Episode 5"}


def out(**kw):
    return CreatorProfileOut(**{"identified": True, "podcast": "Figuring Out", "summary": "A long-form interview show.",
                                "hosts": "Raj Shamani", "host_background": "Entrepreneur", "topics": ["business", "startups"],
                                "known_for": "Long interviews with founders", "country": "India", **kw})


def test_an_identified_channel_becomes_a_profile_with_only_what_the_pages_said():
    row = creator_row(META, out(criticism=[Opinion(text="Soft on guests", by="some viewers", page=1), Opinion(text="Uncited", page=9)],
                                sponsors=[Sponsor(name="Zerodha", category="broking", page=1)],
                                incentives=[IncentiveOut(tag="sponsor_aligned", reason="Sponsored by a broker; covers markets.", page=1),
                                            IncentiveOut(tag="access_preserving", reason="Described as soft on guests.", page=1),
                                            IncentiveOut(tag="commercial", reason="No such page.", page=7)]), PAGES)
    assert row["source"] == "web_search" and row["podcast"] == "Figuring Out" and row["country"] == "India" and row["profile_version"] == 2
    assert row["youtube_channel_ids"] == ["UC123"] and len(row["youtube_handles"]) == 1  # the arrays must match in length
    p = row["profile"]
    assert p["hosts"] == "Raj Shamani" and p["critiques"] == [{"text": "Soft on guests", "by": "some viewers", "url": "https://press.example/review", "site": "press.example"}]
    assert p["sponsors"][0]["name"] == "Zerodha" and p["public_opinion"].startswith("Criticised by some viewers")
    assert set(p["incentives"]) == {"sponsor_aligned"} and set(p["incentives_internal"]) == {"access_preserving"}  # an uncited tag is dropped
    assert p["incentives"]["sponsor_aligned"]["url"] == "https://press.example/review"
    assert "biases" not in row["profile"] and "identified" not in row["profile"]
    assert extraction_context(row) == "Show: Figuring Out. Hosts: Raj Shamani."


def test_a_channel_the_search_could_not_describe_is_saved_as_not_identified_and_gives_no_context():
    for nothing in (None, out(identified=False), out(summary="", hosts="", known_for="")):
        row = creator_row(META, nothing)
        assert row["profile"] == {"identified": False} and row["summary"] is None and row["country"] == "Unknown"
        assert usable_creator(row) is None
    assert usable_creator(creator_row(META, out()))["podcast"] == "Figuring Out"
    assert usable_creator(None) is None and usable_creator({"profile": {"hosts": "A"}}) is not None  # curated rows have no marker


class Store:
    def __init__(self):
        self.saved = []

    async def save_creator(self, row):
        self.saved.append(row)
        return {**row, "id": "c1"}

    async def update_creator(self, creator_id, fields):
        self.updated = (creator_id, fields)
        return {"id": creator_id, "podcast": "Curated", "profile": fields.get("profile") or {"hosts": "A"}, **fields}


def _ec(store, s):
    return EpisodeContext(episode_id="ep1", video_id="v", settings=s, policy=load_policy(), store=store,
                        budget=Budget(cap_usd=3.0), plugins_factory=lambda: [])


def run(monkeypatch, found, written=None, fail=None, meta=META, existing=None):
    store = Store()
    ec = _ec(store, Settings())

    async def search(m):
        if fail:
            raise fail
        return found

    async def write(channel, where, pages):
        return written

    monkeypatch.setattr(creators, "_search", search)
    monkeypatch.setattr(creators, "_write", write)

    async def go():
        token = set_context(ec)
        try:
            return await profile_creator(meta, existing=existing)
        finally:
            token.var.reset(token)

    return asyncio.run(go()), store, ec


def hit(url="https://example.com/about", excerpt="Figuring Out is a podcast hosted by Raj Shamani."):
    return {"n": 1, "url": url, "site": "example.com", "title": "About", "text": excerpt, "group": "SEARCH"}


def test_a_found_profile_is_saved_and_returned(monkeypatch):
    row, store, _ = run(monkeypatch, [hit()], out())
    assert row["id"] == "c1" and row["podcast"] == "Figuring Out" and len(store.saved) == 1


def test_no_search_results_saves_a_not_identified_marker_so_the_channel_is_not_searched_again(monkeypatch):
    row, store, _ = run(monkeypatch, [])
    assert row is None and store.saved[0]["profile"] == {"identified": False}


def test_a_model_that_could_not_identify_the_show_gives_no_context(monkeypatch):
    row, store, _ = run(monkeypatch, [hit()], out(identified=False))
    assert row is None and store.saved[0]["profile"] == {"identified": False}


def test_a_failed_search_never_raises_and_saves_nothing(monkeypatch):
    row, store, ec = run(monkeypatch, [], fail=RuntimeError("search down"))
    assert row is None and store.saved == []
    assert any(e.rule == "profile_failed" for e in ec.events)


def test_a_channel_without_an_id_is_skipped(monkeypatch):
    row, store, _ = run(monkeypatch, [hit()], out(), meta={"channel_title": "X"})
    assert row is None and store.saved == []


def test_a_curated_show_is_brought_up_to_version_2_keeping_its_own_fields(monkeypatch):
    curated = {"id": "cur1", "podcast": "Curated", "summary": "Curated summary.", "profile": {"hosts": "A", "biases": "curated note"}}
    row, store, _ = run(monkeypatch, [hit()], out(hosts="Someone else"), existing=curated)
    cid, fields = store.updated
    assert cid == "cur1" and store.saved == [] and fields["profile_version"] == 2
    assert fields["profile"]["hosts"] == "A" and fields["profile"]["biases"] == "curated note" and fields["summary"] == "Curated summary."
