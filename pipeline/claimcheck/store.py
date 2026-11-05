"""Persistence: Supabase.

Only code writes to the database; LLM agents never get a write tool.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Protocol

from .config import Settings
from .schemas import ClaimRecord, GuardrailEvent, Source, sources_status


def ts_to_seconds(ts: str) -> int:
    try:
        parts = [int(p) for p in ts.strip().split(":")]
    except ValueError:
        return 0
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def _ago(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Store(Protocol):
    async def get_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]: ...
    async def add_channel(self, row: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def create_episode(self, row: dict[str, Any]) -> str: ...
    async def update_episode(self, episode_id: str, fields: dict[str, Any]) -> None: ...
    async def save_statement(self, episode_id: str, rec: ClaimRecord) -> None: ...
    async def save_statements(self, episode_id: str, claims: list[ClaimRecord]) -> None: ...
    async def clear_statements_without_sources(self, episode_id: str) -> None: ...
    async def save_guardrail_events(self, episode_id: str, events: list[GuardrailEvent]) -> None: ...
    # Sources
    async def get_claim_for_sources(self, claim_id: str) -> Optional[dict[str, Any]]: ...
    async def get_episode(self, episode_id: str) -> Optional[dict[str, Any]]: ...
    async def list_batch_claims(self, episode_id: str) -> list[dict[str, Any]]: ...
    async def list_claims_for_qa(self, episode_id: str) -> list[dict[str, Any]]: ...
    async def start_claim_sources(self, claim_id: str) -> bool: ...
    async def set_sources_status(self, claim_id: str, status: str, error: Optional[str] = None) -> None: ...
    async def save_claim_sources(self, claim_id: str, sources: list[Source], summary: str = "", match: str = "", *,
                                 counter: Optional[list[Source]] = None, counter_summary: str = "",
                                 route: Optional[str] = None, triage: Optional[dict[str, Any]] = None) -> None: ...
    async def save_sources_route(self, claim_id: str, route: str, triage: Optional[dict[str, Any]] = None) -> None: ...
    # Creators, speakers, sections
    async def get_creator_by_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]: ...
    async def get_creator(self, creator_id: str) -> Optional[dict[str, Any]]: ...
    async def get_speaker(self, key: str) -> Optional[dict[str, Any]]: ...
    async def save_speaker(self, row: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def save_episode_speakers(self, episode_id: str, rows: list[dict[str, Any]]) -> None: ...
    async def get_episode_speakers(self, episode_id: str) -> list[dict[str, Any]]: ...
    async def save_sections(self, episode_id: str, sections: list[dict[str, Any]]) -> None: ...
    async def list_claims_missing_summary(self, limit: int) -> list[dict[str, Any]]: ...
    async def save_sources_summary(self, claim_id: str, summary: str, match: str = "") -> None: ...
    async def add_episode_cost(self, episode_id: str, usd: float, tokens_in: int, tokens_out: int) -> None: ...
    # YouTube API data upkeep
    async def list_stale_episodes(self, days: int, limit: int = 500) -> list[dict[str, Any]]: ...
    async def list_stale_channels(self, days: int, limit: int = 500) -> list[dict[str, Any]]: ...
    async def refresh_episode_metadata(self, episode_id: str, fields: dict[str, Any]) -> None: ...
    async def mark_episode_removed(self, episode_id: str) -> None: ...
    async def refresh_channel(self, channel_id: str, fields: dict[str, Any]) -> None: ...


class SupabaseStore:
    """Writes with the service-role key. Table definitions: supabase/migrations/."""

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

    async def get_creator_by_channel(self, youtube_channel_id: str) -> Optional[dict[str, Any]]:
        if not youtube_channel_id:
            return None
        r = self.db.table("creators").select("*").contains("youtube_channel_ids", [youtube_channel_id]).limit(1).execute()
        return r.data[0] if r.data else None

    async def get_creator(self, creator_id: str) -> Optional[dict[str, Any]]:
        if not creator_id:
            return None
        r = self.db.table("creators").select("*").eq("id", creator_id).limit(1).execute()
        return r.data[0] if r.data else None

    async def list_episodes_without_channel(self, limit: int = 500) -> list[dict[str, Any]]:
        r = (self.db.table("episodes").select("id, youtube_video_id").is_("channel_id", "null").neq("status", "removed")
             .order("created_at").limit(limit).execute())
        return r.data or []

    async def create_episode(self, row: dict[str, Any]) -> str:
        r = self.db.table("episodes").upsert(row, on_conflict="youtube_video_id").execute()
        return r.data[0]["id"]

    async def update_episode(self, episode_id: str, fields: dict[str, Any]) -> None:
        self.db.table("episodes").update(fields).eq("id", episode_id).execute()

    # --- Statements -------------------------------------------------------------------------------

    def _upsert_claim(self, episode_id: str, rec: ClaimRecord) -> None:
        """Inserts a statement row unless the (episode, idx) row already exists (it may have been streamed earlier)."""
        c = rec.claim
        # Never-show statements (e.g. generalisations about a community) are not republished, even as text.
        hidden = rec.not_checked_reason == "outside_policy"
        self.db.table("claims").upsert({
            "episode_id": episode_id, "idx": rec.index, "start_s": rec.start_s, "speaker": None if hidden else c.speaker,
            "claim_text": "[Not shown: outside the content policy]" if hidden else c.claim,
            "context_quote": None if hidden else c.context_quote, "pestle_area": c.pestle_area,
            "statement_context": None if hidden else (c.statement_context or None),
            "question": None if hidden else (c.question or None), "asked_by": None if hidden else (c.asked_by or None),
            "question_kind": None if hidden or not c.question else c.question_kind,
            "topic": c.topic, "topics": [] if hidden else c.topics, "claim_type": c.claim_type, "policy_tier": rec.effective_tier,
            "not_checked_reason": rec.not_checked_reason, "refers_to_visual": c.refers_to_visual,
            "statement_type": c.statement_type, "verification_status": "not_eligible",
            "sources_status": sources_status(rec),
        }, on_conflict="episode_id,idx", ignore_duplicates=True).execute()

    async def save_statement(self, episode_id, rec):
        """Saves one statement while the extractor is still running."""
        self._upsert_claim(episode_id, rec)

    async def save_statements(self, episode_id, claims):
        for rec in claims:
            self._upsert_claim(episode_id, rec)

    async def clear_statements_without_sources(self, episode_id):
        """Before a (re)run: drops statements left by an earlier attempt, keeping any that already have sources."""
        self.db.table("claims").delete().eq("episode_id", episode_id).neq("sources_status", "done").execute()

    # --- Sources ----------------------------------------------------------------------------------

    async def get_claim_for_sources(self, claim_id):
        r = (self.db.table("claims")
             .select("id, idx, episode_id, start_s, speaker, claim_text, context_quote, statement_context, section_idx, "
                     "pestle_area, topic, topics, statement_type, policy_tier, not_checked_reason, refers_to_visual, sources_status, "
                     "episodes(id, youtube_video_id, title, status, cost_usd, creator_id, sections)")
             .eq("id", claim_id).limit(1).execute())
        return r.data[0] if r.data else None

    async def get_episode(self, episode_id):
        r = (self.db.table("episodes").select("id, youtube_video_id, title, status, cost_usd, creator_id, sections")
             .eq("id", episode_id).limit(1).execute())
        return r.data[0] if r.data else None

    async def list_batch_claims(self, episode_id):
        """Statements "Check sources for all" may take: not a question or story, not redacted, no sources yet, not running,
        and not already set aside by the classifier (sources_route 'skip'; a viewer can still press Check sources)."""
        r = (self.db.table("claims")
             .select("id, idx, start_s, speaker, claim_text, statement_context, section_idx, pestle_area, topic, topics, "
                     "statement_type, policy_tier, sources_status, sources_route")
             .eq("episode_id", episode_id).not_.in_("statement_type", ["question", "story"])
             .in_("sources_status", ["not_requested", "failed"]).neq("policy_tier", "never")
             .or_("not_checked_reason.is.null,not_checked_reason.neq.outside_policy").order("start_s").limit(200).execute())
        return [c for c in (r.data or []) if c.get("sources_route") != "skip"]

    async def list_claims_for_qa(self, episode_id):
        """Every statement of a video, in the order said, for the Q&A step to choose from."""
        r = (self.db.table("claims").select("id, start_s, speaker, claim_text, statement_type, policy_tier, not_checked_reason, sources_status, question")
             .eq("episode_id", episode_id).order("start_s").limit(1000).execute())
        return r.data or []

    async def start_claim_sources(self, claim_id):
        """Moves a claim to 'searching' only if no other run holds it. Returns False if it was taken."""
        r = (self.db.table("claims").update({"sources_status": "searching", "sources_error": None})
             .eq("id", claim_id).in_("sources_status", ["queued", "not_requested", "failed"]).execute())
        return bool(r.data)

    async def set_sources_status(self, claim_id, status, error=None):
        self.db.table("claims").update({"sources_status": status, "sources_error": error}).eq("id", claim_id).execute()

    async def save_claim_sources(self, claim_id, sources, summary="", match="", *, counter=None, counter_summary="",
                                 route=None, triage=None):
        """Both groups of sources (related, then counter) and the summaries, in one go."""
        self.db.table("claim_sources").delete().eq("claim_id", claim_id).execute()
        rows = [{**s.model_dump(), "kind": "related", "claim_id": claim_id} for s in sources]
        rows += [{**s.model_dump(), "kind": "counter", "claim_id": claim_id} for s in (counter or [])]
        if rows:
            self.db.table("claim_sources").insert(rows).execute()
        fields = {"sources_status": "done", "sources_error": None, "sources_summary": summary or None, "sources_match": match or None,
                  "counter_summary": counter_summary or None, "sources_checked_at": _now()}
        if route:
            fields["sources_route"] = route
        if triage is not None:
            fields["sources_triage"] = triage
        self.db.table("claims").update(fields).eq("id", claim_id).execute()

    async def save_sources_route(self, claim_id, route, triage=None):
        """The classifier set this statement aside: no search; it goes back to 'not requested' for the button."""
        self.db.table("claims").update({"sources_route": route, "sources_triage": triage, "sources_status": "not_requested",
                                        "sources_error": None}).eq("id", claim_id).execute()

    # --- Speakers and sections ---------------------------------------------------------------------

    async def get_speaker(self, key):
        r = self.db.table("speakers").select("*").eq("name_key", key).limit(1).execute()
        return r.data[0] if r.data else None

    async def save_speaker(self, row):
        r = self.db.table("speakers").upsert(row, on_conflict="name_key").execute()
        return r.data[0] if r.data else await self.get_speaker(row["name_key"])

    async def save_episode_speakers(self, episode_id, rows):
        """Replaces the video's speakers, so a re-run drops names the earlier run got wrong."""
        self.db.table("episode_speakers").delete().eq("episode_id", episode_id).execute()
        if rows:
            self.db.table("episode_speakers").upsert([{**r, "episode_id": episode_id} for r in rows],
                                                     on_conflict="episode_id,label").execute()

    async def get_episode_speakers(self, episode_id):
        r = (self.db.table("episode_speakers").select("label, role, statements, speaker_id, speakers(*)")
             .eq("episode_id", episode_id).execute())
        return r.data or []

    async def save_sections(self, episode_id, sections):
        """episodes.sections, and each statement's section_idx (the last section starting at or before it)."""
        self.db.table("episodes").update({"sections": sections}).eq("id", episode_id).execute()
        for i, s in enumerate(sections):
            q = self.db.table("claims").update({"section_idx": s["idx"]}).eq("episode_id", episode_id).gte("start_s", s["start_s"])
            if i + 1 < len(sections):
                q = q.lt("start_s", sections[i + 1]["start_s"])
            q.execute()

    async def list_claims_missing_summary(self, limit):
        """Claims whose sources were saved before summaries existed, with those sources in search order."""
        r = (self.db.table("claims")
             .select("id, episode_id, claim_text, episodes(youtube_video_id, cost_usd), "
                     "claim_sources(url, title, tier, excerpt, publish_date, rank)")
             .eq("sources_status", "done").is_("sources_match", "null").order("created_at").limit(limit).execute())
        return [c for c in (r.data or []) if c.get("claim_sources")]

    async def save_sources_summary(self, claim_id, summary, match=""):
        self.db.table("claims").update({"sources_summary": summary or None, "sources_match": match or None}).eq("id", claim_id).execute()

    async def add_episode_cost(self, episode_id, usd, tokens_in, tokens_out):
        row = self.db.table("episodes").select("cost_usd, tokens_in, tokens_out").eq("id", episode_id).limit(1).execute().data
        cur = row[0] if row else {}
        self.db.table("episodes").update({
            "cost_usd": round(float(cur.get("cost_usd") or 0) + usd, 4),
            "tokens_in": int(cur.get("tokens_in") or 0) + tokens_in,
            "tokens_out": int(cur.get("tokens_out") or 0) + tokens_out,
        }).eq("id", episode_id).execute()

    def reset_interrupted(self) -> None:
        """After a restart, work that was in memory can never finish: mark it so users can retry."""
        self.db.table("episodes").update({"status": "failed", "skip_reason": "Interrupted by a service restart. Submit it again."}
                                         ).eq("status", "processing").execute()
        self.db.table("episodes").update({"sources_batch_status": None}).eq("sources_batch_status", "running").execute()
        self.db.table("claims").update({"sources_status": "failed", "sources_error": "Interrupted. Try again."}
                                       ).in_("sources_status", ["queued", "searching"]).execute()

    async def save_guardrail_events(self, episode_id, events):
        if events:
            self.db.table("guardrail_events").insert([{"episode_id": episode_id, "stage": e.stage, "rule": e.rule,
                                                       "action": e.action, "detail": e.detail, "claim_idx": e.claim_index}
                                                      for e in events]).execute()

    # --- YouTube API data upkeep (stored API data must be refreshed or deleted within 30 days) ------------

    async def list_stale_episodes(self, days, limit=500):
        r = (self.db.table("episodes").select("id, youtube_video_id").neq("status", "removed")
             .lt("metadata_refreshed_at", _ago(days)).order("metadata_refreshed_at").limit(limit).execute())
        return r.data or []

    async def list_stale_channels(self, days, limit=500):
        r = (self.db.table("channels").select("id, youtube_channel_id")
             .lt("metadata_refreshed_at", _ago(days)).order("metadata_refreshed_at").limit(limit).execute())
        return r.data or []

    async def refresh_episode_metadata(self, episode_id, fields):
        self.db.table("episodes").update({**fields, "metadata_refreshed_at": _now()}).eq("id", episode_id).execute()

    async def mark_episode_removed(self, episode_id):
        self.db.table("episodes").update({"status": "removed", "title": None, "duration_s": None, "published_at": None,
                                          "skip_reason": "No longer available on YouTube.",
                                          "metadata_refreshed_at": _now()}).eq("id", episode_id).execute()

    async def refresh_channel(self, channel_id, fields):
        self.db.table("channels").update({**fields, "metadata_refreshed_at": _now()}).eq("id", channel_id).execute()


def make_store(settings: Settings) -> Any:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see pipeline/.env.example).")
    return SupabaseStore(settings)
