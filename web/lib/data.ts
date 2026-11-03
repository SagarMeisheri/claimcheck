import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type {
  AlsoSaidIn, ChannelBalance, ClaimOutcome, ChannelPage, Claim, Episode, EpisodeDetail, PendingReview, Pestle, PreviewClaim, Verdict,
  VerdictName, VerificationStatus,
} from "./types";

const URL_ = process.env.NEXT_PUBLIC_SUPABASE_URL;
const ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY;

/** Public reads go through the anon key, so RLS decides what is visible. */
export function publicDb(): SupabaseClient {
  if (!URL_ || !ANON) throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are not set (see web/.env.example)");
  return createClient(URL_!, ANON!, { auth: { persistSession: false } });
}

/** Service role: server actions only (submissions, feedback, review). Never sent to the browser. */
export function serviceDb(): SupabaseClient {
  if (!URL_ || !SERVICE) throw new Error("NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set (see web/.env.example)");
  return createClient(URL_!, SERVICE, { auth: { persistSession: false } });
}

// --- Derived fields used by the feed ---------------------------------------------------

const NOTABLE: VerdictName[] = ["false", "misleading", "disputed", "outdated"];

function toPreview(c: Claim): PreviewClaim {
  const s = c.verdict?.citations[0];
  return {
    id: c.id, start_s: c.start_s, claim_text: c.claim_text, speaker: c.speaker, verdict: c.verdict?.verdict ?? null, basis: c.verdict?.basis,
    not_checked_reason: c.not_checked_reason, awaiting_review: c.awaiting_review,
    source_line: s ? `${s.title ?? "Source"}: ${s.quote}` : null, pestle_area: c.pestle_area, topic: c.topic, topics: c.topics,
    statement_type: c.statement_type, verification_status: c.verification_status,
  };
}

/**
 * Carousel order: the most significant Supported claim first (so a creator's row never reads as only
 * their mistakes), then flagged claims by severity and importance, then the remaining checked claims.
 */
export function carouselOrder(published: Claim[]): Claim[] {
  const byWorth = (a: Claim, b: Claim) => (b.checkworthiness ?? 0) - (a.checkworthiness ?? 0);
  const supported = published.filter((c) => c.verdict!.verdict === "supported").sort(byWorth);
  const flagged = published.filter((c) => NOTABLE.includes(c.verdict!.verdict))
    .sort((a, b) => NOTABLE.indexOf(a.verdict!.verdict) - NOTABLE.indexOf(b.verdict!.verdict) || byWorth(a, b));
  const used = new Set([supported[0]?.id, ...flagged.map((c) => c.id)]);
  const rest = published.filter((c) => !used.has(c.id)).sort(byWorth);
  return [...(supported[0] ? [supported[0]] : []), ...flagged, ...rest];
}

/** Feed fields. `claims` holds only claims with a verdict row (public, or hidden while awaiting review). */
const PER_TYPE = 30; // statements per type kept for the home carousel tabs

/** Carousel content: verified claims first, then the other statements in the order they were said; at most PER_TYPE per type. */
export function carouselStatements(published: Claim[], unverified: Claim[]): Claim[] {
  const visible = unverified.filter((c) => c.not_checked_reason !== "outside_policy")
    .sort((a, b) => a.start_s - b.start_s);
  const seen: Record<string, number> = {};
  return [...carouselOrder(published), ...visible].filter((c) => {
    seen[c.statement_type] = (seen[c.statement_type] ?? 0) + 1;
    return seen[c.statement_type] <= PER_TYPE;
  });
}

