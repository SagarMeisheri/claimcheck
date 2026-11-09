export type StatementType = "factual_claim" | "opinion" | "forecast" | "advice" | "story" | "question" | "other";
/** Looking up sources for one statement (any type). Only statements redacted by the content policy stay "not_eligible". */
export type SourcesStatus = "not_eligible" | "not_requested" | "queued" | "searching" | "done" | "failed";
/** How directly a claim's sources address its specific point (relevance, never agreement). */
export type SourcesMatch = "high" | "medium" | "low";
/** How the classifier chose to look a statement up. skip: not looked up automatically; data / contested: a second
 * search for different figures or other perspectives as well. */
export type SourcesRoute = "skip" | "related" | "data" | "contested";
export type Pestle = "political" | "economic" | "social" | "technological" | "legal" | "environmental";

/** One web search result for a statement, as the search returned it: shown for context, not checked or judged. */
export interface Source {
  url: string;
  title: string | null;
  tier?: number; // unused: every source is treated alike
  excerpt: string; // text the search took from the page (may be empty)
  publish_date: string | null;
  rank: number; // the search engine's order, most relevant first
  kind?: "related" | "counter"; // which search found it: the statement's subject, or different figures / other views
  independence?: "independent" | "own_organisation" | "same_episode" | null; // where a page comes from: a note for the reader, treated alike
}

export type PointStatus = "sources_found" | "no_source" | "pending"; // pending: the pages are not in yet
export interface ResearchPoint { text: string; kind: string; status: PointStatus }
/** A page the grounding rests on: its title and search excerpt. */
export interface GroundingBasis { site: string; url: string; relation: "page"; finding: string; quote: string }
/** For a contradicted answer (agents/contradiction.py): the claim the pages contradict, what the page says instead, how they differ, and a verbatim excerpt from that page. */
export interface GroundingContradiction { said: string; sources_say: string; difference: string; quote?: string; site: string; url: string; title?: string }
/** How each question was asked (agents/interview.py, one batched classifier call per video, never shown the answer). */
export type QuestionType = "factual" | "explanatory" | "experiential" | "evaluative" | "speculative" | "challenging" | "unclear";
export interface QuestionAnalysis { type: QuestionType; p?: number; spoken?: boolean } // spoken false: tagged from the AI's plain-words question
export type AnswerType = "direct" | "narrative" | "structured" | "pivot" | "evasive" | "unclear";
export type ClaimKind = "objective_fact" | "anchored_opinion" | "pure_opinion" | "prediction";
/** Is it backed by evidence? ungrounded: a self-serving claim that rests on the speaker's own word (the self-report rule). */
export type Grounding = "grounded" | "plausible" | "contradicted" | "exempt" | "ungrounded";
export type QaFlag = "missing_context" | "staged_pushback" | "self_serving_pivot";
/** The answer's tags (agents/qa_tags.py): ADK classifiers, then the skepticism rules in code. Any part can be missing. */
export interface QaTags {
  version: number;
  answer?: { type: AnswerType; p: number };
  claim?: { type: ClaimKind; p: number };
  grounding?: { label: Grounding; p: number; was?: Grounding; evidence: "strong" | "limited" | "none"; basis: GroundingBasis[]; contradiction?: GroundingContradiction };
  match?: { label: "high" | "medium" | "low"; p: number };
  flags?: QaFlag[];
  conflict?: { kind: "self_report" | "self_serving_pivot"; disclosure?: "disclosed" | "undisclosed" };
  /** The answer set against the speaker's profile: the profile item it benefits ("benefits", also a conflict) or concerns ("touches"). */
  stake?: { link: "benefits" | "touches"; p: number; item: { kind: string; text: string; url?: string; site?: string }; disclosure?: "disclosed" | "undisclosed" };
  profile_checked?: number; // how many items of the speaker's profile the answer was compared with
  chain?: string;
}
/** How an answer's sources were researched: its checkable points and every page the searches returned. */
export interface Research {
  version: number; points: ResearchPoint[]; positions: string[]; queries: string[]; dropped?: Record<string, number>;
  /** Only while the lookup runs: what it is doing now. Gone when it finishes. */
  stage?: "planning" | "searching" | "reading" | "grounding";
  searches?: { query: string; queries?: string[]; urls: string[]; failed?: boolean; pending?: boolean }[]; // what each search returned, in its own order (pending: still out)
  pages?: { url: string; site: string; title: string; independence: string }[]; // every page the searches returned
}
/** One incentive tag of a person for a video, with the fact it rests on and where that fact was found. */
export type IncentiveTag = "commercial" | "financial" | "ideological" | "reputational" | "academic" | "sponsor_aligned" | "invested_peer" | "adversarial";
export interface Incentive { reason: string; url?: string; site?: string }
/** How host and guest dealt with each other (agents/interview.py), and what the description tells viewers. */
/** The podcast profile's TL;DRs (pipeline agents/tldr.py): a sentence for the whole video, one per section and one per person (by label; "__show" is the show). `counts` is what they were written from. */
export interface Tldr {
  headline: string; questions: string; answers: string; statements: string; evidence: string; flags: string;
  people: Record<string, string>; counts?: Record<string, number>; generated_at?: string;
}
export interface Interaction { dynamic?: "promotional" | "neutral" | "adversarial"; p?: number; description_notes?: string[]; tldr?: Tldr }
/** A fact in a profile, linked to the search page it came from. */
export interface Cited { url?: string; site?: string }
export interface ProfileV2 {
  narrative?: string; expertise?: string[]; credentials?: string;
  businesses?: (Cited & { name: string; relation: string; sector?: string; current?: boolean })[];
  financial_interests?: (Cited & { what: string })[];
  political?: Cited & { leaning?: string; basis?: string; posts?: string[] };
  praise?: (Cited & { text: string; by?: string })[]; critiques?: (Cited & { text: string; by?: string })[];
  controversy_reports?: (Cited & { what: string; when?: string })[]; bias_claims?: (Cited & { claim: string; by?: string })[];
  sponsors?: (Cited & { name: string; category?: string })[]; ownership?: (Cited & { text: string })[];
  incentives?: Partial<Record<IncentiveTag, Incentive>>;
}

