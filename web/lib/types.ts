export type VerdictName = "supported" | "misleading" | "false" | "outdated" | "disputed" | "unverifiable";
export type Pestle = "political" | "economic" | "social" | "technological" | "legal" | "environmental";

export interface Citation {
  url: string; // empty = source link not attached yet
  title: string | null;
  tier: number;
  quote: string;
  summary?: boolean; // true = paraphrase of the source, not an exact quote (imported data only)
}

export interface Verdict {
  id: string;
  verdict: VerdictName;
  confidence: number;
  reasoning: string;
  evidence_grade: string;
  review_status: "not_needed" | "pending" | "approved" | "changed";
  escalated: boolean;
  downgrades?: string[];
  citations: Citation[];
}

export interface AlsoSaidIn {
  youtube_video_id: string;
  title: string;
  channel_name: string;
  start_s: number;
  claim_id: string;
}

export interface Claim {
  id: string;
  idx: number;
  start_s: number;
  speaker: string | null;
  claim_text: string;
  context_quote: string | null;
  pestle_area: Pestle;
  topic: string | null;
  claim_type: string;
  policy_tier: string;
  checkworthiness: number | null;
  not_checked_reason: string | null;
  verdict: Verdict | null; // null = not checked, or checked but awaiting review
  awaiting_review: boolean;
  also_said_in?: AlsoSaidIn[];
}

export type ClaimTab = "flagged" | "checked" | "unchecked" | "all";

export interface PreviewClaim {
  id: string;
  start_s: number;
  claim_text: string;
  speaker: string | null;
  verdict: VerdictName | null; // null = not checked, or with a reviewer
  not_checked_reason: string | null;
  awaiting_review: boolean;
  source_line: string | null; // "Publisher: what it says", shortened
  pestle_area: Pestle;
  topic: string | null;
}

export interface TopClaim {
  id: string;
  start_s: number;
  claim_text: string;
  verdict: VerdictName;
}

export interface Episode {
  id: string;
  youtube_video_id: string;
  title: string;
  channel_id: string | null;
  channel_name: string;
  channel_avatar: string | null;
  channel_track: "politics" | "finance_health";
  duration_s: number;
  published_at: string | null;
  status: string;
  skip_reason?: string | null;
  guest?: string | null;
  import_note?: string | null; // set when verdicts came from an outside analysis, not the pipeline
  tally: Partial<Record<VerdictName, number>>;
  not_checked: Record<string, number>;
  created_at: string;
  // Derived for the feed
  top_claim?: TopClaim | null;
  pestle_areas?: Pestle[];
  claim_texts?: string[];
  pending_count?: number;
  preview_claims?: PreviewClaim[]; // ordered for the home carousel
  published_claims?: PreviewClaim[]; // all published, for the Topics tab
  checked_count?: number;
  tab_claims?: Record<ClaimTab, PreviewClaim[]>; // first few claims per home-card tab
  tab_counts?: Record<ClaimTab, number>;
  video_pending?: boolean; // YouTube link not added yet (imported data)
}

export interface EpisodeDetail extends Episode {
  claims: Claim[];
}

export interface ChannelBalance {
  name: string;
  track: string;
  side: "supportive" | "critical" | "neutral";
  episodes: number;
  claims_checked: number;
  tally: Partial<Record<VerdictName, number>>;
}

export interface ChannelPage {
  id: string;
  name: string;
  avatar: string | null;
  track: string;
  episodes: Episode[];
  tally: Partial<Record<VerdictName, number>>;
}

export interface PendingReview {
  verdict: Verdict;
  claim: Claim;
  episode: Pick<Episode, "id" | "title" | "channel_name" | "youtube_video_id">;
}
