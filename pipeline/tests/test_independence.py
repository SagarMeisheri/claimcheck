"""Which pages can be a source for an answer and which only repeat it. Code only: no keys or network."""

from claimcheck.agents.independence import EPISODE, INDEPENDENT, OWN, classify_source, org_terms, split_sources
from claimcheck.policy import load_policy
from claimcheck.schemas import Source

POLICY = load_policy()
CTX = {"speaker": {"name": "Sameer Nigam", "role": "CEO, PhonePe", "affiliations": ["PhonePe", "Flipkart"]},
       "creator": {"podcast": "WTF is Payments?"},
       "video": {"id": "hBvInWQWpZ0", "title": "If UPI Is Free, Who Pays for It? | PhonePe, Razorpay & NPCI", "channel": "Nikhil Kamath"}}


def src(url, title="A page", rank=0):
    return Source(url=url, title=title, excerpt="text", rank=rank)


def test_organisation_names_come_from_the_profile_the_role_and_the_show():
    terms = org_terms(CTX)
    assert "phonepe" in terms and "flipkart" in terms and "wtfispayments" in terms
    assert "ceo" not in terms and "sameernigam" not in terms


def test_job_titles_are_not_organisations_and_short_names_count_only_as_acronyms():
    assert org_terms({"speaker": {"name": "A B", "role": "Economist, former RBI governor"}}) == ["rbi"]
    assert org_terms({"speaker": {"name": "A B", "role": "Executive Director, NPCI"}}) == ["npci"]
    assert org_terms({"speaker": {"name": "A B", "role": "Columnist, Mint"}}) == []  # "Mint" is a newspaper, not an acronym
    assert org_terms({}) == []


def test_a_podcast_listing_or_transcript_is_the_episode_itself():
    for url in ("https://www.ulisten.ai/episode/abc", "https://podcasts.apple.com/in/podcast/x", "https://www.listennotes.com/e/1"):
        assert classify_source(url, "x", CTX, POLICY)[0] == EPISODE


def test_a_link_to_the_video_or_a_page_titled_like_it_is_the_episode_itself():
    assert classify_source("https://example.com/watch?v=hBvInWQWpZ0", "x", CTX, POLICY)[0] == EPISODE
    same = "If UPI Is Free, Who Pays for It? PhonePe, Razorpay & NPCI - Transcript"
    assert classify_source("https://blog.example.com/t", same, CTX, POLICY)[0] == EPISODE
    assert classify_source("https://blog.example.com/t", "Who pays for UPI? A look at merchant discount rates", CTX, POLICY)[0] == INDEPENDENT


def test_the_speakers_own_organisation_is_labelled_not_dropped():
    label, reason = classify_source("https://www.phonepe.com/press/merchants", "PhonePe crosses 50 million merchants", CTX, POLICY)
    assert label == OWN and "phonepe" in reason
    assert classify_source("https://www.reuters.com/markets/phonepe-merchants", "x", CTX, POLICY)[0] == INDEPENDENT  # about PhonePe, not by it


def test_split_keeps_every_source_labelled_and_counts_them():
    kept, counts = split_sources([src("https://www.ulisten.ai/e/1"), src("https://www.phonepe.com/a"), src("https://rbi.org.in/b")], CTX, POLICY)
    assert [(s.url, s.independence) for s in kept] == [("https://www.ulisten.ai/e/1", EPISODE), ("https://www.phonepe.com/a", OWN), ("https://rbi.org.in/b", INDEPENDENT)]
    assert counts == {INDEPENDENT: 1, OWN: 1, EPISODE: 1}
