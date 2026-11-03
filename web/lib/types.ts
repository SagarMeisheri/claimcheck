export type StatementType = "factual_claim" | "opinion" | "forecast" | "other";
/** Looking up sources for one statement. Only factual claims can leave "not_eligible". */
export type SourcesStatus = "not_eligible" | "not_requested" | "queued" | "searching" | "done" | "failed";
/** How directly a claim's sources address its specific point (relevance, never agreement). */
export type SourcesMatch = "high" | "medium" | "low";
export type Pestle = "political" | "economic" | "social" | "technological" | "legal" | "environmental";

/** One web search result for a claim, as the search returned it: shown for context, not checked or judged. */
export interface Source {
  url: string;
  title: string | null;
  tier: number; // display label only: 1 = official / peer-reviewed, 2 = established news or research, 3 = other
  excerpt: string; // text the search took from the page (may be empty)
  publish_date: string | null;
  rank: number; // the search engine's order, most relevant first
}

export interface Claim {
  id: string;
  idx: number;
  start_s: number;
  speaker: string | null; // as identified by the AI
  claim_text: string; // AI paraphrase of what was said
  context_quote: string | null; // AI transcript of the spoken words
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
  sources_batch?: string | null; // "running" while "Check sources for all claims" works through the video
  summary?: string | null; // 2-3 sentences on what the video covers, written by the AI
  created_at: string;
  statement_counts: Partial<Record<StatementType, number>>; // every tagged statement, by type
  // Derived for the feed
  pestle_areas?: Pestle[];
  claim_texts?: string[];
  preview_claims?: PreviewClaim[]; // statements of every type, for the home carousel and the Topics tab
  with_sources?: number; // claims that have at least one source
}

export interface EpisodeDetail extends Episode {
  claims: Claim[];
}

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