export interface Claim {
  id: string;
  idx: number;
  start_s: number;
  speaker: string | null; // as identified by the AI
  claim_text: string; // AI paraphrase of what was said
  context_quote: string | null; // AI transcript of the spoken words
  statement_context: string | null; // AI: what was being discussed when it was said
  question?: string | null; // the question this answer responds to (videos analysed since answers were extracted)
  asked_by?: string | null;
  question_start_s?: number | null; // where the question starts (start_s is where the answer starts); null for older videos and implied questions
  question_kind?: "asked" | "implied" | null; // implied: the AI wrote the question for a passage nobody prompted
  question_analysis?: QuestionAnalysis | null; // how the question was asked (factual ... challenging), one call per video
  qa_tags?: QaTags | null; // the answer's tags: answer type, claim type, grounding, conflict flags
  section_idx: number | null;
  pestle_area: Pestle;
  topic: string | null;
  topics: string[]; // 1-2 subject tags (filter chips)
  statement_type: StatementType;
  policy_tier: string;
  not_checked_reason: string | null;
  sources_status: SourcesStatus;
  sources_error: string | null;
  sources: Source[];
  sources_summary: string | null; // AI summary of the excerpts. Never a judgement
  sources_match: SourcesMatch | null;
  sources_route: SourcesRoute | null;
  counter_sources: Source[]; // from the second search (data / contested statements)
  counter_summary: string | null;
  research?: Research | null; // how the sources were researched (points, findings with quotes, other positions)
  sources_checked_at?: string | null;
}

/** A statement as shown in the home-page carousel and the Topics tab. */
export interface PreviewClaim {
  id: string;
  start_s: number;
  claim_text: string;
  speaker: string | null;
  pestle_area: Pestle;
  topic: string | null;
  topics: string[];
  statement_type: StatementType;
  sources_status: SourcesStatus;
  sources: Source[]; // without excerpts, to keep the home page small
  sources_summary: string | null;
  sources_match: SourcesMatch | null;
  sources_route: SourcesRoute | null;
  counter_sources: Source[];
  counter_summary: string | null;
  section_idx: number | null;
  statement_context: string | null;
  question?: string | null;
  asked_by?: string | null;
  question_kind?: "asked" | "implied" | null;
}

