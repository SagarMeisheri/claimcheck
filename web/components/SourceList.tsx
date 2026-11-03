import type { Source } from "@/lib/types";
import { TIER_LABEL, domain, shortDate } from "@/lib/format";

export const SOURCES_NOTE =
  "Sentences are copied from the linked pages and checked word for word. They are shown for context and are not a judgement of the statement or the speaker.";

/** What published sources say about a claim's subject: exact sentences with links. No verdict, no colours for right or wrong. */
export function SourceList({ sources, compact = false }: { sources: Source[]; compact?: boolean }) {
  if (!sources.length) {
    return <p className="meta source-none">No relevant source found from official or established news sources.</p>;
  }
  const shown = compact ? sources.slice(0, 1) : sources;
  return (
    <div className="source-list">
      {!compact && <p className="source-list-h">What sources say</p>}
      {shown.map((s) => (
        <figure key={s.url} className="source">
          <blockquote>“{s.quote}”</blockquote>
          <figcaption>
            <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
            <span className="meta"> {domain(s.url)}. {TIER_LABEL[s.tier] ?? ""}{shortDate(s.publish_date) ? `. ${shortDate(s.publish_date)}` : ""}</span>
          </figcaption>
        </figure>
      ))}
      {compact && sources.length > 1 && <p className="meta">+{sources.length - 1} more on the video page</p>}
      {!compact && <p className="meta source-note">{SOURCES_NOTE}</p>}
    </div>
  );
}
