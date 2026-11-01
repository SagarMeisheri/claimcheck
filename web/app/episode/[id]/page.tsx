import { notFound, redirect } from "next/navigation";
import { getVideoIdForEpisode } from "@/lib/data";

// Old scorecard URLs redirect to the watch screen.
export default async function EpisodeRedirect({ params }: { params: Promise<{ id: string }> }) {
  const videoId = await getVideoIdForEpisode((await params).id);
  if (!videoId) notFound();
  redirect(`/v/${videoId}`);
}
