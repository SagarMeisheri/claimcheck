"""Statement tagging and on-demand verification (no keys or network needed)."""

import asyncio

import pytest

from claimcheck.agents import on_demand
from claimcheck.agents.on_demand import precheck, record_from_row, run_claim_verification
from claimcheck.agents.stages import classify_statement
from claimcheck.config import Settings
from claimcheck.context import BudgetExceeded, get_context
from claimcheck.policy import load_policy
from claimcheck.schemas import ClaimRecord, ExtractedClaim, FinalVerdict, verification_status

POLICY = load_policy()


def stmt(text="India's GDP grew 7.4 per cent in FY2025-26.", stype="factual_claim", topic="gdp", tier="normal", **kw):
    return ExtractedClaim(start_ts="01:00", speaker="Host", claim=text, context_quote=text, pestle_area="economic",
                          topic=topic, statement_type=stype, policy_tier=tier, **kw)


# --- Tagging -------------------------------------------------------------------------------
def test_statement_type_and_legacy_claim_type_stay_in_step():
    assert stmt(stype="forecast").claim_type == "prediction"
    assert stmt(stype="hearsay").claim_type == "opinion"
    assert stmt(stype="factual_claim").claim_type == "fact"
    # Old rows / old model output with only claim_type still work.
    old = ExtractedClaim(start_ts="1:00", speaker="H", claim="x", context_quote="x", pestle_area="economic",
                         topic="gdp", claim_type="prediction", policy_tier="normal")
    assert old.statement_type == "forecast" and not old.verifiable
    # statement_type wins when the two disagree.
    assert ExtractedClaim.model_validate({**stmt().model_dump(), "claim_type": "opinion"}).claim_type == "fact"


def test_only_factual_claims_are_verifiable():
    assert classify_statement(stmt(), POLICY) == ("normal", None)
    for t in ("opinion", "forecast", "analogy", "loaded_language", "hearsay", "other"):
        tier, reason = classify_statement(stmt(stype=t), POLICY)
        assert reason == t and tier == "never"


def test_never_topics_are_redacted_for_every_type():
    assert classify_statement(stmt(topic="community_generalisation"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(stype="opinion", topic="religious_belief"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(stype="opinion", tier="never"), POLICY)[1] == "outside_policy"


def _records(n):
    return [ClaimRecord(index=i, start_s=i * 60, claim=stmt(f"claim {i}"), effective_tier="normal") for i in range(n)]


def test_policy_only_verifies_factual_claims():
    assert POLICY["on_demand"]["statement_types"] == ["factual_claim"]


def test_verification_status_mapping():
    r = _records(1)[0]
    r.verdict = FinalVerdict(verdict="false", confidence=0.9, reasoning="x", review_status="pending")
    assert verification_status(r) == "awaiting_review"
    r.verdict.review_status = "not_needed"
    assert verification_status(r) == "verified"
    r.verdict = None
    r.not_checked_reason = "budget"
    assert verification_status(r) == "failed"
    r.not_checked_reason = "outside_policy"
    assert verification_status(r) == "not_eligible"


# --- On-demand precheck ----------------------------------------------------------------------
SETTINGS = Settings(max_cost_usd_per_episode=3.0)  # pinned: a local .env must not change the tests


def row(**kw):
    base = {"id": "c1", "idx": 3, "episode_id": "e1", "start_s": 3725, "speaker": "Guest", "claim_text": "GDP grew 7.4%",
            "context_quote": None, "pestle_area": "economic", "topic": "gdp", "claim_type": "fact",
            "statement_type": "factual_claim", "policy_tier": "normal", "checkworthiness": 0.6, "not_checked_reason": None,
            "refers_to_visual": False, "verdict_id": None, "verification_status": "queued",
            "episodes": {"id": "e1", "youtube_video_id": "vid", "title": "T", "status": "done", "cost_usd": 0.5,
                         "tokens_in": 0, "tokens_out": 0, "channels": {"track": "politics"}}}
    eps = kw.pop("episodes", {})
    base.update(kw)
    base["episodes"] = {**base["episodes"], **eps}
    return base


def test_precheck_allows_queued_factual_claim():
    assert precheck(row(), SETTINGS, POLICY) == (True, "", 200)
    assert precheck(row(verification_status="failed"), SETTINGS, POLICY)[0]


@pytest.mark.parametrize("kw, words", [
    ({"statement_type": "opinion"}, "Only claims"),
    ({"policy_tier": "never"}, "content policy"),
    ({"verification_status": "verified"}, "Already verified"),
    ({"verification_status": "awaiting_review"}, "reviewer"),
    ({"verification_status": "verifying"}, "Already being verified"),
    ({"episodes": {"cost_usd": 3.0}}, "budget"),
    ({"episodes": {"status": "processing"}}, "first pass"),
])
def test_precheck_rejections(kw, words):
    ok, msg, code = precheck(row(**kw), SETTINGS, POLICY)
    assert not ok and code == 409 and words in msg


def test_precheck_missing_claim():
    assert precheck(None, SETTINGS, POLICY)[2] == 404


def test_record_from_row_round_trips():
    rec = record_from_row(row())
    assert rec.claim.start_ts == "01:02:05" and rec.start_s == 3725
    assert rec.claim.context_quote == "GDP grew 7.4%" and rec.claim.verifiable and rec.effective_tier == "normal"


# --- On-demand run (fake store, fake verifier) ------------------------------------------------
class FakeStore:
    def __init__(self, r):
        self.row = r
        self.saved = []
        self.status = []
        self.cost = []
        self.refreshed = []

    async def get_claim_for_verification(self, claim_id):
        return self.row

    async def set_claim_status(self, claim_id, status, error=None):
        self.status.append((status, error))

    async def save_claim_verdict(self, claim_id, verdict, cached_id, embedding, judge_model):
        self.saved.append((verdict.verdict, verdict.review_status, cached_id))
        return cached_id or "v-new"

    async def add_episode_cost(self, episode_id, usd, tin, tout):
        self.cost.append(usd)
        self.row["episodes"]["cost_usd"] += usd

    async def refresh_episode_after_verify(self, episode_id, pending):
        self.refreshed.append(pending)

    async def save_guardrail_events(self, episode_id, events):
        pass


def _fake_verifier(monkeypatch, verdict="supported", review="not_needed", cost=0.2, cached=None, raises=None):
    async def fake(rec, meta):
        ec = get_context()
        assert ec.track == "politics" and meta["video_title"] == "T"
        ec.budget.add(cost)
        if raises:
            raise raises
        return FinalVerdict(verdict=verdict, confidence=0.9, reasoning="r", review_status=review,
                            from_cache=bool(cached)), cached, [0.0]
    import claimcheck.agents.verifier as verifier
    monkeypatch.setattr(verifier, "verify_claim", fake)


def test_run_saves_verdict_and_charges_the_video(monkeypatch):
    _fake_verifier(monkeypatch)
    store = FakeStore(row())
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=store))
    assert res["status"] == "verified" and store.saved == [("supported", "not_needed", None)]
    assert store.refreshed == [False] and store.cost == [pytest.approx(0.2)]


