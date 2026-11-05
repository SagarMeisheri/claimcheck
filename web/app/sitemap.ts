import type { MetadataRoute } from "next";
import { publicDb } from "@/lib/data";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

/** One entry per finished video. Empty if the database is unreachable. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  try {
    const { data, error } = await publicDb().from("episodes").select("youtube_video_id, updated_at")
      .eq("status", "done").order("created_at", { ascending: false }).limit(5000);
    if (error) throw error;
    return (data ?? []).map((e) => ({ url: `${SITE}/v/${e.youtube_video_id}`, lastModified: e.updated_at }));
  } catch (e) {
    console.error("sitemap", e);
    return [];
  }
}
