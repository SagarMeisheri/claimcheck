"""Incentive tags from the profiles, the people finder and the batched question tags. No keys or network."""

import asyncio
from types import SimpleNamespace as NS

from google.adk.labs.classifiers import ChoiceAnswer, ClassifierResponse

from claimcheck.agents import interview, people
from claimcheck.agents.profile_tags import description_notes, invested_peer, person_incentives, tag_rows
from claimcheck.agents.stages import build_record
from claimcheck.config import Settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.policy import load_policy
from claimcheck.profiles import cite, needs_rebuild, split_incentives

POLICY = load_policy()
GUEST = {"status": "ready", "name": "Varun Mayya", "profile": {
    "role": "Co-founder of Aeos", "businesses": [{"name": "Aeos", "relation": "founder", "url": "https://a.example", "site": "a.example"}],
    "incentives": {"commercial": {"reason": "Founder of Aeos, which sells AI products.", "url": "https://a.example", "site": "a.example"}}}}
HOST = {"status": "ready", "name": "Host Person", "profile": {
    "businesses": [{"name": "Aeos Ventures", "relation": "investor", "url": "https://h.example", "site": "h.example"}],
    "incentives_internal": {"access_preserving": {"reason": "Described by X as soft on guests.", "url": "https://x.example"}}}}
SHOW = {"podcast": "Show", "profile": {"incentives": {"sponsor_aligned": {"reason": "Sponsored by a broker.", "url": "https://s.example"}}}}


def test_cited_items_keep_their_page_and_uncited_ones_are_dropped():
    pages = [{"n": 1, "url": "https://p.example/1", "site": "p.example"}]
    got = cite([NS(model_dump=lambda: {"tag": "financial", "reason": "Invests in X.", "page": 1}),
                NS(model_dump=lambda: {"tag": "commercial", "reason": "Sells Y.", "page": 5})], pages)
    assert got == [{"tag": "financial", "reason": "Invests in X.", "url": "https://p.example/1", "site": "p.example"}]
    visible, internal = split_incentives([{"tag": "audience_captured", "reason": "r"}, {"tag": "financial", "reason": "r"}])
    assert set(visible) == {"financial"} and set(internal) == {"audience_captured"}


def test_a_guest_gets_their_own_tags_and_a_host_gets_theirs_the_shows_and_invested_peer():
    rows = [{"label": "Varun Mayya", "role": "guest", "speaker": GUEST}, {"label": "Host Person", "role": "host", "speaker": HOST}]
    tag_rows(rows, rows, SHOW, "VID1")
    assert set(rows[0]["incentives"]) == {"commercial"} and rows[0]["incentives_internal"] == {}
    assert set(rows[1]["incentives"]) == {"sponsor_aligned", "invested_peer"} and set(rows[1]["incentives_internal"]) == {"access_preserving"}
    assert "Aeos" in rows[1]["incentives"]["invested_peer"]["reason"] and rows[1]["incentives"]["invested_peer"]["url"] == "https://h.example"


def test_invested_peer_needs_a_real_name_match():
    assert invested_peer(HOST, [{"status": "ready", "profile": {"businesses": [{"name": "Zerodha"}]}}]) is None
    assert invested_peer({"profile": {}}, [GUEST]) is None


def test_what_the_description_promotes_makes_a_guest_commercial_for_this_video():
    plain = {"status": "ready", "name": "A Writer", "profile": {"role": "Author"}}
    visible, _ = person_incentives({"role": "guest", "speaker": plain, "promotes": ["book Ikigai Code"]}, None, [], "https://www.youtube.com/watch?v=V")
    assert visible["commercial"]["site"] == "the video's description" and "Ikigai Code" in visible["commercial"]["reason"]
    assert visible["commercial"]["url"].endswith("v=V")


def test_description_notes_keep_introductions_promotions_and_sponsor_lines():
    notes = description_notes("Intro\nThis episode is brought to you by Zerodha. Use code X\nhttps://example.com",
                              [{"name": "Varun Mayya", "role": "Co-founder, Aeos", "promotes": ["Aeos AI course"]}])
    assert notes[0] == "Varun Mayya: Co-founder, Aeos" and "promoted in the description" in notes[1] and "brought to you by Zerodha" in notes[2]


def test_profiles_older_than_version_2_or_stale_are_rebuilt():
    assert needs_rebuild(None) and needs_rebuild({"profile_version": 1})
    assert not needs_rebuild({"profile_version": 2, "profiled_at": "2099-01-01T00:00:00+00:00"})
    assert needs_rebuild({"profile_version": 2, "profiled_at": "2020-01-01T00:00:00+00:00"})


# --- the people finder ---------------------------------------------------------------------------------------

