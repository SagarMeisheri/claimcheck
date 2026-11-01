"use server";

import { createHash } from "node:crypto";
import { headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { serviceDb } from "@/lib/data";
import { parseVideoId } from "@/lib/youtube";
import { VERDICTS } from "@/lib/verdicts";
import type { VerificationStatus } from "@/lib/types";

export type ActionResult = { ok: boolean; message: string; episodeId?: string; videoId?: string };

export type Preview = { videoId: string; title: string | null; channel: string | null; alreadyChecked: boolean };

/** Link preview for "Check a video": YouTube oEmbed (no API key) plus whether we've checked it. */
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
  const alreadyChecked = !!data && ["done", "in_review"].includes(data.status);
  return { videoId, title, channel, alreadyChecked };
}

const DAILY_LIMIT = Number(process.env.SUBMIT_PER_PERSON_PER_DAY ?? 5);

async function submitterHash(): Promise<string> {
  const h = await headers();
  const ip = (h.get("x-forwarded-for") ?? "").split(",")[0].trim() || h.get("x-real-ip") || "unknown";
  return createHash("sha256").update(`${process.env.SUBMITTER_SALT ?? ""}:${ip}`).digest("hex").slice(0, 32);
}

export async function submitVideo(_prev: ActionResult | null, form: FormData): Promise<ActionResult> {
  const url = String(form.get("url") ?? "");
  const videoId = parseVideoId(url);
  if (!videoId) return { ok: false, message: "That isn't a YouTube video link. Paste a link like youtube.com/watch?v=… or youtu.be/…" };

  const db = serviceDb();
  const existing = await db.from("episodes").select("id, status").eq("youtube_video_id", videoId).maybeSingle();
  if (existing.data && ["done", "in_review", "processing", "queued"].includes(existing.data.status)) {
    return { ok: true, message: "This video is already checked or in progress.", episodeId: existing.data.id, videoId };
  }

  // Guardrail: 5 submissions per person per day (hashed IP; no raw IPs stored).
  const who = await submitterHash();
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const { count } = await db.from("submissions").select("id", { count: "exact", head: true })
    .eq("submitter", who).gte("created_at", since);
  if ((count ?? 0) >= DAILY_LIMIT) {
    return { ok: false, message: `You've reached today's limit of ${DAILY_LIMIT} videos. Try again tomorrow.` };
  }
  await db.from("submissions").insert({ submitter: who, youtube_video_id: videoId });
  // Best-effort title from YouTube's oEmbed, so the home page shows the video straight away; the pipeline
  // fills in the rest (length, channel, publish date) as soon as its metadata call returns.
  const known = await previewVideo(url).catch(() => null);
  const ep = await db.from("episodes").upsert({ youtube_video_id: videoId, status: "queued", submitted_by: who,
    ...(known?.title ? { title: known.title } : {}) }, { onConflict: "youtube_video_id" }).select("id").single();
  if (ep.error) return { ok: false, message: "Couldn't queue the video. Try again in a minute." };

  const res = await fetch(`${process.env.PIPELINE_URL}/episodes`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
    body: JSON.stringify({ url: `https://www.youtube.com/watch?v=${videoId}`, episode_id: ep.data.id, submitted_by: who }),
  }).catch(() => null);
  revalidatePath("/");
  if (!res || !res.ok) {
    return { ok: false, message: "The checking service didn't respond. The video is saved and will be retried." };
  }
  return { ok: true, message: "Queued. Most videos take 10 to 30 minutes; political verdicts may wait for a reviewer.", episodeId: ep.data.id, videoId };
}

export async function sendFeedback(_prev: ActionResult | null, form: FormData): Promise<ActionResult> {
  const claimId = String(form.get("claim_id") ?? "");
  const note = String(form.get("note") ?? "").trim().slice(0, 2000);
  const suggested = String(form.get("suggested_verdict") ?? "");
  if (!note) return { ok: false, message: "Add a short reason so the reviewer knows what to check." };
  if (suggested && !(suggested in VERDICTS)) return { ok: false, message: "Pick a verdict from the list." };
  const { error } = await serviceDb().from("feedback").insert({
    claim_id: claimId, note, suggested_verdict: suggested || null, submitter: await submitterHash(),
  });
  return error ? { ok: false, message: "Couldn't send that. Try again." } : { ok: true, message: "ok" };
}

