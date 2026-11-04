import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { ChannelPage, Claim, CreatorProfile, Episode, EpisodeDetail, EpisodeSpeaker, OpenReport, Pestle, PreviewClaim, Progress, Section, Source,
  SourcesMatch, SourcesStatus } from "./types";
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
  creator_id?: string | null; sections?: Section[] | null; progress?: Progress | null;
  channels: { name: string } | null;
};

const EP_COLS = "id, youtube_video_id, title, duration_s, published_at, status, skip_reason, statement_counts, summary, sources_batch_status, created_at, channel_id, creator_id, sections, progress, channels(name)";
const SOURCE_COLS = "claim_sources(url, title, tier, excerpt, publish_date, rank, kind)";
const CLAIM_COLS = `id, idx, episode_id, start_s, speaker, claim_text, context_quote, statement_context, section_idx, pestle_area, topic, topics, statement_type, policy_tier, not_checked_reason, sources_status, sources_error, sources_summary, sources_match, sources_route, counter_summary, sources_checked_at, ${SOURCE_COLS}`;
const CREATOR_COLS = "id, podcast, youtube_channel_name, youtube_handles, country, summary, public_profile";
const SPEAKER_COLS = "episode_id, label, role, statements, speakers(id, name, summary, sources, public_profile)";

function toSpeaker(r: any): EpisodeSpeaker {
  return { label: r.label, role: r.role, statements: r.statements, speaker: r.speakers ?? null };
}
const PUBLIC_STATUSES = ["done", "in_review", "processing", "queued"];

function toEpisode(r: EpisodeRow): Episode {
  return {
    id: r.id, youtube_video_id: r.youtube_video_id, title: r.title ?? "Untitled video",
    channel_id: r.channel_id, channel_name: r.channels?.name ?? "Submitted video",
    duration_s: r.duration_s ?? 0, published_at: r.published_at, status: r.status, skip_reason: r.skip_reason,
    statement_counts: mergeCounts(r.statement_counts ?? {}), summary: r.summary ?? null,
    sources_batch: r.sources_batch_status ?? null, created_at: r.created_at,
    creator_id: r.creator_id ?? null, sections: r.sections ?? [], progress: r.progress ?? null,
  };
}

/** Sources in the search engine's own order (most relevant first), from one search: the related one by default. */
function inSearchOrder(sources: Source[] | null | undefined, kind: "related" | "counter" = "related"): Source[] {
  return [...(sources ?? [])].filter((s) => (s.kind ?? "related") === kind).sort((a, b) => a.rank - b.rank);
}

function toClaim(c: any): Claim {
  return {
    ...c,
    topics: (c.topics?.length ? c.topics : c.topic ? [c.topic] : []) as string[],
    statement_type: typeOf(c.statement_type),
    sources_status: (c.sources_status as SourcesStatus) ?? "not_eligible",
    sources: inSearchOrder(c.claim_sources),
    counter_sources: inSearchOrder(c.claim_sources, "counter"),
    claim_sources: undefined,
  };
}

