import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ScorecardView, type View } from "@/components/watch/ScorecardView";
import { STATEMENT_TYPES } from "@/lib/statements";
import { getEpisodeByVideo } from "@/lib/data";

export const revalidate = 30;

type Props = {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ t?: string; play?: string; moment?: string; view?: string; match?: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const ep = await getEpisodeByVideo((await params).videoId);
  if (!ep) return { title: "Video not found" };
  return {
    title: ep.title,
    openGraph: { title: ep.title, images: [`https://i.ytimg.com/vi/${ep.youtube_video_id}/hqdefault.jpg`] },
  };
}

export default async function WatchPage({ params, searchParams }: Props) {
  const [{ videoId }, sp] = await Promise.all([params, searchParams]);
  const ep = await getEpisodeByVideo(videoId);
  if (!ep) notFound();
  const t = sp.t ? Number.parseInt(sp.t, 10) : null;
  return (
    <ScorecardView
      ep={ep}
      initialT={Number.isFinite(t) ? t : null}
      autoplay={sp.play === "1"}
      momentId={sp.moment ?? null}
      initialView={parseView(sp.view)}
      initialMatch={sp.match === "high" || sp.match === "medium" || sp.match === "low" ? sp.match : null}
    />
  );
}

/** ?view=all|with_sources|factual_claim|opinion|forecast|other. Old links (verified, flagged, hearsay, ...) still open. */
function parseView(v: string | undefined): View | null {
  if (!v) return null;
  if (v === "all" || v === "with_sources") return v;
  if (v in STATEMENT_TYPES) return v as View;
  if (["verified", "flagged", "checked"].includes(v)) return "with_sources";
  if (["hearsay", "analogy", "loaded_language"].includes(v)) return "other";
  return "all";
}
