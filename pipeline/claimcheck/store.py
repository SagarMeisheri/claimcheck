"""Persistence: Supabase.

Only code writes to the database; LLM agents never get a write tool.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Protocol

from .config import Settings
from .schemas import ClaimRecord, FinalVerdict, GuardrailEvent


def ts_to_seconds(ts: str) -> int:
    try:
        parts = [int(p) for p in ts.strip().split(":")]
    except ValueError:
        return 0
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


class Store(Protocol):
    async def get_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]: ...
    async def create_episode(self, row: dict[str, Any]) -> str: ...
    async def update_episode(self, episode_id: str, fields: dict[str, Any]) -> None: ...
    async def match_verdict(self, embedding: list[float], threshold: float, max_age_days: int) -> Optional[tuple[str, FinalVerdict]]: ...
    async def save_results(self, episode_id: str, claims: list[ClaimRecord], embeddings: dict[int, list[float]], cached_ids: dict[int, str], fast_model: str, judge_model: str) -> None: ...
    async def save_guardrail_events(self, episode_id: str, events: list[GuardrailEvent]) -> None: ...


class SupabaseStore:
    """Writes with the service-role key. Table definitions: supabase/migrations/0001_init.sql."""

    def __init__(self, settings: Settings) -> None:
        from supabase import create_client

        self.db = create_client(settings.supabase_url, settings.supabase_service_key)

    async def get_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]:
        r = self.db.table("channels").select("*").eq("youtube_channel_id", youtube_channel_id).limit(1).execute()
        return r.data[0] if r.data else None

    async def create_episode(self, row: dict[str, Any]) -> str:
        r = self.db.table("episodes").upsert(row, on_conflict="youtube_video_id").execute()
        return r.data[0]["id"]

    async def update_episode(self, episode_id: str, fields: dict[str, Any]) -> None:
        self.db.table("episodes").update(fields).eq("id", episode_id).execute()

    async def match_verdict(self, embedding, threshold, max_age_days):
        r = self.db.rpc("match_verdict", {"query_embedding": embedding, "similarity_threshold": threshold,
                                          "max_age_days": max_age_days}).execute()
        if not r.data:
            return None
        row = r.data[0]
        cits = self.db.table("citations").select("*").eq("verdict_id", row["verdict_id"]).execute().data
        fv = FinalVerdict(verdict=row["verdict"], confidence=row["confidence"], reasoning=row["reasoning"],
                          evidence_grade=row.get("evidence_grade") or "not_applicable",
                          citations=[{"url": c["url"], "title": c["title"] or "", "tier": c["tier"], "quote": c["quote"],
                                      "quote_check_passed": c["quote_check_passed"]} for c in cits],
                          from_cache=True, review_status=row["review_status"])
        return row["verdict_id"], fv

    async def save_results(self, episode_id, claims, embeddings, cached_ids, fast_model, judge_model):
        now = dt.datetime.now(dt.timezone.utc)
        for rec in claims:
            verdict_id = cached_ids.get(rec.index)
            if rec.verdict is not None and verdict_id is None:
                v = rec.verdict
                vrow = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning,
                        "evidence_grade": v.evidence_grade, "model": judge_model, "escalated": v.escalated,
                        "review_status": v.review_status, "downgrades": v.downgrades,
                        "recheck_after": (now + dt.timedelta(days=90)).isoformat()}
                verdict_id = self.db.table("verdicts").insert(vrow).execute().data[0]["id"]
                if v.citations:
                    self.db.table("citations").insert([{**c.model_dump(), "verdict_id": verdict_id} for c in v.citations]).execute()
            c = rec.claim
            # Never-check claims (e.g. generalisations about a community) are not republished, even as text.
            hidden = rec.not_checked_reason == "outside_policy"
            self.db.table("claims").insert({
                "episode_id": episode_id, "idx": rec.index, "start_s": rec.start_s, "speaker": c.speaker,
                "claim_text": "[Not shown: outside the content policy]" if hidden else c.claim,
                "context_quote": None if hidden else c.context_quote, "pestle_area": c.pestle_area,
                "topic": c.topic, "claim_type": c.claim_type, "policy_tier": rec.effective_tier,
                "checkworthiness": rec.checkworthiness, "not_checked_reason": rec.not_checked_reason,
                "refers_to_visual": c.refers_to_visual, "embedding": embeddings.get(rec.index),
                "verdict_id": verdict_id,
            }).execute()

    async def save_guardrail_events(self, episode_id, events):
        if events:
            self.db.table("guardrail_events").insert([{"episode_id": episode_id, "stage": e.stage, "rule": e.rule,
                                                       "action": e.action, "detail": e.detail, "claim_idx": e.claim_index}
                                                      for e in events]).execute()


def make_store(settings: Settings) -> Any:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see pipeline/.env.example).")
    return SupabaseStore(settings)


async def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    if not texts:
        return []
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key or None)
    res = await client.aio.models.embed_content(
        model=settings.embedding_model, contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=settings.embedding_dims, task_type="SEMANTIC_SIMILARITY"),
    )
    return [e.values for e in res.embeddings]