def _ec(creator=None, listed=()):
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(), policy=POLICY, store=NS(), budget=Budget(cap_usd=3.0),
                        plugins_factory=lambda: [], creator=creator)
    ec.listed_people = list(listed)
    return ec


def _find(monkeypatch, ec, answers, searched):
    async def ask(meta, pages):
        return answers(pages)

    async def search(meta):
        searched.append(True)
        return [{"n": 1, "site": "s", "title": "t", "text": "Nithin Kamath joins"}]

    monkeypatch.setattr(people, "_ask", ask)
    monkeypatch.setattr(people, "_search", search)

    async def go():
        token = set_context(ec)
        try:
            return await people.find_people({"title": "Ep"})
        finally:
            token.var.reset(token)

    return asyncio.run(go())


def test_the_description_comes_first_and_no_search_runs_when_it_names_a_guest(monkeypatch):
    searched = []
    got = _find(monkeypatch, _ec({"podcast": "Show", "profile": {"hosts": "Raj Shamani"}}),
                lambda pages: [{"name": "Varun Mayya", "role": "Co-founder, Aeos", "is_host": False, "promotes": ["Aeos"]}], searched)
    assert searched == [] and [p["name"] for p in got] == ["Raj Shamani", "Varun Mayya"] and got[1]["promotes"] == ["Aeos"]


def test_a_search_runs_only_when_nothing_names_a_guest(monkeypatch):
    searched = []
    got = _find(monkeypatch, _ec(), lambda pages: [{"name": "Nithin Kamath", "is_host": False}] if pages else [], searched)
    assert searched == [True] and [p["name"] for p in got] == ["Nithin Kamath"]


def test_a_name_not_in_the_source_text_is_never_kept():
    assert people._in_text("Varun Mayya", "Watch Varun Mayya on Aeos") and not people._in_text("Varun Mayya", "Watch Varun on Aeos")


# --- the batched question tags -------------------------------------------------------------------------------

def rec(i, q, spoken="", kind="asked"):
    raw = {"start_ts": f"{i}:00", "question": q, "question_quote": spoken, "question_kind": kind, "asked_by": "Host", "speaker": "Guest 1",
           "claim": f"Answer {i}.", "context_quote": "...", "statement_context": "x", "statement_type": "opinion", "pestle_area": "economic",
           "topics": ["x"], "policy_tier": "normal"}
    return build_record(i, raw, NS(policy=POLICY, listed_people=[], creator=None, log=lambda *a, **k: None), log=False)


def test_every_question_of_a_video_is_tagged_in_batched_calls_without_any_answer(monkeypatch):
    records = [rec(i, f"Question number {i}?", spoken=f"So, question {i}?" if i % 2 else "") for i in range(30)]
    records += [rec(30, "Question number 0?"), rec(31, "Implied one?", kind="implied")]  # a second answer to q1; an implied question
    calls = []

    async def classify(inp, questions):
        calls.append((inp, list(questions)))
        ans = {n: ChoiceAnswer(choice="challenging", probabilities={q: (0.9 if q == "challenging" else 0.02) for q in interview.QTYPES})
               for n in questions if n.startswith("q")}
        if "dynamic" in questions:
            ans["dynamic"] = ChoiceAnswer(choice="neutral", probabilities={"promotional": 0.2, "neutral": 0.7, "adversarial": 0.1})
        return ClassifierResponse(answers=ans)

    monkeypatch.setattr(interview, "_classify", classify)

    async def go():
        token = set_context(_ec())
        try:
            return await interview.tag_interview(records, ["invested_peer"], ["commercial"])
        finally:
            token.var.reset(token)

    by_idx, dynamic = asyncio.run(go())
    assert len(calls) == 2 and len(calls[0][1]) == interview.BATCH + 1 and "dynamic" not in calls[1][1]  # 30 questions: 2 calls
    assert len(calls[0][0]["questions"]) == 30 and "answer" not in str(calls[0][0]).lower().replace("answer_", "")
    assert by_idx[0] == by_idx[30] == {"type": "challenging", "p": 0.9, "spoken": False} and by_idx[1]["spoken"] is True
    assert 31 not in by_idx and dynamic == {"dynamic": "neutral", "p": 0.7}


def test_the_people_step_shows_who_was_profiled_and_their_visible_stakes():
    line = people.people_line([{"label": "Raj Shamani", "role": "host", "speaker_id": "s1", "incentives": {}},
                               {"label": "Varun Mayya", "role": "guest", "speaker_id": "s2", "incentives": {"commercial": {}, "financial": {}}},
                               {"label": "Someone", "role": "guest", "speaker_id": None}])
    assert line == "Raj Shamani (host) · Varun Mayya (guest): commercial, financial · Someone (guest), no profile"
