"""Answers with their questions: what the extractor returns, how it is cleaned, and what the store saves. No keys or network."""

from types import SimpleNamespace as NS

from claimcheck.agents.stages import build_record
from claimcheck.policy import load_policy
from claimcheck.schemas import ClaimRecord, ExtractedClaim, ExtractionResult
from claimcheck.store import SupabaseStore

POLICY = load_policy()
EC = NS(policy=POLICY, listed_people=[], creator=None, log=lambda *a, **k: None)


def raw(**kw):
    return {"start_ts": "04:31", "question": "How was NPCI set up and funded?", "question_kind": "asked", "asked_by": "Host",
            "speaker": "Sohini Rajola", "claim": "NPCI was formed by the RBI and the Indian Banks' Association with Rs 100 crore from ten banks.",
            "context_quote": "...", "statement_context": "Discussing NPCI's origins", "statement_type": "factual_claim",
            "pestle_area": "economic", "topics": ["npci"], "policy_tier": "normal", **kw}


def test_the_extractor_must_return_the_question_with_every_answer():
    item = ExtractionResult.model_json_schema()["$defs"]["ExtractedStatement"]
    assert {"question", "question_kind", "asked_by", "speaker", "claim"} <= set(item["required"])
    assert item["properties"]["question_kind"]["enum"] == ["asked", "implied"]
    assert "answer" in item["properties"]["claim"]["description"]


def test_build_record_carries_the_question_and_cleans_it():
    rec = build_record(0, raw(question="  How was   NPCI set up\n and funded? "), EC, log=False)
    assert rec.claim.question == "How was NPCI set up and funded?"
    assert rec.claim.asked_by == "Host" and rec.claim.question_kind == "asked" and rec.claim.speaker == "Sohini Rajola"


def test_an_implied_question_has_no_asker():
    rec = build_record(0, raw(question_kind="implied", asked_by="Host"), EC, log=False)
    assert rec.claim.asked_by == "" and rec.claim.question_kind == "implied"


def test_an_answer_without_a_question_is_still_kept_for_older_rows():
    rec = build_record(0, {k: v for k, v in raw().items() if k not in ("question", "question_kind", "asked_by")}, EC, log=False)
    assert rec is not None and rec.claim.question == "" and rec.claim.question_kind is None


class FakeTable:
    def __init__(self, sink):
        self.sink = sink

    def upsert(self, row, **kw):
        self.sink.append(row)
        return self

    def execute(self):
        return NS(data=[])


def saved_row(rec):
    sink = []
    store = SupabaseStore.__new__(SupabaseStore)
    store.db = NS(table=lambda name: FakeTable(sink))
    store._upsert_claim("ep1", rec)
    return sink[0]


def test_the_store_saves_the_question_with_the_answer():
    row = saved_row(build_record(3, raw(), EC, log=False))
    assert row["question"] == "How was NPCI set up and funded?" and row["asked_by"] == "Host" and row["question_kind"] == "asked"


def test_the_store_hides_the_question_when_the_answer_is_outside_the_content_policy():
    rec = build_record(3, raw(policy_tier="never"), EC, log=False)
    assert rec.not_checked_reason == "outside_policy"
    row = saved_row(rec)
    assert row["claim_text"].startswith("[Not shown") and row["question"] is None and row["asked_by"] is None and row["question_kind"] is None


# --- Answers appear as the model writes them ----------------------------------------------------------------

def test_each_answer_is_saved_with_its_question_as_soon_as_its_object_closes():
    import asyncio
    import json

    from claimcheck.agents.streaming import StatementStreamer

    saved, updates = [], []

    class Store:
        async def save_statement(self, episode_id, rec):
            saved.append(rec)

        async def update_episode(self, episode_id, fields):
            updates.append(fields)

    ec = NS(policy=POLICY, listed_people=[], creator=None, log=lambda *a, **k: None, store=Store(), episode_id="ep1",
            duration_s=3600, steps=[])
    first = raw(question="How was NPCI set up and funded?")
    second = raw(start_ts="05:48", question="Does NPCI pay dividends?", speaker="Sohini Rajola", claim="NPCI pays no dividends.")
    doc = json.dumps({"claims": [first, second], "sections": [], "summary": "A panel."})
    cut = doc.index('"Does NPCI')  # inside the second answer: only the first has closed

    def event(text):
        return NS(author="extractor", partial=True, content=NS(parts=[NS(text=text, thought=False)]))

    async def run():
        s = StatementStreamer(ec)
        await s.on_event(event(doc[:cut]))
        assert [r.claim.question for r in saved] == ["How was NPCI set up and funded?"]  # on screen before the model is done
        await s.on_event(event(doc[cut:]))
        return s

    s = asyncio.run(run())
    assert [r.claim.question for r in saved] == ["How was NPCI set up and funded?", "Does NPCI pay dividends?"]
    assert saved[0].claim.asked_by == "Host" and saved[1].start_s == 348 and s.saved == 2
