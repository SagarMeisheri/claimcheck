"""Persistence: Supabase.

Only code writes to the database; LLM agents never get a write tool.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Protocol

from .config import Settings
from .schemas import ClaimRecord, FinalVerdict, GuardrailEvent, verification_status


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
    async def add_channel(self, row: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def create_episode(self, row: dict[str, Any]) -> str: ...
    async def update_episode(self, episode_id: str, fields: dict[str, Any]) -> None: ...
    async def match_verdict(self, embedding: list[float], threshold: float, max_age_days: int) -> Optional[tuple[str, FinalVerdict]]: ...
    async def save_statement(self, episode_id: str, rec: ClaimRecord) -> None: ...
    async def clear_unverified_statements(self, episode_id: str) -> None: ...
    async def save_results(self, episode_id: str, claims: list[ClaimRecord], embeddings: dict[int, list[float]], cached_ids: dict[int, str], fast_model: str, judge_model: str) -> None: ...
    async def save_guardrail_events(self, episode_id: str, events: list[GuardrailEvent]) -> None: ...
    # On-demand verification of one claim
    async def get_claim_for_verification(self, claim_id: str) -> Optional[dict[str, Any]]: ...
    async def start_claim_verification(self, claim_id: str) -> bool: ...
    async def set_claim_status(self, claim_id: str, status: str, error: Optional[str] = None) -> None: ...
    async def save_claim_verdict(self, claim_id: str, verdict: FinalVerdict, cached_id: Optional[str], embedding: Optional[list[float]], judge_model: str) -> str: ...
    async def add_episode_cost(self, episode_id: str, usd: float, tokens_in: int, tokens_out: int) -> None: ...
    async def refresh_episode_after_verify(self, episode_id: str, pending: bool) -> None: ...


class SupabaseStore:
    """Writes with the service-role key. Table definitions: supabase/migrations/0001_init.sql."""

    def __init__(self, settings: Settings) -> None:
        from supabase import create_client

        self.db = create_client(settings.supabase_url, settings.supabase_service_key)

    async def get_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]:
        r = self.db.table("channels").select("*").eq("youtube_channel_id", youtube_channel_id).limit(1).execute()
        return r.data[0] if r.data else None

    async def add_channel(self, row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Creates a channel row (a no-op if it already exists) and returns it."""
        self.db.table("channels").upsert(row, on_conflict="youtube_channel_id", ignore_duplicates=True).execute()
        return await self.get_channel(row["youtube_channel_id"])

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

    def _insert_verdict(self, v: FinalVerdict, judge_model: str) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        vrow = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning,
                "evidence_grade": v.evidence_grade, "model": judge_model, "escalated": v.escalated,
                "score": v.score, "correction": v.correction or None,
                "review_status": v.review_status, "downgrades": v.downgrades,
                "recheck_after": (now + dt.timedelta(days=90)).isoformat()}
        verdict_id = self.db.table("verdicts").insert(vrow).execute().data[0]["id"]
        if v.citations:
            self.db.table("citations").insert([{**c.model_dump(), "verdict_id": verdict_id} for c in v.citations]).execute()
        return verdict_id

    async def save_results(self, episode_id, claims, embeddings, cached_ids, fast_model, judge_model):
        for rec in claims:
            verdict_id = cached_ids.get(rec.index)
            if rec.verdict is not None and verdict_id is None:
                verdict_id = self._insert_verdict(rec.verdict, judge_model)
            self._upsert_claim(episode_id, rec, verdict_id, embeddings.get(rec.index))

    def _upsert_claim(self, episode_id: str, rec: ClaimRecord, verdict_id: Optional[str], embedding: Optional[list[float]]) -> None:
        """Inserts a claim row unless the (episode, idx) row already exists (it may have been streamed earlier)."""
        c = rec.claim
        # Never-check claims (e.g. generalisations about a community) are not republished, even as text.
        hidden = rec.not_checked_reason == "outside_policy"
        self.db.table("claims").upsert({
            "episode_id": episode_id, "idx": rec.index, "start_s": rec.start_s, "speaker": c.speaker,
            "claim_text": "[Not shown: outside the content policy]" if hidden else c.claim,
            "context_quote": None if hidden else c.context_quote, "pestle_area": c.pestle_area,
            "topic": c.topic, "claim_type": c.claim_type, "policy_tier": rec.effective_tier,
            "checkworthiness": rec.checkworthiness, "not_checked_reason": rec.not_checked_reason,
            "refers_to_visual": c.refers_to_visual, "embedding": embedding,
            "verdict_id": verdict_id, "statement_type": c.statement_type,
            "tag_note": None if hidden else (c.tag_note or None), "verification_status": verification_status(rec),
            "verify_error": "Couldn't be verified during the first pass. Try again." if verification_status(rec) == "failed" else None,
        }, on_conflict="episode_id,idx", ignore_duplicates=True).execute()

    async def save_statement(self, episode_id, rec):
        """Saves one statement while the extractor is still running (no verdict yet)."""
        self._upsert_claim(episode_id, rec, None, None)

    async def clear_unverified_statements(self, episode_id):
        """Before a (re)run: drops statements left by an earlier attempt, keeping any that have a verdict."""
        self.db.table("claims").delete().eq("episode_id", episode_id).is_("verdict_id", "null").execute()

    # --- On-demand verification ------------------------------------------------------------------

    async def get_claim_for_verification(self, claim_id):
        r = (self.db.table("claims")
             .select("id, idx, episode_id, start_s, speaker, claim_text, context_quote, pestle_area, topic, claim_type, "
                     "statement_type, policy_tier, checkworthiness, not_checked_reason, refers_to_visual, verdict_id, "
                     "verification_status, verify_requested_at, "
                     "episodes(id, youtube_video_id, title, status, cost_usd, tokens_in, tokens_out, channels(track))")
             .eq("id", claim_id).limit(1).execute())
        return r.data[0] if r.data else None

    async def start_claim_verification(self, claim_id):
        """Moves a claim to 'verifying' only if no other run holds it. Returns False if it was taken."""
        r = (self.db.table("claims").update({"verification_status": "verifying", "verify_error": None})
             .eq("id", claim_id).in_("verification_status", ["queued", "not_requested", "failed"]).execute())
        return bool(r.data)

    async def set_claim_status(self, claim_id, status, error=None):
        self.db.table("claims").update({"verification_status": status, "verify_error": error}).eq("id", claim_id).execute()

    async def save_claim_verdict(self, claim_id, verdict, cached_id, embedding, judge_model):
        verdict_id = cached_id or self._insert_verdict(verdict, judge_model)
        fields: dict[str, Any] = {
            "verdict_id": verdict_id, "not_checked_reason": None, "verify_error": None,
            "verification_status": "awaiting_review" if verdict.review_status == "pending" else "verified",
        }
        if embedding is not None:
            fields["embedding"] = embedding
        self.db.table("claims").update(fields).eq("id", claim_id).execute()
        return verdict_id

    async def add_episode_cost(self, episode_id, usd, tokens_in, tokens_out):
        row = self.db.table("episodes").select("cost_usd, tokens_in, tokens_out").eq("id", episode_id).limit(1).execute().data
        cur = row[0] if row else {}
        self.db.table("episodes").update({
            "cost_usd": round(float(cur.get("cost_usd") or 0) + usd, 4),
            "tokens_in": int(cur.get("tokens_in") or 0) + tokens_in,
            "tokens_out": int(cur.get("tokens_out") or 0) + tokens_out,
        }).eq("id", episode_id).execute()

    async def refresh_episode_after_verify(self, episode_id, pending):
        self.db.rpc("recompute_episode_tally", {"p_episode_id": episode_id}).execute()
        if pending:  # hidden until a reviewer signs it off, same as during a run
            self.db.table("episodes").update({"status": "in_review"}).eq("id", episode_id).eq("status", "done").execute()

    def reset_interrupted_verifications(self) -> None:
        """After a restart, on-demand runs that were in memory can never finish: let users retry them."""
        self.db.table("claims").update({"verification_status": "failed", "verify_error": "Interrupted. Try again."}
                                       ).in_("verification_status", ["queued", "verifying"]).execute()

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
