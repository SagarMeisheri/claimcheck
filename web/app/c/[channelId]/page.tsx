import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { VideoCard } from "@/components/feed/VideoCard";
import { TallySentence, VerdictStrip } from "@/components/MiniBar";
import { Avatar } from "@/components/Thumb";
import { getChannel } from "@/lib/data";
import { FollowButton } from "./FollowButton";

export const revalidate = 120;
type Props = { params: Promise<{ channelId: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const ch = await getChannel((await params).channelId);
  return { title: ch ? ch.name : "Channel not found" };
}

export default async function ChannelPage({ params }: Props) {
  const ch = await getChannel((await params).channelId);
  if (!ch) notFound();
  return (
    <div className="wide">
      <header className="channel-head">
        <Avatar src={ch.avatar} name={ch.name} size={56} />
        <div>
          <h1>{ch.name}</h1>
          <p className="meta">{ch.episodes.length} checked {ch.episodes.length === 1 ? "video" : "videos"}</p>
        </div>
        <FollowButton channelId={ch.id} />
      </header>
      <section className="channel-record">
        <VerdictStrip tally={ch.tally} />
        <TallySentence tally={ch.tally} />
        <p className="meta">This is a record of what we&apos;ve checked, not a score for the channel.</p>
      </section>
      <div className="vgrid">
        {ch.episodes.map((e) => <VideoCard key={e.id} ep={e} />)}
      </div>
    </div>
  );
}
