import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { ChannelPage, Claim, Episode, EpisodeDetail, OpenReport, Pestle, PreviewClaim, Source, SourcesStatus } from "./types";
import { mergeCounts, typeOf } from "./statements";

const URL_ = process.env.NEXT_PUBLIC_SUPABASE_URL;
const ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY;

/** Public reads go through the anon key, so RLS and column grants decide what is visible. */
export function publicDb(): SupabaseClient {
  if (!URL_ || !ANON) throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are not set (see web/.env.example)");
  return createClient(URL_!, ANON!, { auth: { persistSession: false } });
}

/** Service role: server actions only (submissions, reports, rate limits, review). Never sent to the browser. */
export function serviceDb(): SupabaseClient {
  if (!URL_ || !SERVICE) throw new Error("NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set (see web/.env.example)");
  return createClient(URL_!, SERVICE, { auth: { persistSession: false } });
}

// --- Row mapping -------------------------------------------------------------------------

type EpisodeRow = {
  id: string; youtube_video_id: string; title: string | null; duration_s: number | null; published_at: string | null;
  status: string; skip_reason?: string | null; created_at: string; channel_id: string | null;
  statement_counts?: Record<string, number> | null; summary?: string | null; sources_batch_status?: string | null;
  channels: { name: string } | null;
};

const EP_COLS = "id, youtube_video_id, title, duration_s, published_at, status, skip_reason, statement_counts, summary, sources_batch_status, created_at, channel_id, channels(name)";
const SOURCE_COLS = "claim_sources(url, title, tier, quote, publish_date)";
const CLAIM_COLS = `id, idx, episode_id, start_s, speaker, claim_text, context_quote, pestle_area, topic, topics, statement_type, policy_tier, not_checked_reason, sources_status, sources_error, ${SOURCE_COLS}`;
const PUBLIC_STATUSES = ["done", "in_review", "processing", "queued"];

function toEpisode(r: EpisodeRow): Episode {
  return {
    id: r.id, youtube_video_id: r.youtube_video_id, title: r.title ?? "Untitled video",
    channel_id: r.channel_id, channel_name: r.channels?.name ?? "Submitted video",
    duration_s: r.duration_s ?? 0, published_at: r.published_at, status: r.status, skip_reason: r.skip_reason,
    statement_counts: mergeCounts(r.statement_counts ?? {}), summary: r.summary ?? null,
    sources_batch: r.sources_batch_status ?? null, created_at: r.created_at,
  };
}

function bestFirst(sources: Source[] | null | undefined): Source[] {
  return [...(sources ?? [])].sort((a, b) => a.tier - b.tier);
}

function toClaim(c: any): Claim {
  return {
    ...c,
    topics: (c.topics?.length ? c.topics : c.topic ? [c.topic] : []) as string[],
    statement_type: typeOf(c.statement_type),
    sources_status: (c.sources_status as SourcesStatus) ?? "not_eligible",
    sources: bestFirst(c.claim_sources),
    claim_sources: undefined,
  };
}

function toPreview(c: Claim): PreviewClaim {
  return {
    id: c.id, start_s: c.start_s, claim_text: c.claim_text, speaker: c.speaker, pestle_area: c.pestle_area, topic: c.topic,
    topics: c.topics, statement_type: c.statement_type, sources_status: c.sources_status, first_source: c.sources[0] ?? null,
  };
}

const PER_TYPE = 30; // statements per type kept for the home carousel tabs

/** Carousel content in the order said; at most PER_TYPE per type. Redacted statements are never shown. */
export function carouselStatements(claims: Claim[]): Claim[] {
  const seen: Record<string, number> = {};
  return claims.filter((c) => c.not_checked_reason !== "outside_policy")
    .sort((a, b) => a.start_s - b.start_s)
    .filter((c) => {
      seen[c.statement_type] = (seen[c.statement_type] ?? 0) + 1;
      return seen[c.statement_type] <= PER_TYPE;
    });
}

