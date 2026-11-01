import { NextResponse } from "next/server";
import { publicDb } from "@/lib/data";

// Live status of one video's check, polled by the progress bar. Never cached.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  const { data } = await publicDb().from("episodes").select("status, skip_reason, progress, statement_counts")
    .eq("youtube_video_id", videoId).maybeSingle();
  const body = data
    ? { status: data.status, skip_reason: data.skip_reason, label: data.progress?.label ?? null, pct: data.progress?.pct ?? 0,
        statements: Object.values((data.statement_counts ?? {}) as Record<string, number>).reduce((a, b) => a + (b || 0), 0) }
    : { status: "unknown", skip_reason: null, label: null, pct: 0, statements: 0 };
  return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
}