export function deriveFeedFields(ep: Episode, claims: Claim[], unverified: Claim[] = []): Episode {
  const published = claims.filter((c) => c.verdict);
  const notable = published
    .filter((c) => NOTABLE.includes(c.verdict!.verdict))
    .sort((a, b) => NOTABLE.indexOf(a.verdict!.verdict) - NOTABLE.indexOf(b.verdict!.verdict)
      || (b.checkworthiness ?? 0) - (a.checkworthiness ?? 0));
  const top = notable[0];
  return {
    ...ep,
    top_claim: top ? { id: top.id, start_s: top.start_s, claim_text: top.claim_text, verdict: top.verdict!.verdict } : null,
    pestle_areas: [...new Set(published.map((c) => c.pestle_area))] as Pestle[],
    claim_texts: published.map((c) => c.claim_text),
    pending_count: claims.filter((c) => c.awaiting_review).length,
    preview_claims: carouselStatements(published, unverified).map(toPreview),
    published_claims: published.map(toPreview),
    checked_count: published.length,
  };
}

// --- Row mapping -------------------------------------------------------------------------

type EpisodeRow = {
  id: string; youtube_video_id: string; title: string | null; duration_s: number | null; published_at: string | null;
  status: string; skip_reason?: string | null; tally: Record<string, number>; not_checked: Record<string, number>;
  created_at: string; channel_id: string | null; statement_counts?: Record<string, number> | null; summary?: string | null; auto_verify_status?: string | null;
  channels: { name: string; track: string; avatar_url: string | null } | null;
};

const EP_COLS = "id, youtube_video_id, title, duration_s, published_at, status, skip_reason, tally, not_checked, statement_counts, summary, auto_verify_status, created_at, channel_id, channels(name, track, avatar_url)";
const CLAIM_COLS = "id, idx, start_s, speaker, claim_text, context_quote, pestle_area, topic, topics, claim_type, statement_type, tag_note, verification_status, verify_error, policy_tier, checkworthiness, not_checked_reason, verdict_id, episode_id, verdicts(id, verdict, confidence, reasoning, score, correction, basis, evidence_grade, review_status, escalated, citations(url, title, tier, quote))";

function toEpisode(r: EpisodeRow): Episode {
  return {
    id: r.id, youtube_video_id: r.youtube_video_id, title: r.title ?? "Untitled video",
    channel_id: r.channel_id, channel_name: r.channels?.name ?? "Submitted video",
    channel_avatar: r.channels?.avatar_url ?? null,
    channel_track: (r.channels?.track as Episode["channel_track"]) ?? "finance_health",
    duration_s: r.duration_s ?? 0, published_at: r.published_at, status: r.status, skip_reason: r.skip_reason,
    tally: r.tally ?? {}, not_checked: r.not_checked ?? {}, statement_counts: r.statement_counts ?? {}, summary: r.summary ?? null, auto_verify: r.auto_verify_status ?? null, created_at: r.created_at,
  };
}

function toClaim(c: any): Claim {
  return {
    ...c,
    topics: (c.topics?.length ? c.topics : c.topic ? [c.topic] : []) as string[],
    // RLS hides verdicts awaiting review: the claim has a verdict_id but the join comes back empty.
    verdict: (c.verdicts as Verdict | null) ?? null,
    awaiting_review: Boolean(c.verdict_id && !c.verdicts) || c.verification_status === "awaiting_review",
    statement_type: c.statement_type ?? (c.claim_type === "fact" ? "factual_claim" : "other"),
    verification_status: (c.verification_status as VerificationStatus) ?? (c.verdict_id ? "verified" : "not_eligible"),
  };
}

// --- Queries -------------------------------------------------------------------------------