def test_run_keeps_false_verdicts_for_review(monkeypatch):
    _fake_verifier(monkeypatch, verdict="false", review="pending")
    store = FakeStore(row())
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=store))
    assert res["status"] == "awaiting_review" and store.refreshed == [True]


def test_run_reuses_cached_verdict(monkeypatch):
    _fake_verifier(monkeypatch, cost=0.0, cached="v-old")
    store = FakeStore(row())
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=store))
    assert res["from_cache"] and store.saved[0][2] == "v-old"


def test_run_stops_at_the_video_cost_cap(monkeypatch):
    _fake_verifier(monkeypatch)
    store = FakeStore(row(episodes={"cost_usd": 3.0}))
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and "budget" in res["reason"] and not store.saved


def test_run_records_budget_error_and_cost(monkeypatch):
    _fake_verifier(monkeypatch, cost=0.4, raises=RuntimeError("wrapped") )
    store = FakeStore(row())
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and store.status[-1][0] == "failed" and "Try again" in store.status[-1][1]
    assert store.cost == [pytest.approx(0.4)]  # spend is recorded even when verification fails

    def budget_error():
        try:
            raise BudgetExceeded("cap")
        except BudgetExceeded as e:
            raise RuntimeError("plugin failed") from e
    try:
        budget_error()
    except RuntimeError as e:
        err = e
    _fake_verifier(monkeypatch, raises=err)
    res = asyncio.run(run_claim_verification("c1", settings=SETTINGS, store=FakeStore(row())))
    assert "budget" in res["reason"]


def test_runs_for_one_video_are_serialised(monkeypatch):
    active = {"n": 0, "max": 0}

    async def slow(rec, meta):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.01)
        active["n"] -= 1
        return FinalVerdict(verdict="supported", confidence=0.9, reasoning="r"), None, None
    import claimcheck.agents.verifier as verifier
    monkeypatch.setattr(verifier, "verify_claim", slow)
    on_demand._episode_locks.clear()

    async def both():
        store = FakeStore(row())
        await asyncio.gather(run_claim_verification("c1", settings=SETTINGS, store=store),
                             run_claim_verification("c2", settings=SETTINGS, store=store))
    asyncio.run(both())
    assert active["max"] == 1


def test_extractor_schema_requires_statement_type():
    from claimcheck.schemas import ExtractionResult
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert "statement_type" in item["required"] and "claim_type" not in item["properties"]


