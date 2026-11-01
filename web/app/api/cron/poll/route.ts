import { NextResponse } from "next/server";
import { serviceDb } from "@/lib/data";

// Vercel Cron: polls launch channels' RSS feeds and queues new videos for checking.
// Political channels are processed side-by-side so the weekly balance stays even.
export const dynamic = "force-dynamic";
const MAX_PER_RUN = 8;

export async function GET(req: Request) {
  if (req.headers.get("authorization") !== `Bearer ${process.env.CRON_SECRET}`) {
    return new NextResponse("unauthorised", { status: 401 });
  }
  const db = serviceDb();
  const { data: channels } = await db.from("channels").select("id, youtube_channel_id, track, perceived_lean, rss_url").eq("active", true);

  // This week's political episode count per side, so the side that is behind goes first.
  const weekAgo = new Date(Date.now() - 7 * 86400e3).toISOString();
  const { data: recent } = await db.from("episodes").select("channel_id, channels(track, perceived_lean)")
    .gte("created_at", weekAgo).in("status", ["queued", "processing", "in_review", "done"]);
  const sideCount: Record<string, number> = { supportive: 0, critical: 0, neutral: 0 };
  for (const r of (recent ?? []) as any[]) if (r.channels?.track === "politics") sideCount[r.channels.perceived_lean]++;

  const candidates: { videoId: string; channelId: string; side: string; published: number }[] = [];
  const since = Date.now() - 2 * 86400e3;
  for (const ch of channels ?? []) {
    const xml = await fetch(ch.rss_url, { cache: "no-store" }).then((r) => (r.ok ? r.text() : "")).catch(() => "");
    for (const entry of xml.split("<entry>").slice(1)) {
      const id = entry.match(/<yt:videoId>([^<]+)<\/yt:videoId>/)?.[1];
      const pub = Date.parse(entry.match(/<published>([^<]+)<\/published>/)?.[1] ?? "");
      if (id && pub > since) candidates.push({ videoId: id, channelId: ch.id, published: pub,
        side: ch.track === "politics" ? ch.perceived_lean : "finance_health" });
    }
  }
  if (!candidates.length) return NextResponse.json({ queued: 0 });
  const { data: existing } = await db.from("episodes").select("youtube_video_id").in("youtube_video_id", candidates.map((c) => c.videoId));
  const seen = new Set((existing ?? []).map((e) => e.youtube_video_id));
  const fresh = candidates.filter((c) => !seen.has(c.videoId))
    .sort((a, b) => (sideCount[a.side] ?? 0) - (sideCount[b.side] ?? 0) || b.published - a.published)
    .slice(0, MAX_PER_RUN);

  let queued = 0;
  for (const c of fresh) {
    const ep = await db.from("episodes").insert({ youtube_video_id: c.videoId, channel_id: c.channelId, status: "queued" }).select("id").single();
    if (ep.error) continue;
    const res = await fetch(`${process.env.PIPELINE_URL}/episodes`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
      body: JSON.stringify({ url: `https://www.youtube.com/watch?v=${c.videoId}`, episode_id: ep.data.id }),
    }).catch(() => null);
    if (res?.ok) { queued++; if (c.side in sideCount) sideCount[c.side]++; }
  }
  return NextResponse.json({ queued, candidates: candidates.length });
}
