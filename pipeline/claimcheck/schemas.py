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
# What kind of statement it is. Questions and personal stories assert nothing a source could address, so they have
# no "Check sources"; every other type does (unless redacted by the content policy).
StatementType = Literal["factual_claim", "opinion", "forecast", "advice", "story", "question", "other"]
NO_SOURCE_TYPES: frozenset[str] = frozenset({"question", "story"})
SourcesStatus = Literal["not_eligible", "not_requested", "queued", "searching", "done", "failed"]

# Tags used before the four-tag set; they read as criticism of a named speaker, so they are folded into "other".
LEGACY_TYPES: dict[str, str] = {"hearsay": "other", "analogy": "other", "loaded_language": "other"}
# Legacy claim_type stored alongside statement_type (claims.claim_type is NOT NULL with a check constraint).
_LEGACY_CLAIM_TYPE: dict[str, str] = {"factual_claim": "fact", "opinion": "opinion", "forecast": "prediction", "advice": "opinion",
                                       "story": "anecdote", "question": "anecdote", "other": "anecdote"}
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
    statement_context: str = ""  # what was being discussed when it was said, one neutral line
    question: str = ""  # the question this answer responds to (empty for statements saved before answers were extracted)
    question_quote: str = ""  # the question as the asker said it (framing and all); the question above is a plain-words rewrite
    asked_by: str = ""
    question_kind: Optional[Literal["asked", "implied"]] = None
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
    """What the extractor model returns: one answer to one question. The field is still called `claim` (and the type
    `statement_type`) because every later step, the source search included, works on that text."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where the answer starts")
    question: str = Field(description="The question this answer responds to: plain words, self-contained, at most 25 words, ends with '?'")
    question_quote: str = Field(default="", description="The asker's own words as you heard them (Hindi or English as spoken), up to ~35 words, including any lead-in or view they voice before asking; empty if implied")
    question_kind: Literal["asked", "implied"] = Field(description="'asked' if someone put the question; 'implied' if you wrote it for a passage nobody prompted")
    asked_by: str = Field(description="Who asked it (name only if said or shown on screen, otherwise a role such as Host); empty if implied")
    speaker: str = Field(description="Who gave this answer. Name only if it is said or shown on screen in the video, otherwise a role (Host, Guest 1)")
    claim: str = Field(description="The answer in plain words, at most 80 words, speaker's numbers kept exactly")
    context_quote: str = Field(description="The spoken words as you heard them (Hindi or English as spoken), up to ~40 words")
    statement_context: str = Field(description="Required: one neutral line (at most 20 words) on what was being discussed when this was said")
    statement_type: StatementType = Field(description="What the answer mostly is: factual_claim, opinion, forecast, advice, story or other (never question)")
    pestle_area: PestleArea
    topics: list[str] = Field(description="1-2 short subject names (plain words) saying what the answer is about, most relevant first")
    policy_tier: PolicyTier
    refers_to_visual: bool = False


class Section(BaseModel):
    """A part of the conversation: when it starts and what was being discussed."""

    start_ts: str = Field(description="HH:MM:SS or MM:SS where this part starts")
    title: str = Field(description="3-8 plain words naming the subject")
    summary: str = Field(description="1-2 neutral sentences on what was discussed in this part")


class ExtractionResult(BaseModel):
    claims: list[ExtractedStatement]
    sections: list[Section] = Field(default_factory=list, description="The parts of the conversation in order, written after the statements")
    summary: str = Field(default="", description="2-3 plain, neutral sentences on what the video covers, written after the statements")


# --- Sources (tools/evidence.py) ------------------------------------------------------------
class Source(BaseModel):
    """One web search result for a claim, as Parallel returned it. Not checked or judged: shown for context."""

    url: str
    title: str = ""
    excerpt: str = ""                 # text Parallel took from the page, cleaned to one short line
    publish_date: Optional[str] = None
    tier: int = 3                     # unused: every source is treated alike (kept for the stored rows)
    rank: int = 0                     # Parallel's order, most relevant first
    kind: Literal["related", "counter"] = "related"  # which search found it: the statement's subject, or other figures / views
    independence: Optional[Literal["independent", "own_organisation", "same_episode"]] = None  # set by the research lookup (agents/independence.py)


# --- Q&A view (agents/qa.py) ---------------------------------------------------------------------
class QaItemOut(BaseModel):
    """One question for the Q&A view and the numbered statements that answer it."""

    question: str = Field(description="A neutral question a reader would ask, answered by the cited statements alone")
    statements: list[int] = Field(description="Numbers of the 1-3 statements that answer the question")


class QaOut(BaseModel):
    items: list[QaItemOut] = Field(default_factory=list)


# --- Researching an answer (agents/research.py) ---------------------------------------------------
PointKind = Literal["figure", "rule", "event", "cause", "comparison", "interpretation", "outlook", "other"]
Relation = Literal["same", "different", "different_scope", "other_position"]


class PlanPoint(BaseModel):
    """One checkable point of an answer, and how to look for sources on it."""

    text: str = Field(description="One checkable point from the answer, self-contained, figures, units and periods exactly as said")
    kind: PointKind = Field(description="figure, rule, event, cause, comparison, interpretation (a reading of history or events), outlook or other")
    queries: list[str] = Field(description="2 short keyword queries that would find sources on this point. Not the answer's wording, and not only the phrase the answer opens with")
    challenge_queries: list[str] = Field(description="1-2 queries aimed at sources giving other figures, other periods or definitions, or other positions on this point")


class Position(BaseModel):
    label: str = Field(description="A short neutral name (at most 8 words) for a position people hold on the issue; never a person or party's character")
    query: str = Field(description="A query that would find a source stating that position")


class ResearchPlan(BaseModel):
    points: list[PlanPoint] = Field(default_factory=list, description="The 1-2 most checkable points of the answer; empty when it is only background, small talk, a personal story or too vague to look up")
    disputed: bool = Field(default=False, description="True only if the issue itself is contested in public debate, not merely because the answer is an opinion")
    positions: list[Position] = Field(default_factory=list, description="When disputed: 2-3 positions held on the issue; empty otherwise")


# --- Creator profiles found on the web (agents/creators.py) -------------------------------------
class CreatorProfileOut(BaseModel):
    """What the profile step returns about a YouTube show or channel, from web search excerpts only."""

    identified: bool = Field(description="True only if the pages clearly describe this show or channel")
    podcast: str = Field(default="", description="The show's name")
    summary: str = Field(default="", description="1-2 neutral sentences: who hosts it and what it covers")
    hosts: str = Field(default="", description="The host or hosts, as the pages name them")
    host_background: str = Field(default="", description="Short: what the host is known for professionally")
    host_bio: str = Field(default="", description="One or two sentences on the host or hosts")
    topics: list[str] = Field(default_factory=list, description="Subjects the show usually covers")
    known_for: str = Field(default="", description="What the show is known for, as the pages describe it")
    criticism: str = Field(default="", description="Main public criticisms the pages report, attributed; empty if none")
    country: str = Field(default="", description="The country the show is based in, if the pages say")
    leaning: str = Field(default="", description="The political or ideological leaning the pages attribute to the show, attributed ('Described by X as ...'); empty if they say nothing")
    leaning_basis: Literal["described", "none"] = Field(default="none", description="'described' if the pages attribute a leaning to the show, else 'none'")
    public_opinion: str = Field(default="", description="How the public and the press view the show, both favourable and critical, each attributed ('Praised by X for ...', 'Criticised by Y for ...'); empty if the pages say nothing")


# --- Speaker profiles (agents/speakers.py) -------------------------------------------------------
class SpeakerProfileOut(BaseModel):
    """What the profile step returns about one named speaker, from web search excerpts only."""

    identified: bool = Field(description="True only if the pages clearly describe one public person who fits the video context")
    summary: str = Field(default="", description="1-2 neutral sentences: who they are and what they are known for")
    role: str = Field(default="", description="Current main role, e.g. 'Economist, former RBI governor'")
    background: str = Field(default="", description="Professional background in one or two sentences")
    affiliations: list[str] = Field(default_factory=list, description="Organisations, parties, companies or shows they are tied to")
    topics: list[str] = Field(default_factory=list, description="Subjects they usually speak on")
    known_positions: str = Field(default="", description="Public positions or leanings as the pages describe them, attributed ('described as...'); empty if none")
    criticisms: str = Field(default="", description="Main public criticisms as the pages report them, attributed; empty if none")
    leaning: str = Field(default="", description="Their political or ideological leaning as the pages state it, attributed ('Described by X as ...', or the party or government post they hold or held); empty if the pages say nothing")
    leaning_basis: Literal["declared", "described", "none"] = Field(default="none", description="'declared' if they hold or held a party or government post or speak for a party; 'described' if the pages attribute a leaning to them; else 'none'")
    public_opinion: str = Field(default="", description="How the public and the press view them, both favourable and critical, each attributed ('Praised by X for ...', 'Criticised by Y for ...'); empty if the pages say nothing")




class ClaimRecord(BaseModel):
    index: int
    start_s: int
    claim: ExtractedClaim
    effective_tier: PolicyTier
    not_checked_reason: Optional[str] = None


def sources_status(rec: ClaimRecord) -> str:
    """The claims.sources_status value for a statement leaving the first pass."""
    if rec.not_checked_reason == "outside_policy" or rec.claim.statement_type in NO_SOURCE_TYPES:
        return "not_eligible"
    return "not_requested"


class GuardrailEvent(BaseModel):
    stage: str
    rule: str
    action: Literal["blocked", "downgraded", "skipped", "flagged"]
    detail: str = ""
    claim_index: Optional[int] = None