// --- On-demand verification -------------------------------------------------------------------

export type VerifyResult = { ok: boolean; status: VerificationStatus | null; message: string };

// Guardrails on the public Verify button. The per-video cost cap is enforced by the pipeline.
const VERIFY_PER_PERSON_PER_DAY = Number(process.env.VERIFY_PER_PERSON_PER_DAY ?? 10);
const VERIFY_SITE_PER_HOUR = Number(process.env.VERIFY_SITE_PER_HOUR ?? 120);
const STALE_MS = 30 * 60 * 1000; // a request stuck this long (e.g. service restarted) can be retried

/** Verify button: verifies one factual claim, once for everyone. False verdicts still wait for a reviewer. */
export async function requestVerification(claimId: string): Promise<VerifyResult> {
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return { ok: false, status: null, message: "Unknown claim." };
  const db = serviceDb();
  const { data: c } = await db.from("claims")
    .select("id, episode_id, statement_type, policy_tier, not_checked_reason, verification_status, verify_requested_at, episodes(youtube_video_id, status)")
    .eq("id", claimId).maybeSingle();
  if (!c) return { ok: false, status: null, message: "Unknown claim." };
  const status = c.verification_status as VerificationStatus;
  const videoId = (c as any).episodes?.youtube_video_id as string | undefined;

  if (status === "verified") return { ok: true, status, message: "Already verified." };
  if (status === "awaiting_review") return { ok: true, status, message: "Verified; a reviewer is checking the verdict before it's shown." };
  const stale = !!c.verify_requested_at && Date.now() - Date.parse(c.verify_requested_at) > STALE_MS;
  if ((status === "queued" || status === "verifying") && !stale) return { ok: true, status, message: "Already being verified." };
  if (c.statement_type !== "factual_claim" || c.policy_tier === "never" || c.not_checked_reason === "outside_policy"
      || status === "not_eligible") {
    return { ok: false, status, message: "Only factual claims can be verified. Opinions, forecasts and rhetoric are tagged instead." };
  }
  if (!["done", "in_review"].includes((c as any).episodes?.status)) {
    return { ok: false, status, message: "This video is still being analysed. Try again when it's finished." };
  }

  // Rate limits: per person per day (hashed IP, like submissions) and for the whole site per hour.
  const who = await submitterHash();
  const dayAgo = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const hourAgo = new Date(Date.now() - 3600 * 1000).toISOString();
  const [{ count: mine }, { count: site }] = await Promise.all([
    db.from("verify_requests").select("id", { count: "exact", head: true }).eq("requester", who).eq("outcome", "queued").gte("created_at", dayAgo),
    db.from("verify_requests").select("id", { count: "exact", head: true }).eq("outcome", "queued").gte("created_at", hourAgo),
  ]);
  if ((mine ?? 0) >= VERIFY_PER_PERSON_PER_DAY) {
    return { ok: false, status, message: `You've verified ${VERIFY_PER_PERSON_PER_DAY} claims today, the daily limit. Try again tomorrow.` };
  }
  if ((site ?? 0) >= VERIFY_SITE_PER_HOUR) {
    return { ok: false, status, message: "Lots of people are verifying claims right now. Try again in a few minutes." };
  }

  // Take the claim only if nobody else did in the meantime.
  const { data: taken } = await db.from("claims")
    .update({ verification_status: "queued", verify_requested_at: new Date().toISOString(), verify_error: null })
    .eq("id", claimId).eq("verification_status", status).select("id");
  if (!taken?.length) return { ok: true, status: "queued", message: "Already being verified." };
  const { data: reqRow } = await db.from("verify_requests")
    .insert({ claim_id: claimId, episode_id: c.episode_id, requester: who, outcome: "queued" }).select("id").single();

  const revertTo: VerificationStatus = status === "queued" || status === "verifying" ? "failed" : status;
  const res = await fetch(`${process.env.PIPELINE_URL}/claims/${encodeURIComponent(claimId)}/verify`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
    body: JSON.stringify({}),
  }).catch(() => null);
  if (!res || !res.ok) {
    const refused = !!res && (res.status === 409 || res.status === 404);
    const detail = refused ? String((await res.json().catch(() => ({})))?.detail ?? "") : "";
    const message = detail || "The checking service didn't respond. Try again in a few minutes.";
    await db.from("claims").update({ verification_status: refused ? revertTo : "failed", verify_error: message })
      .eq("id", claimId).eq("verification_status", "queued");
    if (reqRow) await db.from("verify_requests").update({ outcome: refused ? "rejected" : "failed" }).eq("id", reqRow.id);
    if (videoId) revalidatePath(`/v/${videoId}`);
    return { ok: false, status: refused ? revertTo : "failed", message };
  }
  if (videoId) revalidatePath(`/v/${videoId}`);
  return { ok: true, status: "verifying", message: "Verifying. This usually takes a minute or two." };
}

