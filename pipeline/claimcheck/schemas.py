"""Structured outputs for every LLM step (ADK output_schema) plus internal records.

ClaimCheck tags statements and, on request, finds sources for a statement with one web search. It never judges a claim
true or false.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

PestleArea = Literal["political", "economic", "social", "technological", "legal", "environmental"]
PolicyTier = Literal["normal", "never"]
ClaimType = Literal["fact", "opinion", "prediction", "anecdote"]
# What kind of statement it is. Every type can have sources looked up (unless redacted by the content policy).
StatementType = Literal["factual_claim", "opinion", "forecast", "other"]
SourcesStatus = Literal["not_eligible", "not_requested", "queued", "searching", "done", "failed"]

# Tags used before the four-tag set; they read as criticism of a named speaker, so they are folded into "other".
LEGACY_TYPES: dict[str, str] = {"hearsay": "other", "analogy": "other", "loaded_language": "other"}
# Legacy claim_type stored alongside statement_type (claims.claim_type is NOT NULL with a check constraint).
_LEGACY_CLAIM_TYPE: dict[str, str] = {"factual_claim": "fact", "opinion": "opinion", "forecast": "prediction", "other": "anecdote"}
_FROM_CLAIM_TYPE: dict[str, str] = {"fact": "factual_claim", "opinion": "opinion", "prediction": "forecast", "anecdote": "other"}


def _fold_type(value: object) -> object:
    return LEGACY_TYPES.get(value, value) if isinstance(value, str) else value


# --- Extraction -----------------------------------------------------------------
class ExtractedClaim(BaseModel):
    """One tagged statement. The name is kept from when only factual claims were extracted."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where the statement starts")
    speaker: str
    claim: str = Field(description="The statement, self-contained, speaker's numbers kept exactly")
    context_quote: str = Field(description="The spoken words as heard, up to ~40 words")
    pestle_area: PestleArea
    topic: str = Field(description="First subject tag; same as topics[0]")
    topics: list[str] = Field(default_factory=list, description="1-2 free-form subject tags")
    statement_type: Optional[StatementType] = None
    claim_type: Optional[ClaimType] = None  # legacy; derived from statement_type
    policy_tier: PolicyTier
    refers_to_visual: bool = False

    @model_validator(mode="before")
    @classmethod
    def _fold_legacy(cls, data: object) -> object:
        if isinstance(data, dict):
            data = {**data, "statement_type": _fold_type(data.get("statement_type"))}
            if data.get("policy_tier") == "stricter":
                data["policy_tier"] = "normal"
        return data

    @model_validator(mode="after")
    def _fill_types(self) -> "ExtractedClaim":
        if not self.topics and self.topic:
            self.topics = [self.topic]
        if self.statement_type is None:
            self.statement_type = _FROM_CLAIM_TYPE.get(self.claim_type or "fact", "other")  # type: ignore[assignment]
        self.claim_type = _LEGACY_CLAIM_TYPE[self.statement_type]  # type: ignore[assignment,index]
        return self


class ExtractedStatement(BaseModel):
    """What the extractor model returns. statement_type is required so the model can't skip the tag."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where the statement starts")
    speaker: str = Field(description="Name only if it is said or shown on screen in the video, otherwise a role (Host, Guest 1)")
    claim: str = Field(description="The statement, self-contained, speaker's numbers kept exactly")
    context_quote: str = Field(description="The spoken words as you heard them (Hindi or English as spoken), up to ~40 words")
    statement_type: StatementType = Field(description="Required tag: factual_claim, opinion, forecast or other")
    pestle_area: PestleArea
    topics: list[str] = Field(description="1-2 short subject names (plain words) saying what the statement is about, most relevant first")
    policy_tier: PolicyTier
    refers_to_visual: bool = False


class ExtractionResult(BaseModel):
    claims: list[ExtractedStatement]
    summary: str = Field(default="", description="2-3 plain, neutral sentences on what the video covers, written after the statements")


# --- Sources (tools/evidence.py) ------------------------------------------------------------
class Source(BaseModel):
    """One web search result for a claim, as Parallel returned it. Not checked or judged: shown for context."""

    url: str
    title: str = ""
    excerpt: str = ""                 # text Parallel took from the page, cleaned to one short line
    publish_date: Optional[str] = None
    tier: int = 3                     # display label only: 1 official, 2 established news/research, 3 other
    rank: int = 0                     # Parallel's order, most relevant first


class SourcesSummary(BaseModel):
    """What the summary step returns: what the sources say, never an assessment of the statement."""

    summary: str = Field(default="", description="1-2 plain, neutral sentences (at most 45 words) summarising what the excerpts say, with their own figures and dates")
    match: Literal["high", "medium", "low"] = Field(default="low", description="How directly the excerpts address what the statement says (not whether they agree): high = the same specific point, medium = the same topic but not the specific point, low = loosely related or nothing relevant")


class ClaimRecord(BaseModel):
    index: int
    start_s: int
    claim: ExtractedClaim
    effective_tier: PolicyTier
    not_checked_reason: Optional[str] = None


def sources_status(rec: ClaimRecord) -> str:
    """The claims.sources_status value for a statement leaving the first pass."""
    return "not_eligible" if rec.not_checked_reason == "outside_policy" else "not_requested"


class GuardrailEvent(BaseModel):
    stage: str
    rule: str
    action: Literal["blocked", "downgraded", "skipped", "flagged"]
    detail: str = ""
    claim_index: Optional[int] = None
