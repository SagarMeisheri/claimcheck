import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { QaBrowser } from "@/components/qa/QaBrowser";
import { getEpisodeByVideo } from "@/lib/data";
import { shortDate } from "@/lib/format";
import { trim } from "@/lib/notes";
import { hasQa, resolveQa } from "@/lib/qa";
import type { EpisodeDetail } from "@/lib/types";
import s from "./qa.module.css";

export const revalidate = 60;

type Props = { params: Promise<{ videoId: string }> };

/** Only finished videos that have Q&A get a page. */
async function load(videoId: string): Promise<EpisodeDetail | null> {
  const ep = await getEpisodeByVideo(videoId);
  return ep && ep.status === "done" && hasQa(ep) ? ep : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const ep = await load((await params).videoId);
  if (!ep) return { title: "Q&A not found", robots: { index: false } };
  const items = resolveQa(ep.qa, ep.claims);
  const title = `${ep.title}: questions and answers`;
  const description = trim(`${items.length} questions about this video, answered with what the speakers said and what web sources say. ${items.slice(0, 3).map((i) => i.q).join(" ")}`, 300);
  return {
    title, description,
    alternates: { canonical: `/qa/${ep.youtube_video_id}` },
    openGraph: { title, description, type: "article", images: [`https://i.ytimg.com/vi/${ep.youtube_video_id}/hqdefault.jpg`] },
  };
}

export default async function QaPage({ params }: Props) {
  const ep = await load((await params).videoId);
  if (!ep) notFound();
  const items = resolveQa(ep.qa, ep.claims);
  if (items.length === 0) notFound();
  const channel = ep.channel_id ? ep.channel_name : ep.creator?.podcast ?? null;
  const checked = ep.sources_checked_at ? shortDate(ep.sources_checked_at) : null;

  return (
    <article className={`wide ${s.page}`}>
      <p className={s.crumbs}><Link href="/">ClaimCheck</Link></p>
      <QaBrowser videoId={ep.youtube_video_id} title={ep.title} durationS={ep.duration_s} items={items}>
        <h1 className={s.title}>{ep.title}</h1>
        {channel && <p className={s.channel}>{channel}</p>}
        <p className={s.lead}>Questions a viewer might ask about this video. Each answer shows what the speakers said next to what web pages found for it say.</p>
        <p className={s.meta}>
          Questions and answers written by AI from the video · {items.length} questions
          {checked ? ` · sources looked up ${checked}` : ""}
        </p>
      </QaBrowser>

      <p className={s.note}>
        Answers are AI paraphrases of what was said, with the speaker as identified by AI. “Source match” shows how
        directly the search excerpts address the statement; it is not agreement and not a judgement of whether it is true.
      </p>
    </article>
  );
}
