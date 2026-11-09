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
# What kind of statement it is. Only a question is never looked up; for everything else the answer-tag classifier's claim type
# decides (agents/qa_tags.py): a personal story can still carry a checkable or self-serving claim.
StatementType = Literal["factual_claim", "opinion", "forecast", "advice", "story", "question", "other"]
NO_SOURCE_TYPES: frozenset[str] = frozenset({"question"})
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
    question_ts: str = ""  # when the asker starts the question (its lead-in included); empty if implied or not given
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
    question_ts: str = Field(default="", description="HH:MM:SS or MM:SS where the asker starts the question: the first word of question_quote, lead-in included; empty if implied")
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


class VideoPoint(BaseModel):
    text: str = Field(description="One checkable point from the answer, self-contained, figures, units and periods exactly as said")
    kind: PointKind = Field(description="figure, rule, event, cause, comparison, interpretation, outlook or other")


class AnswerPoints(BaseModel):
    answer: int = Field(description="The answer's number, exactly as given")
    points: list[VideoPoint] = Field(default_factory=list, description="The 1-2 most checkable points of this answer; empty when it is only background, small talk, a personal story or too vague to look up")


class SearchPlan(BaseModel):
    """One web search request that serves one or more answers."""

    topic: str = Field(description="At most 15 words: what this request looks into")
    answers: list[int] = Field(description="The numbers of the answers whose points this request looks into (1 to 4)")
    queries: list[str] = Field(description="1-3 short keyword queries that find sources on the points: name the body, programme, document, dataset, year or figure. Not an answer's wording")
    challenge_queries: list[str] = Field(default_factory=list, description="1-2 queries for sources giving other figures, periods or definitions, or other positions on the same points")
    disputed: bool = Field(default=False, description="True only if the issue itself is contested in public debate")
    positions: list[Position] = Field(default_factory=list, description="When disputed: 2-3 positions held on the issue; empty otherwise")


class VideoPlan(BaseModel):
    """The research for every answer of a video that needs it, planned together (agents/research.py)."""

    answers: list[AnswerPoints] = Field(default_factory=list, description="Every answer given, once, with its points")
    searches: list[SearchPlan] = Field(default_factory=list, description="The search requests; every answer that has points is served by at least one")


class PageNote(BaseModel):
    """What one page says, in a line (agents/assess.py): written for every page before any claim is judged."""

    page: int = Field(description="The page's number, as given")
    tldr: str = Field(description="What the page says that bears on the answer's subject, with its own figures, units and periods (at most 35 words). If it is about something else, say so in a few words")
    relevant: bool = Field(description="True if the page speaks to a specific claim of the answer; false if it is only about the wider topic or something else")


class ClaimFinding(BaseModel):
    """One checkable claim of the answer, compared with the pages (agents/assess.py)."""

    claim: str = Field(description="One specific, checkable claim of the answer (a figure, comparison, named study or organisation, cause or outcome), keeping its figures, units and periods (at most 30 words)")
    verdict: Literal["supported", "partly", "contradicted", "not_found"] = Field(
        description="supported: a page states the same fact. partly: a page backs the direction or part of it, but not the exact figure, scope or period, or a named source is unconfirmed. contradicted: a page says something incompatible about the SAME quantity, scope and period. not_found: no page addresses it")
    page: int = Field(default=0, description="The number of the ONE page that decides this verdict; 0 when no page addresses the claim")
    page_says: str = Field(default="", description="What that page says about the same thing, with its own figures (at most 30 words); empty when page is 0")
    quote: str = Field(default="", description="A fragment copied exactly, character for character, from that page's excerpt that shows it (at most 200 characters); empty if none fits")
    reason: str = Field(description="One or two plain sentences comparing the two: what the answer says, what the page says, what matches and what differs or is missing. Never a judgement of the speaker")


class AssessOut(BaseModel):
    """The answer checked against its pages (agents/assess.py): each page in a line, what the pages say together, then each claim."""

    pages: list[PageNote] = Field(default_factory=list, description="One entry for EVERY page given, in order")
    overview: str = Field(default="", description="What the pages together establish about the subject, and where they differ from each other (at most 60 words). Written without reference to the answer")
    claims: list[ClaimFinding] = Field(default_factory=list, description="The answer's 1 to 4 most important checkable claims, each compared with the pages")
    missing_context: str = Field(default="", description="Only if the claims check out: a counter-figure, different period, base rate or caveat in the pages that the answer leaves out and that changes what a listener would take from it (at most 40 words); empty otherwise")