export function deriveFeedFields(ep: Episode, claims: Claim[]): Episode {
  const visible = claims.filter((c) => c.not_checked_reason !== "outside_policy");
  return {
    ...ep,
    pestle_areas: [...new Set(visible.map((c) => c.pestle_area))] as Pestle[],
    claim_texts: visible.map((c) => c.claim_text),
    preview_claims: carouselStatements(visible).map(toPreview),
    with_sources: visible.filter((c) => c.sources.length > 0).length,
  };
}

// --- Queries -------------------------------------------------------------------------------

export async function getFeed(limit = 40): Promise<Episode[]> {
  const db = publicDb();
  const { data, error } = await db.from("episodes").select(EP_COLS)
    .in("status", PUBLIC_STATUSES).order("created_at", { ascending: false }).limit(limit);
  if (error) throw error;
  const eps = (data as unknown as EpisodeRow[]).map(toEpisode);
  if (!eps.length) return [];
  const { data: claims } = await db.from("claims").select(CLAIM_COLS).in("episode_id", eps.map((e) => e.id))
    .order("start_s").limit(4000);
  const byEp = new Map<string, Claim[]>();
  for (const c of (claims ?? []).map(toClaim)) {
    const key = (c as any).episode_id as string;
    byEp.set(key, [...(byEp.get(key) ?? []), c]);
  }
  return eps.map((e) => deriveFeedFields(e, byEp.get(e.id) ?? []));
}

export async function getEpisodeByVideo(videoId: string): Promise<EpisodeDetail | null> {
  const db = publicDb();
  const { data: ep } = await db.from("episodes").select(EP_COLS).eq("youtube_video_id", videoId).maybeSingle();
  if (!ep) return null;
  const { data: claims, error } = await db.from("claims").select(CLAIM_COLS).eq("episode_id", (ep as any).id).order("start_s");
  if (error) throw error;
  return { ...toEpisode(ep as unknown as EpisodeRow), claims: (claims ?? []).map(toClaim) };
}

export async function getVideoIdForEpisode(id: string): Promise<string | null> {
  const { data } = await publicDb().from("episodes").select("youtube_video_id").eq("id", id).maybeSingle();
  return data?.youtube_video_id ?? null;
}

export async function getChannel(id: string): Promise<ChannelPage | null> {
  const db = publicDb();
  const { data: ch } = await db.from("channels").select("id, name").eq("id", id).maybeSingle();
  if (!ch) return null;
  const all = await getFeed(200);
  return { id: ch.id, name: ch.name, episodes: all.filter((e) => e.channel_id === id) };
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

/** Open "Report a problem" submissions, oldest first. Reviewer page only. */
export async function getOpenReports(): Promise<OpenReport[]> {
  const { data, error } = await serviceDb().from("feedback")
    .select("id, kind, note, created_at, claims(id, start_s, speaker, claim_text, context_quote, statement_type, episodes(title, youtube_video_id, channels(name)))")
    .eq("status", "open").order("created_at").limit(100);
  if (error) throw error;
  return (data ?? []).filter((r: any) => r.claims).map((r: any) => ({
    id: r.id, kind: r.kind, note: r.note, created_at: r.created_at,
    claim: { id: r.claims.id, start_s: r.claims.start_s, speaker: r.claims.speaker, claim_text: r.claims.claim_text,
             context_quote: r.claims.context_quote, statement_type: typeOf(r.claims.statement_type) },
    episode: { title: r.claims.episodes?.title ?? "", youtube_video_id: r.claims.episodes?.youtube_video_id ?? "",
               channel_name: r.claims.episodes?.channels?.name ?? "Submitted video" },
  }));
}

export type ClaimSources = { id: string; sources_status: SourcesStatus; sources_error: string | null; video_id: string | null; sources: Source[] };

/** Live state of one claim's source lookup, polled by the "Check sources" button. */
export async function getClaimSources(id: string): Promise<ClaimSources | null> {
  const { data } = await publicDb().from("claims")
    .select(`id, sources_status, sources_error, episodes(youtube_video_id), ${SOURCE_COLS}`)
    .eq("id", id).maybeSingle();
  if (!data) return null;
  const d = data as any;
  return { id: d.id, sources_status: d.sources_status, sources_error: d.sources_error,
           video_id: d.episodes?.youtube_video_id ?? null, sources: bestFirst(d.claim_sources) };
}
