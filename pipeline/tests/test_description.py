"""Chapters and people read from a YouTube description (claimcheck/description.py), and the speaker-name rule."""

from types import SimpleNamespace

from claimcheck.agents.stages import speaker_label
from claimcheck.description import match_listed, parse_chapters, parse_people, people_context

DESCRIPTION = """Access the full data and references used in this episode below.
https://canva.link/abc

I put Rajesh Magow, the chartered accountant who co-founded MakeMyTrip, and Puneet Chhatwal, who ran hotels in Europe, into one room.

Timestamp:
00:00 Introduction
07:03 Getting to Know the Guests
14:30 How MakeMyTrip's Hotel Partnerships Work
1:03:05 Bringing Small-Town India into Online Travel

Rajesh Magow,Co-Founder & Group CEO, MakeMyTrip Limited
Linkedin:   / rajesh-magow-9278094

Puneet Chhatwal,Managing Director & Chief Executive Officer, The Indian Hotels Company Limited (IHCL)

Nikhil Kamath-Co-founder of Zerodha and Gruhas
Host of 'WTF is' & 'People By WTF' Podcast
Twitter: https://x.com/nikhilkamathcio/

Watch 'WTF Online' on Spotify
"""


def test_chapters_from_description():
    ch = parse_chapters(DESCRIPTION, duration_s=4000)
    assert [c["start_s"] for c in ch] == [0, 423, 870, 3785]
    assert ch[1]["title"] == "Getting to Know the Guests"
    assert ch[-1]["end_s"] == 4000 and ch[0]["end_s"] == 423
    assert all(c["summary"] == "" and c["idx"] == i for i, c in enumerate(ch))


def test_chapters_need_youtube_rules():
    assert parse_chapters("0:00 Intro\n5:00 Two") == []                     # fewer than three
    assert parse_chapters("1:00 a\n2:00 b\n3:00 c") == []                   # doesn't start at 0:00
    assert len(parse_chapters("Recorded 9:30 pm\n0:00 a\n1:00 b\n2:00 c")) == 3
    # a second, unrelated timestamp list further down is ignored
    assert len(parse_chapters("0:00 a\n1:00 b\n2:00 c\n\nRefs:\n0:30 x\n0:40 y")) == 3


def test_people_from_description():
    people = parse_people(DESCRIPTION)
    assert [p["name"] for p in people] == ["Rajesh Magow", "Puneet Chhatwal", "Nikhil Kamath"]
    assert people[0]["role"] == "Co-Founder & Group CEO, MakeMyTrip Limited"
    assert people[2]["role"] == "Co-founder of Zerodha and Gruhas" and people[2]["is_host"]
    assert not people[0]["is_host"]


def test_sentences_are_not_people():
    text = "Watch the full episode, CEO edition\nThe Economist, a weekly newspaper\nI met Sam Altman, CEO of OpenAI"
    assert parse_people(text) == []


def test_people_context_keeps_names_untrusted():
    ctx = people_context(parse_people(DESCRIPTION))
    assert "UNTRUSTED" in ctx and "Rajesh Magow" in ctx
    assert people_context([]) == ""


def test_speaker_names_limited_to_listed_people():
    ec = SimpleNamespace(listed_people=parse_people(DESCRIPTION), creator=None)
    assert match_listed("Puneet", ec.listed_people) == "Puneet Chhatwal"
    assert speaker_label("Rajesh", ec) == "Rajesh Magow"
    assert speaker_label("Amit Damani", ec) == "Speaker"     # only mentioned, not listed
    assert speaker_label("Guest 1", ec) == "Guest 1"          # roles stay
    no_list = SimpleNamespace(listed_people=[], creator=None)
    assert speaker_label("Amit Damani", no_list) == "Amit Damani"  # nothing listed: unchanged