class PersonTldr(BaseModel):
    label: str = Field(description="The person's label exactly as given in the digest")
    tldr: str = Field(description="One sentence (at most 28 words): who they are in this video and what they have a stake in")


class TldrOut(BaseModel):
    """The TL;DRs of one video's podcast profile (agents/tldr.py). Numbers come from the digest, which code counted."""

    headline: str = Field(description="One sentence (at most 30 words): what the conversation was about and the main thing the checks found")
    questions: str = Field(description="At most 22 words: how the host asked their questions")
    answers: str = Field(description="At most 22 words: how the questions were answered")
    statements: str = Field(description="At most 22 words: what kinds of statements were made")
    evidence: str = Field(description="At most 28 words: what the web pages found; name the topics of any contradicted answers")
    flags: str = Field(description="At most 24 words: conflicts, stakes and patterns found; 'None found.' if there are none")
    people: list[PersonTldr] = Field(default_factory=list, description="One entry for each person and the show in the digest")


# --- Profiles (agents/creators.py, agents/speakers.py) ---------------------------------------------
# Every item a profile lists names the search page it came from (`page`, the page's number in the prompt). Code maps it to the
# page's URL and drops an item whose page doesn't exist, so each fact a viewer sees links to where it was found.

class CitedText(BaseModel):
    text: str = Field(description="One short fact as the page states it, attributed where it is a view ('Described by X as ...')")
    page: int = Field(description="The number of the page it comes from")


class Business(BaseModel):
    name: str = Field(description="The company, fund or organisation")
    relation: Literal["founder", "executive", "investor", "board", "advisor", "employee", "owner", "other"]
    sector: str = Field(default="", description="What it does, in a few words")
    current: bool = Field(default=True, description="False if the pages say the tie has ended")
    page: int


class FinancialInterest(BaseModel):
    what: str = Field(description="A holding, fund, product they sell (book, course, supplement, app), paid partnership or sponsorship")
    page: int


class Political(BaseModel):
    leaning: str = Field(default="", description="Their political or ideological leaning as the pages state it, attributed; empty if none")
    basis: Literal["declared", "described", "none"] = Field(default="none", description="declared: a party, elected or government post; described: the pages attribute a leaning; else none")
    posts: list[str] = Field(default_factory=list, description="Party memberships, elected, ministerial or advisory government posts they hold or held")
    page: int = 0


class Opinion(BaseModel):
    text: str = Field(description="What is said about them")
    by: str = Field(default="", description="Who says it (a newspaper, a critic, an organisation)")
    page: int


class Controversy(BaseModel):
    what: str = Field(description="The controversy, neutrally, as the pages report it")
    when: str = Field(default="", description="When, if the pages say")
    page: int


class BiasClaim(BaseModel):
    claim: str = Field(description="The accusation of bias or conflict of interest, as made")
    by: str = Field(default="", description="Who made it")
    page: int


class Sponsor(BaseModel):
    name: str
    category: str = Field(default="", description="What the sponsor sells")
    page: int


IncentiveTag = Literal["commercial", "financial", "ideological", "reputational", "academic",
                       "sponsor_aligned", "adversarial", "access_preserving", "audience_captured"]


class IncentiveOut(BaseModel):
    """Why someone is in a conversation, as the pages show it."""

    tag: IncentiveTag
    reason: str = Field(description="One short sentence: the fact on the page that shows it, attributed")
    page: int = Field(description="The number of the page that shows it")


INCENTIVES_FIELD = ("Incentive tags the pages plainly show, each with the page: commercial (sells a book, product, course, service or "
                    "show of their own), financial (holds equity or investments in companies, assets or a sector), ideological (a "
                    "party, government post, policy or worldview they advocate), reputational (dealing with a controversy or rebuilding "
                    "an image), academic (a researcher or institution with findings or a post to defend); for a host or show: "
                    "sponsor_aligned (sponsors or paid partners in the subjects the show covers), adversarial (known for tough, "
                    "accountability-style questioning), access_preserving (reported as soft on big-name guests), audience_captured "
                    "(reported as telling its audience what it wants to hear). Never a tag a page doesn't show; empty if none.")


