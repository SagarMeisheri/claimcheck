"""The pages a correctness tag is shown with. No model, no network. Every page counts alike."""

from claimcheck.agents.correctness import build_correctness, evidence_level


def pg(site, title="A page", text="An excerpt from the search.", independence="independent"):
    return {"url": f"https://{site}/a", "site": site, "title": title, "date": None, "independence": independence, "text": text}


def test_evidence_counts_the_sites_the_search_returned_whatever_their_kind():
    assert evidence_level([pg("a.example"), pg("b.example"), pg("gov.nic.in")]) == "strong"
    assert evidence_level([pg("a.example", independence="own_organisation"), pg("a.example")]) == "limited"  # one site, however many pages
    assert evidence_level([pg("a.example"), pg("b.example")]) == "limited"
    assert evidence_level([]) == "none"


def test_the_basis_is_the_first_pages_the_search_returned_with_their_excerpts():
    c = build_correctness("partly", [pg("a.example", "First", "x " * 300), pg("b.example", "Second"), pg("c.example"), pg("d.example")])
    assert [b["site"] for b in c["basis"]] == ["a.example", "b.example", "c.example"]
    assert c["basis"][0] == {"site": "a.example", "url": "https://a.example/a", "relation": "page", "finding": "First", "quote": ("x " * 300).strip()[:240]}
    assert c["label"] == "partly" and c["evidence"] == "strong"


def test_an_unverified_label_still_lists_the_pages_found_and_an_opinion_label_has_none():
    c = build_correctness("unverified", [pg("a.example")])
    assert c["label"] == "unverified" and [b["site"] for b in c["basis"]] == ["a.example"] and c["evidence"] == "limited"
    assert build_correctness("opinion", [pg("a.example")])["basis"] == []
    assert build_correctness("unverified", []) == {"label": "unverified", "evidence": "none", "basis": []}
