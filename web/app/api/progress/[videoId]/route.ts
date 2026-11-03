import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";
import { publicDb } from "@/lib/data";

// Live status of one video, polled by the progress bar and the "Check sources for all" button. Never cached.
export const dynamic = "force-dynamic";

// Last count of claims with sources looked up, per video, so cached pages are dropped the moment a new result lands.
const lastDone = new Map<string, number>();

export async function GET(_req: Request, { params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  const db = publicDb();
  const { data } = await db.from("episodes").select("id, status, skip_reason, progress, statement_counts, sources_batch_status")
    .eq("youtube_video_id", videoId).maybeSingle();
  if (!data) {
    return NextResponse.json({ status: "unknown", skip_reason: null, label: null, pct: 0, statements: 0, batch: null, looked_up: 0, searching: 0 },
      { headers: { "Cache-Control": "no-store" } });
  }
  const { data: rows } = await db.from("claims").select("sources_status").eq("episode_id", data.id).limit(1000);
  const lookedUp = (rows ?? []).filter((c) => c.sources_status === "done").length;
  const searching = (rows ?? []).filter((c) => c.sources_status === "searching" || c.sources_status === "queued").length;
  if (lastDone.get(videoId) !== lookedUp) {
    if (lastDone.has(videoId)) { revalidatePath("/"); revalidatePath(`/v/${videoId}`); }
    lastDone.set(videoId, lookedUp);
  }
  return NextResponse.json({
    status: data.status, skip_reason: data.skip_reason, label: data.progress?.label ?? null, pct: data.progress?.pct ?? 0,
    statements: Object.values((data.statement_counts ?? {}) as Record<string, number>).reduce((a, b) => a + (b || 0), 0),
    batch: data.sources_batch_status ?? null, looked_up: lookedUp, searching,
  }, { headers: { "Cache-Control": "no-store" } });
}
