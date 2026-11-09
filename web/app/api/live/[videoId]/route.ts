import { NextResponse } from "next/server";
import { publicDb } from "@/lib/data";

// The lookups in flight for one video, with what each has found so far. The page listens for these as they happen (Realtime); this is
// what it asks for when it first looks, after a dropped connection, and every few seconds while Realtime is not available. Never cached.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  const headers = { "Cache-Control": "no-store" };
  if (!/^[\w-]{6,20}$/.test(videoId)) return NextResponse.json({ claims: [] }, { status: 404, headers });
  const db = publicDb();
  const { data: ep } = await db.from("episodes").select("id").eq("youtube_video_id", videoId).maybeSingle();
  if (!ep) return NextResponse.json({ claims: [] }, { headers });
  const { data } = await db.from("claims").select("id, sources_status, sources_error, sources_route, qa_tags, research")
    .eq("episode_id", ep.id).in("sources_status", ["searching", "queued"]).limit(500);
  return NextResponse.json({ claims: data ?? [] }, { headers });
}