/** One Q&A question and the ids of the stored statements that answer it (written by the AI; the answers are the statements). */
export interface QaEntry { q: string; claim_ids: string[] }

export interface Episode {
  id: string;
  youtube_video_id: string;
  title: string;
  channel_id: string | null;
  channel_name: string;
  duration_s: number;
  published_at: string | null;
  status: string;
  skip_reason?: string | null;
  sources_batch?: string | null; // "running" while "Check sources for all statements" works through the video
  auto_sources?: boolean | null; // sources are looked up automatically for this video: no "Check sources" buttons
  summary?: string | null; // 2-3 sentences on what the video covers, written by the AI
  created_at: string;
  creator_id?: string | null;
  sections?: Section[];
  progress?: Progress | null;
  steps?: Step[] | null; // the analysis steps, kept after the run
  creator?: CreatorProfile | null; // the show's profile, if the channel is a known creator
  speakers?: EpisodeSpeaker[];
  qa?: QaEntry[] | null; // the Q&A page's questions; only loaded for a single video
  interaction?: Interaction | null; // the interview dynamic
  statement_counts: Partial<Record<StatementType, number>>; // every tagged statement, by type
  // Derived for the feed
  pestle_areas?: Pestle[];
  claim_texts?: string[];
  preview_claims?: PreviewClaim[]; // statements of every type, for the home carousel and the Topics tab
  with_sources?: number; // claims that have at least one source
  sources_checked_at?: string | null; // when sources were last looked up for any statement of the video
}

export interface EpisodeDetail extends Episode {
  claims: Claim[];
  creator: CreatorProfile | null;
  speakers: EpisodeSpeaker[];
}

/** A part of the conversation, written by the AI. */
export interface Section { idx: number; start_s: number; end_s: number; title: string; summary: string }

export type StepStatus = "pending" | "running" | "done" | "skipped";
export interface Step { key: string; label: string; status: StepStatus; detail?: string | null }
export interface Progress { label?: string; pct?: number; steps?: Step[] }

/** The neutral parts of a creator profile (the database never sends the bias and criticism notes). */
export interface CreatorProfile {
  id: string;
  podcast: string;
  youtube_channel_name: string;
  youtube_handles: string[];
  country: string;
  summary: string | null;
  public_profile: ProfileV2 & { hosts?: string; host_background?: string; host_bio?: string; topics?: string[]; known_for?: string; leaning?: string; leaning_basis?: string; public_opinion?: string };
}

/** Who speaks in a video, and their profile if one was found (neutral parts only). */
export interface EpisodeSpeaker {
  label: string;
  role: "host" | "guest" | null;
  statements: number;
  incentives?: Partial<Record<IncentiveTag, Incentive>> | null; // this person's incentive tags for this video
  speaker: {
    id: string; name: string; summary: string | null; sources: { url: string; title: string | null }[];
    public_profile: ProfileV2 & { role?: string; background?: string; affiliations?: string[]; topics?: string[]; leaning?: string; leaning_basis?: string; public_opinion?: string };
  } | null;
}

/** One row of the sidebar's video list. */
export interface SidebarVideo { id: string; videoId: string; title: string; channel: string; status: string; statements: number }

export interface ChannelPage {
  id: string;
  name: string;
  episodes: Episode[];
}

export type ReportKind = "wrong_quote" | "wrong_speaker" | "wrong_tag" | "wrong_time" | "bad_source" | "other";

export interface OpenReport {
  id: number;
  kind: ReportKind;
  note: string;
  created_at: string;
  claim: Pick<Claim, "id" | "start_s" | "speaker" | "claim_text" | "context_quote" | "statement_type">;
  episode: { title: string; youtube_video_id: string; channel_name: string };
}
