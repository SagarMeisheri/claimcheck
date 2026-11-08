"""Creator and speaker profile helpers, sections and the progress checklist. No network."""

from types import SimpleNamespace as NS

from claimcheck.agents.pipeline import initial_steps
from claimcheck.agents.speakers import host_profile, role_of
from claimcheck.agents.stages import normalize_sections
from claimcheck.context import set_step
from claimcheck.profiles import (creator_context, extraction_context, host_names, is_role_label, match_host, name_key,
                                 search_location, section_for, speaker_context)

PBT = {"id": "cr1", "podcast": "Pardon My Take", "country": "US", "summary": "Pardon My Take, hosted by ...",
       "profile": {"hosts": 'Dan "Big Cat" Katz & Eric "PFT Commenter" Sollenberger', "host_bio": "Barstool bloggers.",
                   "biases": "Bro culture.", "criticism": "Sportsbook ads.", "topics": ["NFL"]}}


def test_role_labels_never_get_a_profile_but_names_do():
    for label in ["Host", "Guest 1", "Panellist 2", "Speaker (off-screen)", "the host", "Co-host", "", "1"]:
        assert is_role_label(label), label
    for name in ["Joe Rogan", "Dr. Andrew Huberman", "Raj Shamani", "राज शमानी"]:
        assert not is_role_label(name), name


def test_names_are_compared_without_titles_or_punctuation():
    assert name_key("Dr. Andrew Huberman") == "andrew huberman" == name_key("  andrew   HUBERMAN ")


def test_hosts_with_nicknames_and_aliases_are_matched():
    assert "Big Cat" in host_names(PBT) and "Dan Katz" in host_names(PBT)
    assert match_host("Big Cat", PBT) == "Big Cat" and match_host("Katz", PBT) == "Dan Katz"
    assert match_host("Joe Rogan", PBT) is None and match_host("Dan", PBT) is None  # too short to be sure
    assert host_names({"profile": {"hosts": "Matthew Mercer & Cast"}}) == ["Matthew Mercer"]


def test_context_for_later_steps_and_for_the_extractor():
    ctx = creator_context(PBT)
    assert ctx["biases"] == "Bro culture." and ctx["podcast"] == "Pardon My Take"
    assert "Bro culture" not in extraction_context(PBT) and extraction_context(PBT).startswith("Show: Pardon My Take. Hosts:")
    assert creator_context(None) == {} and extraction_context(None) == ""
    assert speaker_context({"status": "not_found"}, "X") == {"label": "X"}
    assert speaker_context({"status": "ready", "name": "A", "summary": "s", "profile": {"criticisms": "c"}})["criticisms"] == "c"


def test_searches_are_geo_targeted_to_the_creators_country():
    assert search_location(PBT) == "us"
    assert search_location({"country": "UK / US"}) == "gb" and search_location({"country": "Japan (Intl)"}) == "jp"
    assert search_location(None) == "in" and search_location({"country": "Atlantis"}, "us") == "us"


def test_sections_are_cleaned_in_code():
    raw = [{"start_ts": "10:00", "title": "Inflation", "summary": "On prices."},
           {"start_ts": "00:30", "title": "Intro to the guest", "summary": "Who she is."},
           {"start_ts": "10:00", "title": "Duplicate", "summary": "x"},
           {"start_ts": "99:00:00", "title": "Past the end", "summary": "x"}, {"start_ts": "05:00"}, "junk"]
    got = normalize_sections(raw, duration_s=1800)
    assert [(s["idx"], s["start_s"], s["end_s"], s["title"]) for s in got] == [(0, 0, 600, "Intro to the guest"), (1, 600, 1800, "Inflation")]
    assert section_for(700, got)["title"] == "Inflation" and section_for(10, got)["idx"] == 0 and section_for(5, []) is None


def test_hosts_get_a_profile_from_the_creator_without_a_search():
    row = host_profile("Big Cat", PBT)
    assert row["name_key"] == "big cat" and row["creator_id"] == "cr1" and row["status"] == "ready"
    assert row["profile"]["known_positions"] == "Bro culture." and row["summary"] == "Host of Pardon My Take, with Eric Sollenberger."
    assert role_of("Host") == "host" and role_of("Guest 2") == "guest" and role_of("Joe Rogan") is None


def test_the_checklist_marks_earlier_steps_done_when_a_step_starts():
    ec = NS(steps=initial_steps())
    set_step(ec, "ingest_gate", "running")
    set_step(ec, "people_profiler", "skipped", "Nobody named before the video is read")
    set_step(ec, "claim_filter", "running")
    status = {s["key"]: s["status"] for s in ec.steps}
    assert list(status) == ["ingest_gate", "people_profiler", "extractor", "claim_filter", "speaker_profiler",
                            "interview_tagger", "publisher"]  # the show and who is talking first (one step); the video is marked done last
    assert status == {"ingest_gate": "done", "people_profiler": "skipped", "extractor": "done",
                      "claim_filter": "running", "speaker_profiler": "pending", "interview_tagger": "pending", "publisher": "pending"}
    set_step(ec, "nope", "done")  # unknown steps are ignored


def test_an_unnamed_host_on_a_one_host_show_gets_that_hosts_profile():
    import asyncio

    from claimcheck.agents.speakers import profile_speakers
    from claimcheck.config import Settings
    from claimcheck.context import Budget, EpisodeContext, set_context
    from claimcheck.schemas import ClaimRecord, ExtractedClaim

    class Store:
        def __init__(self):
            self.rows = {}

        async def get_speaker(self, key):
            return self.rows.get(key)

        async def save_speaker(self, row):
            self.rows[row["name_key"]] = {"id": "sp-" + row["name_key"], **row}
            return self.rows[row["name_key"]]

    def rec(i, speaker):
        c = ExtractedClaim(start_ts="0:10", speaker=speaker, claim="x", context_quote="x", pestle_area="economic",
                           topic="t", topics=["t"], statement_type="opinion", policy_tier="normal")
        return ClaimRecord(index=i, start_s=10, claim=c, effective_tier="normal")

    one_host = {"id": "cr2", "podcast": "Huberman Lab", "profile": {"hosts": "Dr. Andrew Huberman", "host_bio": "Neuroscientist."}}
    for creator, expect in [(one_host, "sp-andrew huberman"), (PBT, None)]:  # two hosts: can't tell which one
        set_context(EpisodeContext(episode_id="e", video_id="v", settings=Settings(profile_speakers=False), policy={},
                                   store=Store(), budget=Budget(cap_usd=1), creator=creator))
        rows = asyncio.run(profile_speakers([rec(0, "Host"), rec(1, "Guest 1")], {}))
        assert {r["label"]: (r["role"], r["speaker_id"]) for r in rows} == {"Host": ("host", expect), "Guest 1": ("guest", None)}
