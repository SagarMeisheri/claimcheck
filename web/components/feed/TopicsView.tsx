import Link from "next/link";
import { VerdictStrip } from "@/components/MiniBar";
import type { Episode, PreviewClaim, VerdictName } from "@/lib/types";
import { PESTLE, VERDICTS, clock, topicLabel } from "@/lib/verdicts";

type Row = PreviewClaim & { verdict: VerdictName; videoId: string; videoTitle: string; channel: string };

/** Claims from every video, grouped by topic. Each claim keeps its video and speaker attached. */
export function TopicsView({ episodes }: { episodes: Episode[] }) {
  const rows: Row[] = episodes.flatMap((e) => (e.published_claims ?? []).flatMap((c) => c.verdict ? [{
    ...c, verdict: c.verdict, videoId: e.youtube_video_id, videoTitle: e.title, channel: e.channel_name,
  }] : []));
  const groups = new Map<string, Row[]>();
  for (const r of rows) {
    const key = r.topic ?? r.pestle_area;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  if (!sorted.length) return <div className="empty"><p>No checked claims yet.</p></div>;
  return (
    <div className="topics">
      {sorted.map(([key, list]) => {
        const tally: Partial<Record<VerdictName, number>> = {};
        for (const r of list) tally[r.verdict] = (tally[r.verdict] ?? 0) + 1;
        return (
          <section key={key} className="topic">
            <header className="topic-head">
              <h2>{topicLabel(key)}</h2>
              <span className="meta">{PESTLE[list[0].pestle_area]} · {list.length} {list.length === 1 ? "claim" : "claims"}</span>
            </header>
            <VerdictStrip tally={tally} />
            <ul className="topic-list">
              {list.map((r) => (
                <li key={r.id}>
                  <Link href={`/v/${r.videoId}#claim-${r.id}`}>
                    <span className="vword" style={{ color: VERDICTS[r.verdict].cssVar }}>{VERDICTS[r.verdict].label}</span>
                    <span className="topic-claim">{r.claim_text}</span>
                    <span className="meta">{r.speaker ? `${r.speaker}, ` : ""}{r.channel} at {clock(r.start_s)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
