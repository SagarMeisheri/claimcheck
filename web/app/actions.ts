"use server";

import { createHash } from "node:crypto";
import { headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { reviewerFromHeader } from "@/lib/auth";
import { serviceDb } from "@/lib/data";
import { parseVideoId } from "@/lib/youtube";
import type { ReportKind, SourcesStatus } from "@/lib/types";

export type ActionResult = { ok: boolean; message: string; episodeId?: string; videoId?: string };

export type Preview = { videoId: string; title: string | null; channel: string | null; alreadyDone: boolean };

/** Link preview for "Analyse a video": YouTube oEmbed (no API key) plus whether it has been analysed already. */
export async function previewVideo(url: string): Promise<Preview | null> {
  const videoId = parseVideoId(url);
  if (!videoId) return null;
  let title: string | null = null, channel: string | null = null;
  try {
    const r = await fetch(`https://www.youtube.com/oembed?format=json&url=${encodeURIComponent(`https://www.youtube.com/watch?v=${videoId}`)}`,
      { next: { revalidate: 3600 } });
    if (r.ok) { const j = await r.json(); title = j.title ?? null; channel = j.author_name ?? null; }
  } catch { /* preview is best-effort */ }
  const { data } = await serviceDb().from("episodes").select("status").eq("youtube_video_id", videoId).maybeSingle();
  const alreadyDone = !!data && ["done", "in_review"].includes(data.status);
  return { videoId, title, channel, alreadyDone };
}

const DAILY_LIMIT = Number(process.env.SUBMIT_PER_PERSON_PER_DAY ?? 5);

/** Salted hash of the visitor's IP, used only for rate limits (rows deleted after 30 days by the maintenance cron). */
async function visitorHash(): Promise<string> {
  const h = await headers();
  const ip = (h.get("x-forwarded-for") ?? "").split(",")[0].trim() || h.get("x-real-ip") || "unknown";
  return createHash("sha256").update(`${process.env.SUBMITTER_SALT ?? ""}:${ip}`).digest("hex").slice(0, 32);
}

function pipeline(path: string, body?: unknown): Promise<Response | null> {
  return fetch(`${process.env.PIPELINE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => null);
}

export async function submitVideo(_prev: ActionResult | null, form: FormData): Promise<ActionResult> {
  const url = String(form.get("url") ?? "");
  const videoId = parseVideoId(url);
  if (!videoId) return { ok: false, message: "That isn't a YouTube video link. Paste a link like youtube.com/watch?v=… or youtu.be/…" };

  const db = serviceDb();
  const existing = await db.from("episodes").select("id, status").eq("youtube_video_id", videoId).maybeSingle();
  if (existing.data && ["done", "in_review", "processing", "queued"].includes(existing.data.status)) {
    return { ok: true, message: "This video is already analysed or in progress.", episodeId: existing.data.id, videoId };
  }

  const who = await visitorHash();
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const { count } = await db.from("submissions").select("id", { count: "exact", head: true })
    .eq("submitter", who).gte("created_at", since);
  if (DAILY_LIMIT > 0 && (count ?? 0) >= DAILY_LIMIT) {
    return { ok: false, message: `You've reached today's limit of ${DAILY_LIMIT} videos. Try again tomorrow.` };
  }
  await db.from("submissions").insert({ submitter: who, youtube_video_id: videoId });
  // Best-effort title from YouTube's oEmbed, so the home page shows the video straight away.
  const known = await previewVideo(url).catch(() => null);
  const ep = await db.from("episodes").upsert({ youtube_video_id: videoId, status: "queued", submitted_by: who,
    ...(known?.title ? { title: known.title } : {}) }, { onConflict: "youtube_video_id" }).select("id").single();
  if (ep.error) return { ok: false, message: "Couldn't queue the video. Try again in a minute." };

  const res = await pipeline("/episodes", { url: `https://www.youtube.com/watch?v=${videoId}`, episode_id: ep.data.id, submitted_by: who });
  revalidatePath("/", "layout"); // the sidebar on every page lists the new video
  if (!res || !res.ok) {
    return { ok: false, message: "The analysis service didn't respond. Try again in a few minutes." };
  }
  return { ok: true, message: "Queued. Statements start appearing within a few minutes; long videos take longer.", episodeId: ep.data.id, videoId };
}

// --- Reports ("Report a problem") ---------------------------------------------------------------

const REPORT_KINDS: ReportKind[] = ["wrong_quote", "wrong_speaker", "wrong_tag", "wrong_time", "bad_source", "other"];

export async function sendReport(_prev: ActionResult | null, form: FormData): Promise<ActionResult> {
  const claimId = String(form.get("claim_id") ?? "");
  const kind = String(form.get("kind") ?? "other") as ReportKind;
  const note = String(form.get("note") ?? "").trim().slice(0, 2000);
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return { ok: false, message: "Unknown statement." };
  if (!REPORT_KINDS.includes(kind)) return { ok: false, message: "Pick what's wrong from the list." };
  if (!note) return { ok: false, message: "Add a short description so we know what to fix." };
  const { error } = await serviceDb().from("feedback").insert({ claim_id: claimId, kind, note, submitter: await visitorHash() });
  return error ? { ok: false, message: "Couldn't send that. Try again." } : { ok: true, message: "ok" };
}

// --- Sources -----------------------------------------------------------------------------------

export type SourcesResult = { ok: boolean; status: SourcesStatus | null; message: string };

// Limits on the public buttons. The per-video cost cap is enforced by the pipeline. Set a limit to 0 to turn it off.
const ONE_PER_PERSON_PER_DAY = Number(process.env.SOURCES_PER_PERSON_PER_DAY ?? 10);
const ONE_SITE_PER_HOUR = Number(process.env.SOURCES_SITE_PER_HOUR ?? 120);
const ALL_PER_PERSON_PER_DAY = Number(process.env.SOURCES_ALL_PER_PERSON_PER_DAY ?? 3);
const ALL_SITE_PER_HOUR = Number(process.env.SOURCES_ALL_SITE_PER_HOUR ?? 20);
const STALE_MS = 30 * 60 * 1000; // a request stuck this long (e.g. service restarted) can be retried

/** How many "queued" requests of this kind this person made today, and the whole site made in the last hour. */
async function requestCounts(kind: "one" | "all", who: string): Promise<{ mine: number; site: number }> {
  const db = serviceDb();
  const dayAgo = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const hourAgo = new Date(Date.now() - 3600 * 1000).toISOString();
  const [{ count: mine }, { count: site }] = await Promise.all([
    db.from("source_requests").select("id", { count: "exact", head: true }).eq("kind", kind).eq("requester", who).eq("outcome", "queued").gte("created_at", dayAgo),
    db.from("source_requests").select("id", { count: "exact", head: true }).eq("kind", kind).eq("outcome", "queued").gte("created_at", hourAgo),
  ]);
  return { mine: mine ?? 0, site: site ?? 0 };
}

/** "Check sources": looks up sources for one factual claim, once for everyone. */
export async function requestSources(claimId: string): Promise<SourcesResult> {
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return { ok: false, status: null, message: "Unknown statement." };
  const db = serviceDb();
  const { data: c } = await db.from("claims")
    .select("id, episode_id, statement_type, policy_tier, not_checked_reason, sources_status, sources_requested_at, episodes(youtube_video_id, status)")
    .eq("id", claimId).maybeSingle();
  if (!c) return { ok: false, status: null, message: "Unknown statement." };
  const status = c.sources_status as SourcesStatus;
  const videoId = (c as any).episodes?.youtube_video_id as string | undefined;

  if (status === "done") return { ok: true, status, message: "Sources have already been looked up." };
  const stale = !!c.sources_requested_at && Date.now() - Date.parse(c.sources_requested_at) > STALE_MS;
  if ((status === "queued" || status === "searching") && !stale) return { ok: true, status, message: "Already searching." };
  if (c.statement_type === "question" || c.statement_type === "story") {
    return { ok: false, status, message: "Questions and personal stories don't have sources to look up." };
  }
  if (c.policy_tier === "never" || c.not_checked_reason === "outside_policy" || status === "not_eligible") {
    return { ok: false, status, message: "This statement is outside our content policy." };
  }
  if (!["done", "in_review"].includes((c as any).episodes?.status)) {
    return { ok: false, status, message: "This video is still being analysed. Try again when it's finished." };
  }

  const who = await visitorHash();
  const { mine, site } = await requestCounts("one", who);
  if (ONE_PER_PERSON_PER_DAY > 0 && mine >= ONE_PER_PERSON_PER_DAY) {
    return { ok: false, status, message: `You've checked sources ${ONE_PER_PERSON_PER_DAY} times today, the daily limit. Try again tomorrow.` };
  }
  if (ONE_SITE_PER_HOUR > 0 && site >= ONE_SITE_PER_HOUR) {
    return { ok: false, status, message: "Lots of people are checking sources right now. Try again in a few minutes." };
  }

  // Take the claim only if nobody else did in the meantime.
  const { data: taken } = await db.from("claims")
    .update({ sources_status: "queued", sources_requested_at: new Date().toISOString(), sources_error: null })
    .eq("id", claimId).eq("sources_status", status).select("id");
  if (!taken?.length) return { ok: true, status: "queued", message: "Already searching." };
  const { data: reqRow } = await db.from("source_requests")
    .insert({ claim_id: claimId, episode_id: c.episode_id, requester: who, kind: "one" }).select("id").single();

  const revertTo: SourcesStatus = status === "queued" || status === "searching" ? "failed" : status;
  const res = await pipeline(`/claims/${encodeURIComponent(claimId)}/sources`, {});
  if (!res || !res.ok) {
    const refused = !!res && (res.status === 409 || res.status === 404);
    const detail = refused ? String((await res.json().catch(() => ({})))?.detail ?? "") : "";
    const message = detail || "The service didn't respond. Try again in a few minutes.";
    await db.from("claims").update({ sources_status: refused ? revertTo : "failed", sources_error: message })
      .eq("id", claimId).eq("sources_status", "queued");
    if (reqRow) await db.from("source_requests").update({ outcome: refused ? "rejected" : "failed" }).eq("id", reqRow.id);
    if (videoId) revalidatePath(`/v/${videoId}`);
    return { ok: false, status: refused ? revertTo : "failed", message };
  }
  if (videoId) revalidatePath(`/v/${videoId}`);
  return { ok: true, status: "searching", message: "Searching the web. This usually takes a few seconds." };
}

/** "Check sources for all statements": one press runs a web search for each statement of a video (up to 75). Only for videos
 *  whose sources have never been checked. */
export async function requestAllSources(videoId: string, recheck = false): Promise<{ ok: boolean; message: string }> {
  if (!/^[\w-]{6,20}$/.test(videoId)) return { ok: false, message: "Unknown video." };
  const db = serviceDb();
  const { data: ep } = await db.from("episodes").select("id, status, sources_batch_status").eq("youtube_video_id", videoId).maybeSingle();
  if (!ep) return { ok: false, message: "Unknown video." };
  if (!["done", "in_review"].includes(ep.status)) return { ok: false, message: "This video is still being analysed. Try again when it's finished." };
  if (ep.sources_batch_status === "running") return { ok: true, message: "Already checking sources for this video." };

  // Once any statement of the video has sources ("last checked"), the video isn't checked again as a whole.
  // A re-check (recheck) is the exception: it looks every answer up again with the current method.
  const { data: checked } = await db.from("claims").select("id").eq("episode_id", ep.id).not("sources_checked_at", "is", null).limit(1);
  if (checked?.length && !recheck) return { ok: false, message: "Sources have already been checked for this video." };

  const { data: eligible } = await db.from("claims").select("id").eq("episode_id", ep.id).not("statement_type", "in", "(question,story)")
    .in("sources_status", recheck ? ["not_requested", "failed", "done"] : ["not_requested", "failed"]).limit(1);
  if (!eligible?.length) return { ok: false, message: "Sources have already been looked up for every statement in this video." };

  const who = await visitorHash();
  const { mine, site } = await requestCounts("all", who);
  if (ALL_PER_PERSON_PER_DAY > 0 && mine >= ALL_PER_PERSON_PER_DAY) return { ok: false, message: `You've used "Check sources for all statements" ${ALL_PER_PERSON_PER_DAY} times today, the daily limit. Try again tomorrow.` };
  if (ALL_SITE_PER_HOUR > 0 && site >= ALL_SITE_PER_HOUR) return { ok: false, message: "Lots of people are checking sources right now. Try again in a few minutes." };

  const { data: reqRow } = await db.from("source_requests")
    .insert({ episode_id: ep.id, requester: who, kind: "all" }).select("id").single();
  await db.from("episodes").update({ sources_batch_status: "running" }).eq("id", ep.id); // the button shows progress straight away

  const res = await pipeline(`/episodes/${encodeURIComponent(ep.id)}/sources-all${recheck ? "?recheck=true" : ""}`);
  if (!res || !res.ok) {
    const detail = res ? String((await res.json().catch(() => ({})))?.detail ?? "") : "";
    if (res?.status === 409) return { ok: true, message: detail || "Already checking sources for this video." }; // it is running: keep the state
    await db.from("episodes").update({ sources_batch_status: null }).eq("id", ep.id);
    if (reqRow) await db.from("source_requests").update({ outcome: "failed" }).eq("id", reqRow.id);
    return { ok: false, message: detail || "The service didn't respond. Try again in a few minutes." };
  }
  revalidatePath(`/v/${videoId}`);
  return { ok: true, message: "Searching sources for the claims. Each result appears as soon as it is ready." };
}

// --- Reviewer ----------------------------------------------------------------------------------

async function assertReviewer(): Promise<string> {
  const who = reviewerFromHeader((await headers()).get("authorization"));
  if (!who) throw new Error("Not authorised");
  return who;
}

/** Stops a queued or running analysis. Falls back to marking it skipped if the pipeline service is unreachable. */
export async function cancelEpisode(form: FormData): Promise<void> {
  await assertReviewer();
  const id = String(form.get("episode_id"));
  const res = await pipeline(`/episodes/${encodeURIComponent(id)}/cancel`);
  if (!res?.ok) {
    await serviceDb().from("episodes").update({ status: "skipped", skip_reason: "Cancelled." })
      .eq("id", id).in("status", ["queued", "processing"]);
  }
  revalidatePath("/", "layout"); // the sidebar and /review
}

/** Removes a video, its statements and their sources (cascade). Old verdict rows stay hidden in the database. */
export async function deleteEpisode(form: FormData): Promise<void> {
  await assertReviewer();
  const id = String(form.get("episode_id"));
  await pipeline(`/episodes/${encodeURIComponent(id)}/cancel`);
  await serviceDb().from("episodes").delete().eq("id", id);
  revalidatePath("/", "layout"); // the sidebar and /review
}

/** Closes a report: "accepted" once the problem is fixed (or the statement removed), "rejected" if nothing was wrong. */
export async function resolveReport(form: FormData): Promise<void> {
  await assertReviewer();
  const id = Number(form.get("report_id"));
  const status = String(form.get("status"));
  if (!Number.isInteger(id) || !["accepted", "rejected"].includes(status)) throw new Error("Bad request");
  await serviceDb().from("feedback").update({ status }).eq("id", id).eq("status", "open");
  revalidatePath("/review");
}

/** Hides one statement for everyone (e.g. a wrong quote or speaker that was reported). */
export async function hideStatement(form: FormData): Promise<void> {
  await assertReviewer();
  const claimId = String(form.get("claim_id"));
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) throw new Error("Bad request");
  const db = serviceDb();
  const { data } = await db.from("claims").update({
    not_checked_reason: "outside_policy", claim_text: "[Not shown: removed after a report]", context_quote: null, speaker: null,
    topics: [], sources_status: "not_eligible",
  }).eq("id", claimId).select("episodes(youtube_video_id)").maybeSingle();
  await db.from("claim_sources").delete().eq("claim_id", claimId);
  const videoId = (data as any)?.episodes?.youtube_video_id;
  if (videoId) revalidatePath(`/v/${videoId}`);
  revalidatePath("/review");
}