class CreatorProfileOut(BaseModel):
    """What the profile step returns about a YouTube show or channel, from web search excerpts only."""

    identified: bool = Field(description="True only if the pages clearly describe this show or channel")
    podcast: str = Field(default="", description="The show's name")
    summary: str = Field(default="", description="1-2 neutral sentences: who hosts it and what it covers")
    narrative: str = Field(default="", description="A neutral profile of the show in 120-200 words, every view attributed, from the pages only")
    hosts: str = Field(default="", description="The host or hosts, as the pages name them")
    host_background: str = Field(default="", description="Short: what the host is known for professionally")
    host_bio: str = Field(default="", description="One or two sentences on the host or hosts")
    topics: list[str] = Field(default_factory=list, description="Subjects the show usually covers")
    known_for: str = Field(default="", description="What the show is known for, as the pages describe it")
    country: str = Field(default="", description="The country the show is based in, if the pages say")
    ownership: list[CitedText] = Field(default_factory=list, description="Who owns, funds or distributes the show (a network, investors, a company)")
    sponsors: list[Sponsor] = Field(default_factory=list, description="Sponsors and advertisers the pages name")
    political: Political = Field(default_factory=Political)
    praise: list[Opinion] = Field(default_factory=list, description="Favourable views of the show, attributed")
    criticism: list[Opinion] = Field(default_factory=list, description="Critical views of the show, attributed")
    controversies: list[Controversy] = Field(default_factory=list)
    bias_claims: list[BiasClaim] = Field(default_factory=list, description="Accusations that the show is biased, captured by its audience, soft on guests or paid for coverage")
    incentives: list[IncentiveOut] = Field(default_factory=list, description=INCENTIVES_FIELD)


class SpeakerProfileOut(BaseModel):
    """What the profile step returns about one named person, from web search excerpts only."""

    identified: bool = Field(description="True only if the pages clearly describe one public person who fits the video context")
    summary: str = Field(default="", description="1-2 neutral sentences: who they are and what they are known for")
    narrative: str = Field(default="", description="A neutral profile in 150-250 words: who they are, their work, their interests and how they are seen, every view attributed, from the pages only")
    role: str = Field(default="", description="Current main role, e.g. 'Economist, former RBI governor'")
    background: str = Field(default="", description="Professional background in one or two sentences")
    expertise: list[str] = Field(default_factory=list, description="Fields they are an expert or practitioner in, as the pages show")
    credentials: str = Field(default="", description="Degrees, posts or achievements the pages give for that expertise")
    affiliations: list[str] = Field(default_factory=list, description="Organisations, parties, companies or shows they are tied to")
    topics: list[str] = Field(default_factory=list, description="Subjects they usually speak on")
    businesses: list[Business] = Field(default_factory=list, description="Companies, funds and organisations they founded, run, invest in or advise")
    financial_interests: list[FinancialInterest] = Field(default_factory=list, description="Holdings, products they sell, paid partnerships")
    political: Political = Field(default_factory=Political)
    praise: list[Opinion] = Field(default_factory=list, description="Favourable views of them, attributed")
    criticism: list[Opinion] = Field(default_factory=list, description="Critical views of them, attributed")
    controversies: list[Controversy] = Field(default_factory=list)
    bias_claims: list[BiasClaim] = Field(default_factory=list, description="Accusations of bias or conflicts of interest made against them")
    sponsors: list[Sponsor] = Field(default_factory=list, description="For a host: sponsors and paid partners of their shows")
    incentives: list[IncentiveOut] = Field(default_factory=list, description=INCENTIVES_FIELD)


# --- Who appears in a video (agents/people.py) ----------------------------------------------------
class PersonOut(BaseModel):
    name: str = Field(description="The person's full name, exactly as the title, description or pages give it")
    role: str = Field(default="", description="How they are introduced, in a few words ('Co-founder of Zerodha')")
    is_host: bool = Field(default=False, description="True if they host the show or this video")
    promotes: list[str] = Field(default_factory=list, description="What the description promotes for this person: their book, product, course, company, fund, app or show, as named there")


class PeopleOut(BaseModel):
    people: list[PersonOut] = Field(default_factory=list, description="The hosts and guests who appear and speak in this video; never people who are only talked about")


class ClaimRecord(BaseModel):
    index: int
    start_s: int  # where the answer starts
    question_start_s: Optional[int] = None  # where the question starts, when the extractor gave a believable time; the page plays from here
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
