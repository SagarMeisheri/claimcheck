"""Political leaning and public opinion in profiles: fallbacks to the fields the tables already have, and the live pull."""

import asyncio
from types import SimpleNamespace as NS

from claimcheck.agents import speakers
from claimcheck.agents.creators import creator_row
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.policy import load_policy
from claimcheck.profiles import creator_context, speaker_context
from claimcheck.schemas import CreatorProfileOut


def test_a_curated_show_gives_its_biases_as_leaning_and_its_criticism_as_public_opinion():
    c = creator_context({"podcast": "Show", "profile": {"hosts": "A", "biases": "Techno-libertarian", "criticism": "Fast-paced.", "controversies": "Clickbait titles."}})
    assert c["leaning"] == "Techno-libertarian" and c["leaning_basis"] == "curated" and c["public_opinion"] == "Fast-paced. Clickbait titles."


def test_a_live_profile_wins_over_the_older_fields():
    c = creator_context({"podcast": "Show", "profile": {"leaning": "Described by X as centrist", "leaning_basis": "described", "public_opinion": "Praised by Y.",
                                                         "biases": "old", "criticism": "old"}})
    assert c["leaning"] == "Described by X as centrist" and c["leaning_basis"] == "described" and c["public_opinion"] == "Praised by Y."


def test_a_speakers_known_positions_and_criticisms_fill_the_two_fields_when_nothing_newer_exists():
    s = speaker_context({"status": "ready", "name": "N", "profile": {"known_positions": "Described by Z as a free-market economist", "criticisms": "Criticised by W."}})
    assert s["leaning"].startswith("Described by Z") and s["leaning_basis"] == "described" and s["public_opinion"] == "Criticised by W."
    assert "leaning" not in speaker_context({"status": "ready", "name": "N", "profile": {"role": "Economist"}})


def test_a_live_creator_profile_saves_leaning_and_public_opinion():
    out = CreatorProfileOut(identified=True, podcast="Show", summary="A show.", hosts="A", leaning="Described by The Hindu as centre-left", leaning_basis="described",
                            public_opinion="Praised by X for depth. Criticised by Y for length.")
    p = creator_row({"channel_title": "Show", "channel_id": "UC1"}, out)["profile"]
    assert p["leaning"].startswith("Described by The Hindu") and p["leaning_basis"] == "described" and p["public_opinion"].startswith("Praised by X")
    none = creator_row({"channel_title": "Show", "channel_id": "UC1"}, CreatorProfileOut(identified=True, podcast="Show", summary="A show.", hosts="A"))["profile"]
    assert "leaning" not in none and "public_opinion" not in none


def test_a_host_gets_their_own_leaning_and_public_opinion_from_one_search(monkeypatch):
    s = Settings(profile_speakers=True, max_cost_usd_per_episode=3.0)
    ec = EpisodeContext(episode_id="e", video_id="v", settings=s, policy=load_policy(), store=NS(), budget=Budget(cap_usd=3.0), plugins_factory=lambda: [])
    ec.log = lambda *a, **k: None

    async def fake_build(label, meta, topics, described_as=""):
        return {"status": "ready", "profile": {"leaning": "Described by X as liberal", "leaning_basis": "described", "public_opinion": "Praised by Y.", "affiliations": ["Org"]},
                "sources": [{"url": "https://a.example", "title": "t"}]}
    monkeypatch.setattr(speakers, "build_profile", fake_build)

    async def go():
        token = set_context(ec)
        try:
            return await speakers.host_row("Ranveer Allahbadia", {"podcast": "Show", "profile": {"hosts": "Ranveer Allahbadia"}}, {})
        finally:
            token.var.reset(token)
    row = asyncio.run(go())
    assert row["profile"]["leaning"] == "Described by X as liberal" and row["profile"]["public_opinion"] == "Praised by Y." and row["profile"]["affiliations"] == ["Org"]
    assert row["profile"]["role"] == "Host of Show" and row["sources"]

    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(speakers, "build_profile", boom)
    row = asyncio.run(go())
    assert "leaning" not in row["profile"] and row["profile"]["role"] == "Host of Show"
