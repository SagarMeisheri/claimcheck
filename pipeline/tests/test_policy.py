from claimcheck.policy import blocklist, is_never, load_policy

POLICY = load_policy()


def test_model_can_add_never_but_code_also_applies_it():
    assert is_never("never", ["gdp"], POLICY)
    assert is_never("normal", ["gdp", "religious_belief"], POLICY)
    assert is_never("normal", [" Minor "], POLICY)
    assert not is_never("normal", ["gdp", "health"], POLICY)


def test_policy_has_no_verdict_rules_left():
    for gone in ("verdicts", "review", "on_demand", "triage", "stricter_topics", "claim_types_checked", "sources_rules"):
        assert gone not in POLICY


def test_parallel_domain_limit_respected():
    assert 0 < len(blocklist(POLICY)) <= 10 and len(POLICY["sources"]["blocklist"]) <= 10
