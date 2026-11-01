import { FeedView } from "@/components/feed/FeedView";
import { getFeed } from "@/lib/data";

export const revalidate = 10;

export default async function Home() {
  const episodes = await getFeed();
  return (
    <div className="wide">
      <h1 className="visually-hidden">Latest checked videos</h1>
      <FeedView episodes={episodes} />
    </div>
  );
}
