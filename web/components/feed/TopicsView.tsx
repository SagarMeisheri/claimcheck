import Link from "next/link";
import type { Episode, PreviewClaim } from "@/lib/types";
import { PESTLE, clock, domain, topicLabel } from "@/lib/format";
import { typeOf } from "@/lib/statements";

type Row = PreviewClaim & { videoId: string; videoTitle: string; channel: string };

/** Claims from every video, grouped by subject, each with the first source the search found (if any). Nothing is judged. */
export function TopicsView({ episodes }: { episodes: Episode[] }) {
  const rows: Row[] = episodes.flatMap((e) => (e.preview_claims ?? [])
    .filter((c) => typeOf(c.statement_type) === "factual_claim")
    .map((c) => ({ ...c, videoId: e.youtube_video_id, videoTitle: e.title, channel: e.channel_name })));
  const groups = new Map<string, Row[]>();
  for (const r of rows) {
    const key = r.topics?.[0] ?? r.topic ?? r.pestle_area;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const sorted = [...groups.entries()].filter(([, list]) => list.length > 1 || list.some((r) => r.first_source))
    .sort((a, b) => b[1].length - a[1].length);
  if (!sorted.length) return <div className="empty"><p>No claims grouped by subject yet.</p></div>;
  return (
    <div className="topics">
      {sorted.map(([key, list]) => (
        <section key={key} className="topic">
          <header className="topic-head">
            <h2>{topicLabel(key)}</h2>
            <span className="meta">{PESTLE[list[0].pestle_area]} · {list.length} {list.length === 1 ? "claim" : "claims"}</span>
          </header>
          <ul className="topic-list">
            {list.map((r) => (
              <li key={r.id}>
                <Link href={`/v/${r.videoId}#claim-${r.id}`}>
                  <span className="topic-claim">{r.claim_text}</span>
                  <span className="meta">{r.channel} at {clock(r.start_s)}</span>
                  {r.first_source && <span className="meta topic-src">Source: {r.first_source.title || domain(r.first_source.url)}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