function toPreview(c: Claim): PreviewClaim {
  return {
    id: c.id, start_s: c.start_s, claim_text: c.claim_text, speaker: c.speaker, pestle_area: c.pestle_area, topic: c.topic,
    topics: c.topics, statement_type: c.statement_type, sources_status: c.sources_status,
    sources: c.sources.map((s) => ({ ...s, excerpt: "" })), sources_summary: c.sources_summary ?? null, sources_match: c.sources_match ?? null,
    sources_route: c.sources_route ?? null, counter_sources: c.counter_sources.map((s) => ({ ...s, excerpt: "" })),
    counter_summary: c.counter_summary ?? null, section_idx: c.section_idx ?? null, statement_context: c.statement_context ?? null,
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

/** The latest time sources were looked up for any of these statements. */
function lastChecked(claims: Claim[]): string | null {
  let last: string | null = null;
  for (const c of claims) if (c.sources_checked_at && (!last || c.sources_checked_at > last)) last = c.sources_checked_at;
  return last;
}

export function deriveFeedFields(ep: Episode, claims: Claim[]): Episode {
  const visible = claims.filter((c) => c.not_checked_reason !== "outside_policy");
  return {
    ...ep,
    sources_checked_at: lastChecked(visible),
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
  const creatorIds = [...new Set(eps.map((e) => e.creator_id).filter(Boolean))] as string[];
  const [{ data: claims }, { data: creators }, { data: speakers }] = await Promise.all([
    db.from("claims").select(CLAIM_COLS).in("episode_id", eps.map((e) => e.id)).order("start_s").limit(4000),
    creatorIds.length ? db.from("creators").select(CREATOR_COLS).in("id", creatorIds) : Promise.resolve({ data: [] as any[] }),
    db.from("episode_speakers").select(SPEAKER_COLS).in("episode_id", eps.map((e) => e.id)).order("statements", { ascending: false }),
  ]);
  const byEp = new Map<string, Claim[]>();
  for (const c of (claims ?? []).map(toClaim)) {
    const key = (c as any).episode_id as string;
    byEp.set(key, [...(byEp.get(key) ?? []), c]);
  }
  const creatorById = new Map((creators ?? []).map((c: any) => [c.id as string, c as CreatorProfile]));
  const speakersByEp = new Map<string, EpisodeSpeaker[]>();
  for (const r of speakers ?? []) speakersByEp.set((r as any).episode_id, [...(speakersByEp.get((r as any).episode_id) ?? []), toSpeaker(r)]);
  return eps.map((e) => ({
    ...deriveFeedFields(e, byEp.get(e.id) ?? []),
    creator: e.creator_id ? creatorById.get(e.creator_id) ?? null : null, speakers: speakersByEp.get(e.id) ?? [],
  }));
}

export async function getEpisodeByVideo(videoId: string): Promise<EpisodeDetail | null> {
  const db = publicDb();
  const { data: ep } = await db.from("episodes").select(EP_COLS).eq("youtube_video_id", videoId).maybeSingle();
  if (!ep) return null;
  const epId = (ep as any).id as string;
  const creatorId = (ep as any).creator_id as string | null;
  const [{ data: claims, error }, creator, { data: speakers }] = await Promise.all([
    db.from("claims").select(CLAIM_COLS).eq("episode_id", epId).order("start_s"),
    creatorId ? db.from("creators").select(CREATOR_COLS).eq("id", creatorId).maybeSingle().then((r) => r.data) : Promise.resolve(null),
    db.from("episode_speakers").select(SPEAKER_COLS).eq("episode_id", epId).order("statements", { ascending: false }),
  ]);
  if (error) throw error;
  return {
    ...toEpisode(ep as unknown as EpisodeRow), claims: (claims ?? []).map(toClaim),
    sources_checked_at: lastChecked((claims ?? []).map(toClaim)),
    creator: (creator as CreatorProfile | null) ?? null,
    speakers: (speakers ?? []).map(toSpeaker),
  };
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

export type ClaimSources = {
  id: string; sources_status: SourcesStatus; sources_error: string | null; video_id: string | null; sources: Source[]; sources_summary: string | null; sources_match: SourcesMatch | null;
  counter_sources: Source[]; counter_summary: string | null; sources_route: string | null;
};

/** Live state of one claim's source lookup, polled by the "Check sources" button. */
export async function getClaimSources(id: string): Promise<ClaimSources | null> {
  const { data } = await publicDb().from("claims")
    .select(`id, sources_status, sources_error, sources_summary, sources_match, sources_route, counter_summary, episodes(youtube_video_id), ${SOURCE_COLS}`)
    .eq("id", id).maybeSingle();
  if (!data) return null;
  const d = data as any;
  return { id: d.id, sources_status: d.sources_status, sources_error: d.sources_error,
           video_id: d.episodes?.youtube_video_id ?? null, sources: inSearchOrder(d.claim_sources), sources_summary: d.sources_summary ?? null, sources_match: d.sources_match ?? null,
           counter_sources: inSearchOrder(d.claim_sources, "counter"), counter_summary: d.counter_summary ?? null, sources_route: d.sources_route ?? null };
}
