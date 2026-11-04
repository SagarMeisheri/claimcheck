"""Speaker profiles for the people a description lists, built in the background while the video is read."""

import asyncio

from claimcheck.agents import speakers
from claimcheck.agents.pipeline import initial_steps
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context, set_step
from claimcheck.schemas import ClaimRecord, ExtractedClaim

PEOPLE = [{"name": "Rajesh Magow", "role": "Co-Founder & Group CEO, MakeMyTrip Limited", "is_host": ""},
          {"name": "Puneet Chhatwal", "role": "Managing Director & CEO, IHCL", "is_host": ""},
          {"name": "Nikhil Kamath", "role": "Co-founder of Zerodha", "is_host": "1"}]
WTF = {"id": "cr", "podcast": "WTF is", "profile": {"hosts": "Nikhil Kamath"}}


class Store:
    def __init__(self):
        self.rows, self.progress = {}, []

    async def get_speaker(self, key):
        return self.rows.get(key)

    async def save_speaker(self, row):
        self.rows[row["name_key"]] = {"id": "sp-" + row["name_key"], **row}
        return self.rows[row["name_key"]]

    async def update_episode(self, _id, fields):
        self.progress.append(fields.get("progress"))


def rec(i, speaker):
    c = ExtractedClaim(start_ts="0:10", speaker=speaker, claim="x", context_quote="x", pestle_area="economic",
                       topic="t", topics=["t"], statement_type="opinion", policy_tier="normal")
    return ClaimRecord(index=i, start_s=10, claim=c, effective_tier="normal")


def test_checklist_puts_speaker_profiles_after_video_details():
    keys = [s["key"] for s in initial_steps()]
    assert keys[:4] == ["creator", "ingest_gate", "speaker_profiler", "extractor"]
    assert next(s for s in initial_steps() if s["key"] == "speaker_profiler")["parallel"]


def test_parallel_step_is_not_ticked_off_by_later_steps():
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(), policy={}, store=None, budget=Budget(cap_usd=1),
                        steps=initial_steps())
    set_step(ec, "speaker_profiler", "running")
    set_step(ec, "extractor", "running")
    status = {s["key"]: s["status"] for s in ec.steps}
    assert status["speaker_profiler"] == "running" and status["ingest_gate"] == "done"
    set_step(ec, "speaker_profiler", "done", "3 of 3")
    set_step(ec, "speaker_profiler", "running")  # the pipeline reaching the step later doesn't restart it
    assert next(s for s in ec.steps if s["key"] == "speaker_profiler")["status"] == "done"


def test_listed_people_profiled_in_background(monkeypatch):
    searched = []

    async def fake_build(label, meta, topics, described_as=""):
        searched.append((label, described_as))
        return speakers.described_profile(label, described_as)  # as if the search couldn't identify them

    monkeypatch.setattr(speakers, "build_profile", fake_build)
    store = Store()
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(profile_speakers=True, max_speaker_profiles=1),
                        policy={}, store=store, budget=Budget(cap_usd=1), creator=WTF, steps=initial_steps(),
                        listed_people=PEOPLE)

    async def run():
        set_context(ec)
        speakers.start_listed_profiles({"title": "WTF is Travel?"})  # at the ingest gate
        await asyncio.sleep(0)  # ... the extractor would run here ...
        return await speakers.profile_speakers([rec(0, "Rajesh Magow"), rec(1, "Rajesh Magow"), rec(2, "Host"), rec(3, "Guest 1")], {})

    rows = {r["label"]: r for r in asyncio.run(run())}
    # One search allowed: the first listed guest, aimed with the description's role. The other falls back to that role.
    assert searched == [("Rajesh Magow", "Co-Founder & Group CEO, MakeMyTrip Limited")]
    assert store.rows["puneet chhatwal"]["summary"] == "Managing Director & CEO, IHCL."
    assert rows["Rajesh Magow"]["speaker_id"] == "sp-rajesh magow" and rows["Rajesh Magow"]["statements"] == 2
    assert rows["Puneet Chhatwal"] == {"label": "Puneet Chhatwal", "statements": 0, "speaker_id": "sp-puneet chhatwal", "role": "guest"}
    assert rows["Host"]["speaker_id"] == "sp-nikhil kamath" and "Nikhil Kamath" not in rows  # the host, once
    assert rows["Guest 1"]["speaker_id"] is None
    step = next(s for s in ec.steps if s["key"] == "speaker_profiler")
    assert step["status"] == "done" and step["detail"] == "3 of 3 people from the description have a profile"