export async function getFeed(limit = 40): Promise<Episode[]> {
  const db = publicDb();
  const { data, error } = await db.from("episodes").select(EP_COLS)
    .in("status", ["done", "in_review", "processing", "queued"]).order("created_at", { ascending: false }).limit(limit);
  if (error) throw error;
  const eps = (data as unknown as EpisodeRow[]).map(toEpisode);
  if (!eps.length) return [];
  // Verified claims (with verdict and sources); type counts come from episodes.statement_counts.
  const { data: claims } = await db.from("claims").select(CLAIM_COLS).in("episode_id", eps.map((e) => e.id))
    .not("verdict_id", "is", null).limit(1000);
  const byEp = new Map<string, Claim[]>();
  for (const c of (claims ?? []).map(toClaim)) {
    const key = (c as any).episode_id as string;
    byEp.set(key, [...(byEp.get(key) ?? []), c]);
  }
  // The other statements (no verdict yet), without verdict joins, so the carousel can show every type.
  const { data: rest } = await db.from("claims")
    .select("id, idx, start_s, speaker, claim_text, pestle_area, topic, topics, statement_type, verification_status, policy_tier, not_checked_reason, verdict_id, episode_id")
    .in("episode_id", eps.map((e) => e.id)).is("verdict_id", null).order("start_s").limit(3000);
  const restByEp = new Map<string, Claim[]>();
  for (const c of (rest ?? []).map(toClaim)) {
    const key = (c as any).episode_id as string;
    restByEp.set(key, [...(restByEp.get(key) ?? []), c]);
  }
  return eps.map((e) => deriveFeedFields(e, byEp.get(e.id) ?? [], restByEp.get(e.id) ?? []));
}

async function withAlsoSaidIn(db: SupabaseClient, ep: EpisodeDetail): Promise<EpisodeDetail> {
  const ids = ep.claims.map((c) => c.verdict?.id).filter(Boolean) as string[];
  if (!ids.length) return ep;
  const { data } = await db.from("claims")
    .select("id, start_s, verdict_id, episode_id, episodes(youtube_video_id, title, channels(name))")
    .in("verdict_id", ids).neq("episode_id", ep.id).limit(200);
  const byVerdict = new Map<string, AlsoSaidIn[]>();
  for (const r of (data ?? []) as any[]) {
    const item: AlsoSaidIn = { youtube_video_id: r.episodes?.youtube_video_id, title: r.episodes?.title ?? "",
      channel_name: r.episodes?.channels?.name ?? "Submitted video", start_s: r.start_s, claim_id: r.id };
    byVerdict.set(r.verdict_id, [...(byVerdict.get(r.verdict_id) ?? []), item]);
  }
  return { ...ep, claims: ep.claims.map((c) => ({ ...c, also_said_in: c.verdict ? byVerdict.get(c.verdict.id) ?? [] : [] })) };
}

export async function getEpisodeByVideo(videoId: string): Promise<EpisodeDetail | null> {
  const db = publicDb();
  const { data: ep } = await db.from("episodes").select(EP_COLS).eq("youtube_video_id", videoId).maybeSingle();
  if (!ep) return null;
  const { data: claims, error } = await db.from("claims").select(CLAIM_COLS).eq("episode_id", (ep as any).id).order("start_s");
  if (error) throw error;
  return withAlsoSaidIn(db, { ...toEpisode(ep as unknown as EpisodeRow), claims: (claims ?? []).map(toClaim) });
}

export async function getVideoIdForEpisode(id: string): Promise<string | null> {
  const { data } = await publicDb().from("episodes").select("youtube_video_id").eq("id", id).maybeSingle();
  return data?.youtube_video_id ?? null;
}

export async function getChannel(id: string): Promise<ChannelPage | null> {
  const sum = (eps: Episode[]) => {
    const t: Record<string, number> = {};
    for (const e of eps) for (const [k, n] of Object.entries(e.tally)) t[k] = (t[k] ?? 0) + (n ?? 0);
    return t;
  };
  const db = publicDb();
  const { data: ch } = await db.from("channels").select("id, name, track, avatar_url").eq("id", id).maybeSingle();
  if (!ch) return null;
  const all = await getFeed(200);
  const eps = all.filter((e) => e.channel_id === id);
  return { id: ch.id, name: ch.name, avatar: ch.avatar_url, track: ch.track, episodes: eps, tally: sum(eps) };
}

