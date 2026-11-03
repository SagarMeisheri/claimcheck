"""Statement tagging, streaming, the cost cap and sources on request (no keys or network needed)."""

import asyncio

import pytest

from claimcheck.agents import sources_on_demand
from claimcheck.agents.sources_on_demand import precheck, record_from_row, run_claim_sources
from claimcheck.agents.stages import classify_statement
from claimcheck.config import Settings
from claimcheck.context import BudgetExceeded, get_context
from claimcheck.policy import load_policy
from claimcheck.schemas import CheckedSource, ClaimRecord, ExtractedClaim, sources_status

POLICY = load_policy()


def stmt(text="India's GDP grew 7.4 per cent in FY2025-26.", stype="factual_claim", topic="gdp", tier="normal", **kw):
    return ExtractedClaim(start_ts="01:00", speaker="Host", claim=text, context_quote=text, pestle_area="economic",
                          topic=topic, statement_type=stype, policy_tier=tier, **kw)


# --- Tagging -------------------------------------------------------------------------------
def test_statement_type_and_legacy_claim_type_stay_in_step():
    assert stmt(stype="forecast").claim_type == "prediction"
    assert stmt(stype="other").claim_type == "anecdote"
    assert stmt(stype="factual_claim").claim_type == "fact"
    # Old rows / old model output with only claim_type still work.
    old = ExtractedClaim(start_ts="1:00", speaker="H", claim="x", context_quote="x", pestle_area="economic",
                         topic="gdp", claim_type="prediction", policy_tier="normal")
    assert old.statement_type == "forecast" and not old.sourceable
    # statement_type wins when the two disagree.
    assert ExtractedClaim.model_validate({**stmt().model_dump(), "claim_type": "opinion"}).claim_type == "fact"


@pytest.mark.parametrize("legacy", ["hearsay", "analogy", "loaded_language"])
def test_legacy_tags_that_characterise_a_speaker_become_other(legacy):
    c = ExtractedClaim.model_validate({**stmt().model_dump(), "statement_type": legacy})
    assert c.statement_type == "other" and c.claim_type == "anecdote"
    assert ExtractedClaim.model_validate({**stmt().model_dump(), "policy_tier": "stricter"}).policy_tier == "normal"


def test_only_factual_claims_can_have_sources():
    assert classify_statement(stmt(), POLICY) == ("normal", None)
    for t in ("opinion", "forecast", "other"):
        assert classify_statement(stmt(stype=t), POLICY) == ("normal", t)


