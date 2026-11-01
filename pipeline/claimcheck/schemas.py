"""Structured outputs for every LLM step (ADK output_schema) plus internal records."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

PestleArea = Literal["political", "economic", "social", "technological", "legal", "environmental"]
PolicyTier = Literal["normal", "stricter", "never"]
ClaimType = Literal["fact", "opinion", "prediction", "anecdote"]
# What kind of statement it is. Only factual_claim can be verified; the rest are tagged and shown.
StatementType = Literal["factual_claim", "opinion", "forecast", "analogy", "loaded_language", "hearsay", "other"]
VerificationStatus = Literal["not_eligible", "not_requested", "queued", "verifying", "verified", "awaiting_review", "failed"]
# Legacy claim_type stored alongside statement_type (claims.claim_type check constraint, effective_tier()).
_LEGACY_TYPE: dict[str, str] = {"factual_claim": "fact", "forecast": "prediction"}
_FROM_LEGACY: dict[str, str] = {"fact": "factual_claim", "opinion": "opinion", "prediction": "forecast", "anecdote": "other"}
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
    """One tagged statement. The name is kept from when only factual claims were extracted."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where the statement starts")
    speaker: str
    claim: str = Field(description="The statement, self-contained, speaker's numbers kept exactly")
    context_quote: str = Field(description="The words actually spoken, verbatim, up to ~40 words")
    pestle_area: PestleArea
    topic: str = Field(description="snake_case topic, e.g. gdp, welfare_schemes, nutrition")
    statement_type: Optional[StatementType] = Field(
        default=None, description="factual_claim, opinion, forecast, analogy, loaded_language, hearsay or other")
    tag_note: str = Field(default="", description="Up to 15 words on why it has this tag; empty for plain factual claims")
    claim_type: Optional[ClaimType] = None  # legacy; derived from statement_type when missing
    policy_tier: PolicyTier
    refers_to_visual: bool = False

    @model_validator(mode="after")
    def _fill_types(self) -> "ExtractedClaim":
        if self.statement_type is None:
            self.statement_type = _FROM_LEGACY.get(self.claim_type or "fact", "other")  # type: ignore[assignment]
        if self.claim_type is None or (self.claim_type == "fact") != (self.statement_type == "factual_claim"):
            self.claim_type = _LEGACY_TYPE.get(self.statement_type, "opinion")  # type: ignore[assignment]
        return self

    @property
    def verifiable(self) -> bool:
        return self.statement_type == "factual_claim"


class ExtractedStatement(BaseModel):
    """What the extractor model returns. statement_type is required and the legacy claim_type is absent,
    so the model can't skip the tag (an optional field was being left out and defaulted to factual_claim)."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where the statement starts")
    speaker: str
    claim: str = Field(description="The statement, self-contained, speaker's numbers kept exactly")
    context_quote: str = Field(description="The words actually spoken, verbatim, up to ~40 words")
    statement_type: StatementType = Field(
        description="Required tag: factual_claim, opinion, forecast, analogy, loaded_language, hearsay or other")
    tag_note: str = Field(default="", description="Up to 15 words on why it has this tag; empty for plain factual claims")
    pestle_area: PestleArea
    topic: str = Field(description="snake_case topic, e.g. gdp, welfare_schemes, nutrition")
    policy_tier: PolicyTier
    refers_to_visual: bool = False


class ExtractionResult(BaseModel):
    claims: list[ExtractedStatement]
    summary: str = Field(default="", description="2-3 plain sentences on what the video covers, written after the statements")


# --- Verification -----------------------------------------------------------------
class PlannedSearch(BaseModel):
    query: str = Field(description="Self-contained search query: entity, metric, period, geography")
    scope: Literal["tier1", "open"] = Field(description="tier1 = official sources for this topic only; open = the wider web")
    purpose: Literal["official", "corroborate", "counter"] = Field(
        description="official = primary source; corroborate = independent confirmation; counter = look for evidence against the claim")


class SearchPlan(BaseModel):
    searches: list[PlannedSearch] = Field(description="Exactly 3 searches, one per purpose")


class JudgeCitation(BaseModel):
    url: str
    title: str = ""
    quote: str = Field(description="Exact sentence copied character-for-character from the source text")


FinalTag = Literal["TRUE", "FALSE", "UNVERIFIABLE"]
_TAG_TO_VERDICT: dict[str, str] = {"TRUE": "supported", "FALSE": "false", "UNVERIFIABLE": "unverifiable"}


class JudgeOutput(BaseModel):
    """What the judge model returns: one of three final tags, an explanation and the sources."""

    tag: FinalTag = Field(description="TRUE, FALSE or UNVERIFIABLE")
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(description="2-3 neutral sentences. For FALSE: what exactly is wrong. For UNVERIFIABLE: why it can't be verified")
    correction: str = Field(default="", description="FALSE only: the correct fact according to the sources, in one sentence. Otherwise empty")
    evidence_grade: Optional[Literal["rct_or_review", "observational", "animal_or_lab", "expert_opinion", "not_applicable"]] = "not_applicable"
    citations: list["JudgeCitation"] = Field(default_factory=list)

    def to_result(self) -> "JudgeResult":
        return JudgeResult(verdict=_TAG_TO_VERDICT[self.tag], confidence=self.confidence, reasoning=self.explanation,  # type: ignore[arg-type]
                           correction=self.correction if self.tag == "FALSE" else "", evidence_grade=self.evidence_grade,
                           citations=self.citations)


class JudgeResult(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(description="2-3 neutral sentences describing what the sources state")
    correction: str = ""
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
    correction: str = ""
    score: Optional[int] = None  # 0-100 truthfulness; None when unverifiable
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


def verification_status(rec: ClaimRecord) -> str:
    """The claims.verification_status value for a record leaving the pipeline."""
    if rec.verdict is not None:
        return "awaiting_review" if rec.verdict.review_status == "pending" else "verified"
    if rec.not_checked_reason in ("budget", "error") and rec.claim.verifiable:
        return "failed"  # auto-verify was attempted and didn't finish: a viewer can retry
    if not rec.claim.verifiable or rec.not_checked_reason:
        return "not_eligible"
    return "not_requested"


class GuardrailEvent(BaseModel):
    stage: str
    rule: str
    action: Literal["blocked", "downgraded", "skipped", "flagged"]
    detail: str = ""
    claim_index: Optional[int] = None
