"""Structured outputs for every LLM step (ADK output_schema) plus internal records."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

PestleArea = Literal["political", "economic", "social", "technological", "legal", "environmental"]
PolicyTier = Literal["normal", "stricter", "never"]
ClaimType = Literal["fact", "opinion", "prediction", "anecdote"]
Verdict = Literal["supported", "misleading", "false", "outdated", "disputed", "unverifiable"]


# --- Triage -------------------------------------------------------------------
class PestleMix(BaseModel):
    """Share of the video's content per PESTLE area (values sum to about 1)."""

    political: float = 0
    economic: float = 0
    social: float = 0
    technological: float = 0
    legal: float = 0
    environmental: float = 0


class TriageResult(BaseModel):
    worthiness: float = Field(ge=0, le=1, description="0-1: how worth fact-checking this video is")
    factual_density: Literal["low", "medium", "high"]
    speaker_type: Literal["minister_or_official", "party_spokesperson", "journalist", "commentator", "expert", "other"]
    pestle_mix: PestleMix
    never_share: float = Field(ge=0, le=1, description="Share of content falling in the never-check tier")
    reason: str = Field(description="One sentence explaining the score")


# --- Extraction -----------------------------------------------------------------
class ExtractedClaim(BaseModel):
    start_ts: str = Field(description="HH:MM:SS or MM:SS where the claim starts")
    speaker: str
    claim: str = Field(description="One self-contained factual statement, speaker's numbers kept exactly")
    context_quote: str = Field(description="The words actually spoken, verbatim, up to ~40 words")
    pestle_area: PestleArea
    topic: str = Field(description="snake_case topic, e.g. gdp, welfare_schemes, nutrition")
    claim_type: ClaimType
    policy_tier: PolicyTier
    refers_to_visual: bool = False


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


# --- Prioritisation ---------------------------------------------------------------
class ClaimPriority(BaseModel):
    index: int
    label: Literal["checkworthy_factual", "unimportant_factual", "not_factual"]
    score: float = Field(ge=0, le=1)


class PriorityResult(BaseModel):
    priorities: list[ClaimPriority]


# --- Verification -----------------------------------------------------------------
class NormalizedQuery(BaseModel):
    query: str = Field(description="Self-contained search query: entity, metric, period, geography")
    keywords: list[str] = Field(description="2-4 short keyword queries")


class JudgeCitation(BaseModel):
    url: str
    title: str = ""
    quote: str = Field(description="Exact sentence copied character-for-character from the source text")


class JudgeResult(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(description="2-3 neutral sentences describing what the sources state")
    evidence_grade: Optional[Literal["rct_or_review", "observational", "animal_or_lab", "expert_opinion", "not_applicable"]] = "not_applicable"
    citations: list[JudgeCitation] = Field(default_factory=list)


# --- Internal records (not LLM output) ------------------------------------------
class Citation(BaseModel):
    url: str
    title: str = ""
    tier: int
    quote: str
    quote_check_passed: bool


class FinalVerdict(BaseModel):
    verdict: Verdict
    confidence: float
    reasoning: str
    evidence_grade: str = "not_applicable"
    citations: list[Citation] = Field(default_factory=list)
    escalated: bool = False
    from_cache: bool = False
    review_status: Literal["not_needed", "pending", "approved", "changed"] = "not_needed"
    downgrades: list[str] = Field(default_factory=list)


class ClaimRecord(BaseModel):
    index: int
    start_s: int
    claim: ExtractedClaim
    effective_tier: PolicyTier
    checkworthiness: Optional[float] = None
    not_checked_reason: Optional[str] = None
    verdict: Optional[FinalVerdict] = None


class GuardrailEvent(BaseModel):
    stage: str
    rule: str
    action: Literal["blocked", "downgraded", "skipped", "flagged"]
    detail: str = ""
    claim_index: Optional[int] = None