def test_never_topics_are_redacted_for_every_type():
    assert classify_statement(stmt(topic="community_generalisation"), POLICY) == ("never", "outside_policy")
    assert classify_statement(stmt(stype="opinion", topic="religious_belief"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(stype="opinion", tier="never"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(topic="gdp", topics=["gdp", "religious_belief"]), POLICY)[1] == "outside_policy"


def test_sources_status_for_new_statements():
    claim = ClaimRecord(index=0, start_s=0, claim=stmt(), effective_tier="normal")
    assert sources_status(claim) == "not_requested"
    assert sources_status(claim.model_copy(update={"not_checked_reason": "outside_policy"})) == "not_eligible"
    assert sources_status(ClaimRecord(index=1, start_s=0, claim=stmt(stype="opinion"), effective_tier="normal",
                                      not_checked_reason="opinion")) == "not_eligible"


def test_extractor_schema_requires_statement_type_and_has_no_characterisation():
    from claimcheck.schemas import ExtractionResult
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert "statement_type" in item["required"] and "claim_type" not in item["properties"]
    assert "tag_note" not in item["properties"]
    assert set(item["properties"]["statement_type"]["enum"]) == {"factual_claim", "opinion", "forecast", "other"}


def test_extractor_schema_asks_for_topics_list():
    from claimcheck.schemas import ExtractionResult
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert "topics" in item["required"] and "topic" not in item["properties"]


def test_normalize_topics_is_free_form():
    from claimcheck.policy import normalize_topics
    assert normalize_topics(["Roman Coins", "Maritime-Trade", "jobs"], POLICY) == ["roman_coins", "maritime_trade"]  # max 2
    assert normalize_topics(["  Middle class! "], POLICY) == ["middle_class"]
    assert normalize_topics(["gdp", "GDP"], POLICY) == ["gdp"]
    assert normalize_topics("gdp", POLICY) == ["gdp"] and normalize_topics(None, POLICY) == ["general"]


# --- Sources on request: precheck --------------------------------------------------------------
SETTINGS = Settings(max_cost_usd_per_episode=3.0)  # pinned: a local .env must not change the tests


def row(**kw):
    base = {"id": "c1", "idx": 3, "episode_id": "e1", "start_s": 3725, "speaker": "Guest", "claim_text": "GDP grew 7.4%",
            "context_quote": None, "pestle_area": "economic", "topic": "gdp", "topics": ["gdp"],
            "statement_type": "factual_claim", "policy_tier": "normal", "not_checked_reason": None,
            "refers_to_visual": False, "sources_status": "queued",
            "episodes": {"id": "e1", "youtube_video_id": "vid", "title": "T", "status": "done", "cost_usd": 0.5}}
    eps = kw.pop("episodes", {})
    base.update(kw)
    base["episodes"] = {**base["episodes"], **eps}
    return base


def test_precheck_allows_queued_factual_claim():
    assert precheck(row(), SETTINGS) == (True, "", 200)
    assert precheck(row(sources_status="failed"), SETTINGS)[0]
    assert precheck(row(sources_status="not_requested"), SETTINGS)[0]


@pytest.mark.parametrize("kw, words", [
    ({"statement_type": "opinion"}, "only be looked up for claims"),
    ({"policy_tier": "never"}, "content policy"),
    ({"sources_status": "done"}, "already been looked up"),
    ({"sources_status": "searching"}, "Already searching"),
    ({"sources_status": "not_eligible"}, "can't be looked up"),
    ({"episodes": {"cost_usd": 3.0}}, "budget"),
    ({"episodes": {"status": "processing"}}, "finished"),
])
def test_precheck_rejections(kw, words):
    ok, msg, code = precheck(row(**kw), SETTINGS)
    assert not ok and code == 409 and words in msg


def test_precheck_missing_claim():
    assert precheck(None, SETTINGS)[2] == 404


def test_record_from_row_round_trips():
    rec = record_from_row(row())
    assert rec.claim.start_ts == "01:02:05" and rec.start_s == 3725
    assert rec.claim.context_quote == "GDP grew 7.4%" and rec.claim.sourceable and rec.effective_tier == "normal"


# --- Sources on request: run (fake store, fake lookup) -----------------------------------------
class FakeStore:
    def __init__(self, r):
        self.row = r
        self.saved = []
        self.status = []
        self.cost = []

    async def get_claim_for_sources(self, claim_id):
        return self.row

    async def set_sources_status(self, claim_id, status, error=None):
        self.status.append((status, error))

    async def save_claim_sources(self, claim_id, sources):
        self.saved.append([s.url for s in sources])

    async def add_episode_cost(self, episode_id, usd, tin, tout):
        self.cost.append(usd)
        self.row["episodes"]["cost_usd"] += usd

    async def save_guardrail_events(self, episode_id, events):
        pass


SRC = CheckedSource(url="https://mospi.gov.in/a", title="MoSPI", tier=1, quote="GDP grew 7.4 per cent in 2025-26.")


def _fake_lookup(monkeypatch, sources=(SRC,), cost=0.2, raises=None):
    async def fake(rec, meta):
        ec = get_context()
        assert meta["video_title"] == "T" and ec.episode_id == "e1"
        ec.budget.add(cost)
        if raises:
            raise raises
        return list(sources)
    import claimcheck.agents.sources as sources_mod
    monkeypatch.setattr(sources_mod, "find_sources", fake)


def test_run_saves_sources_and_charges_the_video(monkeypatch):
    _fake_lookup(monkeypatch)
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "done" and res["sources"] == 1 and store.saved == [["https://mospi.gov.in/a"]]
    assert store.cost == [pytest.approx(0.2)]


def test_run_saves_an_empty_result_as_done(monkeypatch):
    _fake_lookup(monkeypatch, sources=())
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "done" and store.saved == [[]]


def test_run_stops_at_the_video_cost_cap(monkeypatch):
    _fake_lookup(monkeypatch)
    store = FakeStore(row(episodes={"cost_usd": 3.0}))
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and "budget" in res["reason"] and not store.saved


def test_run_records_errors_and_cost(monkeypatch):
    _fake_lookup(monkeypatch, cost=0.4, raises=RuntimeError("wrapped"))
    store = FakeStore(row())
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=store))
    assert res["status"] == "failed" and store.status[-1][0] == "failed" and "Try again" in store.status[-1][1]
    assert store.cost == [pytest.approx(0.4)]  # spend is recorded even when the lookup fails

    def budget_error():
        try:
            raise BudgetExceeded("cap")
        except BudgetExceeded as e:
            raise RuntimeError("plugin failed") from e
    try:
        budget_error()
    except RuntimeError as e:
        err = e
    _fake_lookup(monkeypatch, raises=err)
    res = asyncio.run(run_claim_sources("c1", settings=SETTINGS, store=FakeStore(row())))
    assert "budget" in res["reason"]


