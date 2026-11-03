from claimcheck.policy import is_never, load_policy, source_tier, tier1_domains_for

POLICY = load_policy()


def test_source_tiers():
    assert source_tier("https://www.rbi.org.in/x", POLICY) == 1
    assert source_tier("https://pmay-urban.gov.in/x", POLICY) == 1  # .gov.in suffix
    assert source_tier("https://www.thehindu.com/x", POLICY) == 2
    assert source_tier("https://someblog.in/x", POLICY) == 3
    assert source_tier("https://twitter.com/x", POLICY) == 9


def test_model_can_add_never_but_code_also_applies_it():
    assert is_never("never", ["gdp"], POLICY)
    assert is_never("normal", ["gdp", "religious_belief"], POLICY)
    assert is_never("normal", [" Minor "], POLICY)
    assert not is_never("normal", ["gdp", "health"], POLICY)


def test_policy_has_no_verdict_rules_left():
    for gone in ("verdicts", "review", "on_demand", "triage", "stricter_topics", "claim_types_checked"):
        assert gone not in POLICY
    assert POLICY["sources_rules"]["allowed_tiers"] == [1, 2]


def test_parallel_domain_limit_respected():
    for area in POLICY["pestle_areas"]:
        assert 0 < len(tier1_domains_for(area, POLICY)) <= 10
    assert len(POLICY["sources"]["blocklist"]) <= 10
