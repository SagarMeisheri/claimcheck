import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ScorecardView, type View } from "@/components/watch/ScorecardView";
import { STATEMENT_TYPES } from "@/lib/statements";
import { getEpisodeByVideo } from "@/lib/data";

export const revalidate = 30;

type Props = {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ t?: string; play?: string; moment?: string; view?: string; topic?: string }>;
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
      initialTopic={sp.topic ?? null}
    />
  );
}

/** ?view=all|verified|factual_claim|opinion|... (old links: flagged/checked -> verified, unchecked/topics -> all). */
function parseView(v: string | undefined): View | null {
  if (!v) return null;
  if (v === "all" || v === "verified") return v;
  if (v in STATEMENT_TYPES) return v as View;
  if (v === "flagged" || v === "checked") return "verified";
  if (v === "unchecked" || v === "topics") return "all";
  return null;
}