def test_runs_for_one_video_are_serialised(monkeypatch):
    active = {"n": 0, "max": 0}

    async def slow(rec, meta):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.01)
        active["n"] -= 1
        return []
    import claimcheck.agents.sources as sources_mod
    monkeypatch.setattr(sources_mod, "find_sources", slow)
    sources_on_demand._episode_locks.clear()

    async def both():
        store = FakeStore(row())
        await asyncio.gather(run_claim_sources("c1", settings=SETTINGS, store=store),
                             run_claim_sources("c2", settings=SETTINGS, store=store))
    asyncio.run(both())
    assert active["max"] == 1


# --- Streaming ------------------------------------------------------------------------------
def _stmt_json(text, stype="factual_claim", ts="01:00"):
    import json
    return json.dumps({"start_ts": ts, "speaker": "Host", "claim": text, "context_quote": text, "statement_type": stype,
                       "pestle_area": "economic", "topics": ["gdp"], "policy_tier": "normal", "refers_to_visual": False})


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
        await st.on_event(ev('{"claims": [' + _stmt_json("x") + "]}", author="someone_else"))  # other agents too
        await st.finish()
    asyncio.run(go())
    assert [r.claim.statement_type for r in saved] == ["factual_claim", "opinion"]
    assert [r.index for r in saved] == [0, 1] and saved[1].not_checked_reason == "opinion"
    assert [u for u in updates if "statement_counts" in u][-1]["statement_counts"] == {"factual_claim": 1, "opinion": 1}


# --- Cost cap ---------------------------------------------------------------------------------
def _plugin_with(ec):
    from claimcheck.guardrails import budget as b
    from claimcheck.guardrails.budget import BudgetPlugin
    b.get_context = lambda: ec  # type: ignore[assignment]
    return BudgetPlugin()


def test_budget_counts_streamed_usage_once():
    from types import SimpleNamespace as NS
    from claimcheck.context import Budget

    ec = NS(budget=Budget(cap_usd=10), settings=NS(prices={"x": (1.0, 1.0)}), log=lambda *a, **k: None)
    plugin, cb = _plugin_with(ec), NS(invocation_id="i", agent_name="a")
    resp = lambda partial, out: NS(partial=partial, model_version="x", usage_metadata=NS(
        prompt_token_count=1000, candidates_token_count=out, thoughts_token_count=0, tool_use_prompt_token_count=None))

    async def go():
        for out in (10, 20, 30):  # running totals from three partial pieces
            await plugin.after_model_callback(callback_context=cb, llm_response=resp(True, out))
        await plugin.after_model_callback(callback_context=cb, llm_response=resp(False, 30))
    asyncio.run(go())
    assert (ec.budget.tokens_in, ec.budget.tokens_out) == (1000, 30)


def test_budget_counts_agentic_video_tool_use_tokens():
    from types import SimpleNamespace as NS
    from claimcheck.context import Budget

    ec = NS(budget=Budget(cap_usd=10), settings=Settings(), log=lambda *a, **k: None)
    plugin, cb = _plugin_with(ec), NS(invocation_id="i", agent_name="extractor")
    usage = NS(prompt_token_count=1_000, tool_use_prompt_token_count=999_000, candidates_token_count=0, thoughts_token_count=0)
    asyncio.run(plugin.after_model_callback(callback_context=cb, llm_response=NS(partial=False, model_version="gemini-3.8-flash", usage_metadata=usage)))
    assert ec.budget.tokens_in == 1_000_000
    assert ec.budget.spent_usd == pytest.approx(1.50)  # 1M input tokens at the conservative 2027 Flash price


def test_prices_are_conservative_and_can_be_overridden(monkeypatch):
    s = Settings()
    assert s.prices["gemini-3.8-flash"] == (1.50, 7.50) and s.prices["flash-lite"] == (0.30, 2.50)
    monkeypatch.setenv("CLAIMCHECK_PRICES_JSON", '{"gemini-3.8-flash": [0.75, 3.75]}')
    assert Settings().prices["gemini-3.8-flash"] == (0.75, 3.75)
