import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";
import { publicDb } from "@/lib/data";

// Live status of one video, polled by the progress bar and the live-verification bar. Never cached.
export const dynamic = "force-dynamic";

// Last verified-claim count seen per video, so the cached pages are dropped the moment a new verdict lands.
const lastVerified = new Map<string, number>();

export async function GET(_req: Request, { params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  const db = publicDb();
  const { data } = await db.from("episodes").select("id, status, skip_reason, progress, statement_counts, auto_verify_status")
    .eq("youtube_video_id", videoId).maybeSingle();
  if (!data) {
    return NextResponse.json({ status: "unknown", skip_reason: null, label: null, pct: 0, statements: 0, auto_verify: null, verified: 0, verifying: 0 },
      { headers: { "Cache-Control": "no-store" } });
  }
  const { data: rows } = await db.from("claims").select("verification_status, verdict_id").eq("episode_id", data.id).limit(1000);
  const verified = (rows ?? []).filter((c) => c.verdict_id || c.verification_status === "awaiting_review").length;
  const verifying = (rows ?? []).filter((c) => c.verification_status === "verifying" || c.verification_status === "queued").length;
  if (lastVerified.get(videoId) !== verified) {
    if (lastVerified.has(videoId)) { revalidatePath("/"); revalidatePath(`/v/${videoId}`); }
    lastVerified.set(videoId, verified);
  }
  return NextResponse.json({
    status: data.status, skip_reason: data.skip_reason, label: data.progress?.label ?? null, pct: data.progress?.pct ?? 0,
    statements: Object.values((data.statement_counts ?? {}) as Record<string, number>).reduce((a, b) => a + (b || 0), 0),
    auto_verify: data.auto_verify_status ?? null, verified, verifying,
  }, { headers: { "Cache-Control": "no-store" } });
}
