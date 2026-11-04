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
  tier: number; // display label only: 1 = official / peer-reviewed, 2 = established news or research, 3 = other
  excerpt: string; // text the search took from the page (may be empty)
  publish_date: string | null;
  rank: number; // the search engine's order, most relevant first
  kind?: "related" | "counter"; // which search found it: the statement's subject, or different figures / other views
}

export interface Claim {
  id: string;
  idx: number;
  start_s: number;
  speaker: string | null; // as identified by the AI
  claim_text: string; // AI paraphrase of what was said
  context_quote: string | null; // AI transcript of the spoken words
  statement_context: string | null; // AI: what was being discussed when it was said
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
}

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
  summary?: string | null; // 2-3 sentences on what the video covers, written by the AI
  created_at: string;
  creator_id?: string | null;
  sections?: Section[];
  progress?: Progress | null;
  creator?: CreatorProfile | null; // the show's profile, if the channel is a known creator
  speakers?: EpisodeSpeaker[];
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
  public_profile: { hosts?: string; host_background?: string; host_bio?: string; topics?: string[]; known_for?: string };
}

/** Who speaks in a video, and their profile if one was found (neutral parts only). */
export interface EpisodeSpeaker {
  label: string;
  role: "host" | "guest" | null;
  statements: number;
  speaker: {
    id: string; name: string; summary: string | null; sources: { url: string; title: string | null }[];
    public_profile: { role?: string; background?: string; affiliations?: string[]; topics?: string[] };
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
