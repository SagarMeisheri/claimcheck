import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { VideoCard } from "@/components/feed/VideoCard";
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
        <Avatar name={ch.name} size={56} />
        <div>
          <h1>{ch.name}</h1>
          <p className="meta">{ch.episodes.length} analysed {ch.episodes.length === 1 ? "video" : "videos"}, submitted by visitors</p>
        </div>
        <FollowButton channelId={ch.id} />
      </header>
      <div className="vgrid">
        {ch.episodes.map((e) => <VideoCard key={e.id} ep={e} />)}
      </div>
    </div>
  );
}
