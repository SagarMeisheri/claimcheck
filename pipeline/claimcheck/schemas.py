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
    tier: int = 3                     # display label only: 1 official, 2 established news/research, 3 other
    rank: int = 0                     # Parallel's order, most relevant first
    kind: Literal["related", "counter"] = "related"  # which search found it: the statement's subject, or other figures / views
    independence: Optional[Literal["independent", "own_organisation", "same_episode"]] = None  # set by the research lookup (agents/independence.py)


class SourcesSummary(BaseModel):
    """What the summary step returns: what the sources say, never an assessment of the statement."""

    summary: str = Field(default="", description="1-2 plain, neutral sentences (at most 45 words) summarising what the excerpts say, with their own figures and dates")
    match: Literal["high", "medium", "low"] = Field(default="low", description="How directly the excerpts address what the statement says (not whether they agree): high = the same specific point, medium = the same topic but not the specific point, low = loosely related or nothing relevant")
    counter_summary: str = Field(default="", description="1-2 plain, neutral sentences (at most 45 words) on what the OTHER pages say, with their own figures and dates; empty if there are none")


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
    points: list[PlanPoint] = Field(description="The 1-2 most checkable points of the answer, each searched separately")
    disputed: bool = Field(default=False, description="True only if the issue itself is contested in public debate, not merely because the answer is an opinion")
    positions: list[Position] = Field(default_factory=list, description="When disputed: 2-3 positions held on the issue; empty otherwise")


class PageFinding(BaseModel):
    point: int = Field(description="Number of the point this finding is about")
    page: int = Field(description="Number of the page")
    relation: Relation = Field(description="same, different, different_scope or other_position")
    finding: str = Field(description="What the page says about the point, at most 40 words, with its figures, units and periods")
    quote: str = Field(description="The exact words from the page that support the finding, copied character for character, at most 40 words")
    position: str = Field(default="", description="For other_position or different: a neutral label of the stance, at most 8 words")


class PageReading(BaseModel):
    findings: list[PageFinding] = Field(default_factory=list)


class QueryRewrite(BaseModel):
    queries: list[str] = Field(description="2 new keyword queries from a different angle")


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


# --- Opinion assessment (agents/opinion.py) ----------------------------------------------------
Camp = Literal["ruling", "opposition"]


class StancePlan(BaseModel):
    issue: str = Field(description="The public issue the answer takes a side on, as one neutral sentence that doesn't favour either side")
    ruling_queries: list[str] = Field(description="2 short keyword queries that would find what the governing side has said or done on this issue")
    opposition_queries: list[str] = Field(description="2 short keyword queries that would find what the opposition has said on this issue")


class StanceFinding(BaseModel):
    camp: Camp = Field(description="ruling or opposition")
    page: int = Field(description="Number of the page")
    stance: str = Field(description="The camp's position on the issue as this page reports it, at most 35 words, no adjectives of your own")
    quote: str = Field(description="The exact words from the page that state or report the position, copied character for character, at most 40 words")
    who: str = Field(default="", description="Who held the position, as the page names them (a party, a minister, a spokesperson)")


class StanceReading(BaseModel):
    findings: list[StanceFinding] = Field(default_factory=list)


BiasKind = Literal["stake", "prior_stance", "camp_match", "one_sided", "loaded_language", "selective_use", "leading_question", "other_view_acknowledged"]


class BiasSignal(BaseModel):
    kind: BiasKind = Field(description="stake (a role or interest in the outcome), prior_stance (their own earlier public position), camp_match (the answer matches a camp's stated position), one_sided (no other view acknowledged), loaded_language, selective_use (cites only facts favouring one side), leading_question, other_view_acknowledged (the answer itself weighs another view)")
    text: str = Field(description="What was found, one plain sentence, at most 30 words, no adjectives of your own")
    quote: str = Field(description="The exact words, copied character for character, from the answer, the question, the profile text or a finding, that show it")


class BiasRead(BaseModel):
    signals: list[BiasSignal] = Field(default_factory=list)
    matches: Literal["ruling", "opposition", "neither", "unclear"] = Field(default="unclear", description="Which camp's stated position the answer's stance is closest to")


class Assessment(BaseModel):
    bottom_line: str = Field(description="One plain sentence, at most 45 words: what kind of answer it is, what it rests on, where it sits between the ruling side and the opposition")
    grounding: Literal["backed", "partly_backed", "unverified", "not_backed", "value_judgement"] = Field(description="backed: the premises have independent sources; partly_backed: some do; unverified: none has an independent source; not_backed: independent sources were found and give other figures or a different account; value_judgement: no factual premise to check")
    grounding_reason: str = Field(description="One sentence, at most 35 words, naming the premise and what the sources show")
    bias: Literal["balanced", "leans", "one_sided", "cant_tell"] = Field(description="balanced, leans, one_sided or cant_tell, from the evidenced signals only")
    toward: Literal["ruling", "opposition", "none"] = Field(default="none", description="For leans and one_sided: which camp's position the answer follows")
    bias_reason: str = Field(description="One sentence, at most 40 words, naming the strongest evidenced signals")
    signals: list[int] = Field(default_factory=list, description="Numbers of the signals the bias judgement relies on")
    objection: str = Field(default="", description="The strongest evidenced other view in one sentence of at most 30 words, or empty")
    speaker_record: str = Field(default="", description="One sentence on what the speaker has said before on this, only if a signal or finding shows it, else empty")
    stake: str = Field(default="", description="One factual sentence on a role or interest the speaker has in the outcome, only if a signal shows it, else empty")
    evidence: Literal["strong", "limited", "none"] = Field(description="How much independent evidence the assessment rests on")


# --- Source triage (agents/sources.py) ---------------------------------------------------------
TriageRoute = Literal["skip", "related", "data", "contested"]
TRIAGE_ROUTES: tuple[str, ...] = ("skip", "related", "data", "contested")
COUNTER_ROUTES: frozenset[str] = frozenset({"data", "contested"})


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
