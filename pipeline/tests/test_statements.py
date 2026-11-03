"""Statement tagging, streaming and the cost cap (no keys or network needed). Sources: test_sources.py."""

import asyncio

import pytest

from claimcheck.agents.stages import classify_statement
from claimcheck.config import Settings
from claimcheck.policy import load_policy
from claimcheck.schemas import ClaimRecord, ExtractedClaim, sources_status

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
    assert old.statement_type == "forecast"
    # statement_type wins when the two disagree.
    assert ExtractedClaim.model_validate({**stmt().model_dump(), "claim_type": "opinion"}).claim_type == "fact"


@pytest.mark.parametrize("legacy", ["hearsay", "analogy", "loaded_language"])
def test_legacy_tags_that_characterise_a_speaker_become_other(legacy):
    c = ExtractedClaim.model_validate({**stmt().model_dump(), "statement_type": legacy})
    assert c.statement_type == "other" and c.claim_type == "anecdote"
    assert ExtractedClaim.model_validate({**stmt().model_dump(), "policy_tier": "stricter"}).policy_tier == "normal"


def test_every_statement_type_can_have_sources():
    for t in ("factual_claim", "opinion", "forecast", "other"):
        assert classify_statement(stmt(stype=t), POLICY) == ("normal", None)


def test_never_topics_are_redacted_for_every_type():
    assert classify_statement(stmt(topic="community_generalisation"), POLICY) == ("never", "outside_policy")
    assert classify_statement(stmt(stype="opinion", topic="religious_belief"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(stype="opinion", tier="never"), POLICY)[1] == "outside_policy"
    assert classify_statement(stmt(topic="gdp", topics=["gdp", "religious_belief"]), POLICY)[1] == "outside_policy"


def test_sources_status_for_new_statements():
    claim = ClaimRecord(index=0, start_s=0, claim=stmt(), effective_tier="normal")
    assert sources_status(claim) == "not_requested"
    assert sources_status(claim.model_copy(update={"not_checked_reason": "outside_policy"})) == "not_eligible"
    assert sources_status(ClaimRecord(index=1, start_s=0, claim=stmt(stype="opinion"), effective_tier="normal")) == "not_requested"


def test_extractor_schema_requires_statement_type_and_has_no_characterisation():
    from claimcheck.schemas import ExtractionResult
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert "statement_type" in item["required"] and "claim_type" not in item["properties"]
    assert "tag_note" not in item["properties"]
    assert set(item["properties"]["statement_type"]["enum"]) == {"factual_claim", "opinion", "forecast", "advice", "story", "question", "other"}


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
    assert [r.index for r in saved] == [0, 1] and saved[1].not_checked_reason is None
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
    assert s.prices["gemini-3.8-flash"] == (1.50, 7.50)
    monkeypatch.setenv("CLAIMCHECK_PRICES_JSON", '{"gemini-3.8-flash": [0.75, 3.75]}')
    assert Settings().prices["gemini-3.8-flash"] == (0.75, 3.75)


def test_podcast_types_questions_and_stories_have_no_sources():
    assert stmt(stype="advice").claim_type == "opinion"
    assert stmt(stype="story").claim_type == "anecdote" and stmt(stype="question").claim_type == "anecdote"
    rec = lambda t: ClaimRecord(index=0, start_s=0, claim=stmt(stype=t), effective_tier="normal")
    assert sources_status(rec("advice")) == "not_requested"
    assert sources_status(rec("question")) == "not_eligible" and sources_status(rec("story")) == "not_eligible"
