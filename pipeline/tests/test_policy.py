from claimcheck.policy import effective_tier, load_policy, needs_review, source_tier, tier1_domains_for

POLICY = load_policy()


def test_source_tiers():
    assert source_tier("https://www.rbi.org.in/x", POLICY) == 1
    assert source_tier("https://pmay-urban.gov.in/x", POLICY) == 1  # .gov.in suffix
    assert source_tier("https://www.thehindu.com/x", POLICY) == 2
    assert source_tier("https://someblog.in/x", POLICY) == 3
    assert source_tier("https://twitter.com/x", POLICY) == 9


def test_model_cannot_relax_tier():
    assert effective_tier("normal", "elections", "fact", POLICY) == "stricter"
    assert effective_tier("normal", "religious_belief", "fact", POLICY) == "never"
    assert effective_tier("stricter", "gdp", "fact", POLICY) == "stricter"
    assert effective_tier("normal", "gdp", "opinion", POLICY) == "never"
    assert effective_tier("normal", "gdp", "fact", POLICY) == "normal"


def test_review_rules():
    assert needs_review("false", "normal", "finance_health", POLICY)
    assert needs_review("misleading", "normal", "politics", POLICY)
    assert needs_review("disputed", "stricter", "finance_health", POLICY)
    assert not needs_review("supported", "stricter", "politics", POLICY)
    assert not needs_review("misleading", "normal", "finance_health", POLICY)


def test_parallel_domain_limit_respected():
    for area in POLICY["pestle_areas"]:
        assert 0 < len(tier1_domains_for(area, POLICY)) <= 10
    assert len(POLICY["sources"]["blocklist"]) <= 10