export async function getBalance(): Promise<ChannelBalance[]> {
  // Service role: needs the internal perceived_lean column, but only aggregates leave this function.
  const { data, error } = await serviceDb().from("channels")
    .select("name, track, perceived_lean, episodes(status, tally)").eq("active", true).eq("polled", true); // curated channels only
  if (error) throw error;
  return (data ?? []).map((ch: any) => {
    const eps = (ch.episodes ?? []).filter((e: any) => ["done", "in_review"].includes(e.status));
    const tally: Record<string, number> = {};
    for (const e of eps) for (const [k, v] of Object.entries(e.tally ?? {})) tally[k] = (tally[k] ?? 0) + (v as number);
    return { name: ch.name, track: ch.track, side: ch.perceived_lean, episodes: eps.length,
             claims_checked: Object.values(tally).reduce((a, b) => a + b, 0), tally };
  }).filter((c) => c.episodes > 0);
}

export type AdminEpisode = { id: string; youtube_video_id: string; title: string | null; status: string;
  skip_reason: string | null; created_at: string; cost_usd: number | null };

/** Every episode, newest first, including ones the public can't see. Reviewer page only. */
export async function getAllEpisodes(): Promise<AdminEpisode[]> {
  const { data, error } = await serviceDb().from("episodes")
    .select("id, youtube_video_id, title, status, skip_reason, created_at, cost_usd").order("created_at", { ascending: false }).limit(100);
  if (error) throw error;
  return (data ?? []) as AdminEpisode[];
}

export async function getPendingReviews(): Promise<PendingReview[]> {
  const { data, error } = await serviceDb().from("verdicts")
    .select("id, verdict, confidence, reasoning, score, correction, evidence_grade, review_status, escalated, downgrades, citations(url, title, tier, quote), claims(id, idx, start_s, speaker, claim_text, context_quote, pestle_area, topic, claim_type, statement_type, tag_note, verification_status, policy_tier, checkworthiness, not_checked_reason, episodes(id, title, youtube_video_id, channels(name)))")
    .eq("review_status", "pending").order("created_at").limit(50);
  if (error) throw error;
  return (data ?? []).flatMap((v: any) => (v.claims ?? []).slice(0, 1).map((c: any) => ({
    verdict: { ...v, claims: undefined },
    claim: { ...c, verdict: null, awaiting_review: true, episodes: undefined },
    episode: { id: c.episodes.id, title: c.episodes.title, youtube_video_id: c.episodes.youtube_video_id,
               channel_name: c.episodes.channels?.name ?? "Submitted video" },
  })));
}

export async function getClaimForCard(id: string): Promise<{ claim: Claim; episode: Episode } | null> {
  const db = publicDb();
  const { data: c } = await db.from("claims").select(CLAIM_COLS).eq("id", id).maybeSingle();
  if (!c) return null;
  const { data: ep } = await db.from("episodes").select(EP_COLS).eq("id", (c as any).episode_id).maybeSingle();
  if (!ep) return null;
  return { claim: toClaim(c), episode: toEpisode(ep as unknown as EpisodeRow) };
}

export type ClaimStatus = { id: string; verification_status: VerificationStatus; verify_error: string | null; video_id: string | null; outcome: ClaimOutcome | null };

/** Live verification state of one claim. The verdict is included only when it is public (RLS hides it while awaiting review). */
export async function getClaimStatus(id: string): Promise<ClaimStatus | null> {
  const { data } = await publicDb().from("claims")
    .select("id, verification_status, verify_error, episodes(youtube_video_id), verdicts(verdict, reasoning, score, correction, citations(url, title, tier, quote))")
    .eq("id", id).maybeSingle();
  if (!data) return null;
  const d = data as any;
  const v = d.verdicts;
  const outcome: ClaimOutcome | null = v ? {
    verdict: v.verdict, score: v.score ?? null, reasoning: v.reasoning, correction: v.correction ?? null,
    sources: (v.citations ?? []).slice(0, 3),
  } : null;
  return { id: d.id, verification_status: d.verification_status, verify_error: d.verify_error, video_id: d.episodes?.youtube_video_id ?? null, outcome };
}