async function assertReviewer(): Promise<string> {
  const h = await headers();
  const auth = h.get("authorization") ?? "";
  const [user, pass] = Buffer.from(auth.replace(/^Basic /, ""), "base64").toString().split(":");
  if (!process.env.REVIEW_PASSWORD || user !== process.env.REVIEW_USER || pass !== process.env.REVIEW_PASSWORD) {
    throw new Error("Not authorised");
  }
  return user;
}

async function pipelineCancel(episodeId: string): Promise<boolean> {
  const res = await fetch(`${process.env.PIPELINE_URL}/episodes/${encodeURIComponent(episodeId)}/cancel`, {
    method: "POST", headers: { "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
  }).catch(() => null);
  return !!res?.ok;
}

/** Stops a queued or running check. Falls back to marking it skipped if the pipeline service is unreachable. */
export async function cancelEpisode(form: FormData): Promise<void> {
  await assertReviewer();
  const id = String(form.get("episode_id"));
  if (!(await pipelineCancel(id))) {
    await serviceDb().from("episodes").update({ status: "skipped", skip_reason: "Cancelled." })
      .eq("id", id).in("status", ["queued", "processing"]);
  }
  revalidatePath("/review");
  revalidatePath("/");
}

/** Removes a video and its claims. Verdicts that no other claim uses are removed too. */
export async function deleteEpisode(form: FormData): Promise<void> {
  await assertReviewer();
  const id = String(form.get("episode_id"));
  const db = serviceDb();
  await pipelineCancel(id);
  const { data: rows } = await db.from("claims").select("verdict_id").eq("episode_id", id);
  const verdictIds = [...new Set((rows ?? []).map((r) => r.verdict_id as string | null).filter(Boolean) as string[])];
  await db.from("episodes").delete().eq("id", id);
  if (verdictIds.length) {
    const { data: stillUsed } = await db.from("claims").select("verdict_id").in("verdict_id", verdictIds);
    const used = new Set((stillUsed ?? []).map((r) => r.verdict_id as string));
    const orphans = verdictIds.filter((v) => !used.has(v));
    if (orphans.length) await db.from("verdicts").delete().in("id", orphans);
  }
  revalidatePath("/review");
  revalidatePath("/");
}

export async function reviewVerdict(form: FormData): Promise<void> {
  const reviewer = await assertReviewer();
  const verdictId = String(form.get("verdict_id"));
  const decision = String(form.get("decision")); // approve | change
  const note = String(form.get("note") ?? "").slice(0, 2000) || null;
  const patch: Record<string, unknown> = { reviewer, reviewer_note: note, reviewed_at: new Date().toISOString() };
  if (decision === "approve") patch.review_status = "approved";
  else {
    const newVerdict = String(form.get("new_verdict"));
    if (!(newVerdict in VERDICTS)) throw new Error("Unknown verdict");
    patch.review_status = "changed";
    patch.verdict = newVerdict;
  }
  const db = serviceDb();
  await db.from("verdicts").update(patch).eq("id", verdictId).eq("review_status", "pending");
  // Claims waiting on this verdict (verified on demand or during the run) are now public.
  await db.from("claims").update({ verification_status: "verified" }).eq("verdict_id", verdictId).eq("verification_status", "awaiting_review");
  // Recompute public tallies for affected episodes, then close episodes with nothing left to review.
  const { data: rows } = await db.from("claims").select("episode_id").eq("verdict_id", verdictId);
  for (const epId of new Set((rows ?? []).map((r) => r.episode_id as string))) {
    await db.rpc("recompute_episode_tally", { p_episode_id: epId });
  }
  await db.rpc("refresh_episode_review_status");
  revalidatePath("/review");
  revalidatePath("/");
}