# --- Streaming ------------------------------------------------------------------------------
def _stmt_json(text, stype="factual_claim", ts="01:00"):
    import json
    return json.dumps({"start_ts": ts, "speaker": "Host", "claim": text, "context_quote": text, "statement_type": stype,
                       "tag_note": "", "pestle_area": "economic", "topics": ["gdp"], "policy_tier": "normal", "refers_to_visual": False})


def test_object_stream_finds_statements_in_any_chunking():
    from claimcheck.agents.streaming import ObjectStream
    doc = '{"claims": [' + ", ".join(_stmt_json(f'a "quoted" {{brace}} [x] \\ claim {i}') for i in range(3)) + '], "summary": "it [is] {fine}"}'
    for size in (1, 7, 50, len(doc)):
        s = ObjectStream()
        got = []
        for k in range(0, len(doc), size):
            got += s.feed(doc[k:k + size])
        assert [g["claim"] for g in got] == [f'a "quoted" {{brace}} [x] \\ claim {i}' for i in range(3)], size


def test_object_stream_waits_for_the_closing_brace():
    from claimcheck.agents.streaming import ObjectStream
    s = ObjectStream()
    assert s.feed('{"claims": [' + _stmt_json("one") + ", " + _stmt_json("two")[:40]) == [__import__("json").loads(_stmt_json("one"))]


def test_streamer_saves_each_statement_once_and_tags_it():
    from types import SimpleNamespace as NS
    from claimcheck.agents.streaming import StatementStreamer

    saved, updates = [], []

    class Store:
        async def save_statement(self, episode_id, rec): saved.append(rec)
        async def update_episode(self, episode_id, fields): updates.append(fields)

    ec = NS(episode_id="e1", policy=POLICY, store=Store(), duration_s=600, log=lambda *a, **k: None)

    def ev(text, partial=True, author="extractor"):
        return NS(author=author, partial=partial, content=NS(parts=[NS(text=text, thought=False)]))

    doc = '{"claims": [' + _stmt_json("GDP grew 7%") + ", " + _stmt_json("this is ridiculous", "opinion", "05:00") + "]}"

    async def go():
        st = StatementStreamer(ec)
        for k in range(0, len(doc), 25):
            await st.on_event(ev(doc[k:k + 25]))
        await st.on_event(ev(doc, partial=False))        # the accumulated final reply is ignored
        await st.on_event(ev('{"claims": [' + _stmt_json("x") + "]}", author="triage"))  # other agents too
        await st.finish()
    asyncio.run(go())
    assert [r.claim.statement_type for r in saved] == ["factual_claim", "opinion"]
    assert [r.index for r in saved] == [0, 1] and saved[1].not_checked_reason == "opinion"
    assert [u for u in updates if "statement_counts" in u][-1]["statement_counts"] == {"factual_claim": 1, "opinion": 1}


def test_budget_counts_streamed_usage_once():
    from types import SimpleNamespace as NS
    from claimcheck.context import Budget
    from claimcheck.guardrails import budget as b
    from claimcheck.guardrails.budget import BudgetPlugin

    ec = NS(budget=Budget(cap_usd=10), settings=NS(prices={"x": (1.0, 1.0)}), log=lambda *a, **k: None)
    b.get_context = lambda: ec  # type: ignore[assignment]
    resp = lambda partial, out: NS(partial=partial, model_version="x", usage_metadata=NS(prompt_token_count=1000, candidates_token_count=out, thoughts_token_count=0))
    plugin, cb = BudgetPlugin(), NS(invocation_id="i", agent_name="a")

    async def go():
        for out in (10, 20, 30):  # running totals from three partial pieces
            await plugin.after_model_callback(callback_context=cb, llm_response=resp(True, out))
        await plugin.after_model_callback(callback_context=cb, llm_response=resp(False, 30))
    asyncio.run(go())
    assert (ec.budget.tokens_in, ec.budget.tokens_out) == (1000, 30)


# --- Subject tags ---------------------------------------------------------------------------
def test_normalize_topics_is_free_form():
    from claimcheck.policy import normalize_topics
    assert normalize_topics(["Roman Coins", "Maritime-Trade", "jobs"], POLICY) == ["roman_coins", "maritime_trade"]  # max 2
    assert normalize_topics(["  Middle class! "], POLICY) == ["middle_class"]
    assert normalize_topics(["gdp", "GDP"], POLICY) == ["gdp"]
    assert normalize_topics("gdp", POLICY) == ["gdp"] and normalize_topics(None, POLICY) == ["general"]


def test_any_never_topic_redacts_and_any_stricter_topic_raises_tier():
    c = stmt(topic="gdp", topics=["gdp", "religious_belief"])
    assert classify_statement(c, POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(topic="gdp", topics=["gdp", "health"]), POLICY)[0] == "stricter"


def test_extractor_schema_asks_for_topics_list():
    from claimcheck.schemas import ExtractionResult
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert "topics" in item["required"] and "topic" not in item["properties"]
