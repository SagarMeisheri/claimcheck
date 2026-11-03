import type { Source } from "@/lib/types";
import { TIER_LABEL, domain, shortDate } from "@/lib/format";

export const SOURCES_NOTE =
  "Links found by a web search for this statement, in the search engine's order, with a short excerpt from each page. They are shown for context and are not a judgement of the statement or the speaker.";

/** Web search results for a claim: link, site, date and an excerpt. No verdict, no colours for right or wrong. */
export function SourceList({ sources, compact = false }: { sources: Source[]; compact?: boolean }) {
  if (!sources.length) {
    return <p className="meta source-none">The web search found no sources for this statement.</p>;
  }
  const shown = compact ? sources.slice(0, 1) : sources;
  return (
    <div className="source-list">
      {!compact && <p className="source-list-h">Sources found</p>}
      {shown.map((s) => (
        <figure key={s.url} className="source">
          <a className="source-title" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
          <p className="meta source-site">
            {[domain(s.url), TIER_LABEL[s.tier], shortDate(s.publish_date)].filter(Boolean).join(" · ")}
          </p>
          {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
        </figure>
      ))}
      {compact && sources.length > 1 && <p className="meta">+{sources.length - 1} more on the video page</p>}
      {!compact && <p className="meta source-note">{SOURCES_NOTE}</p>}
    </div>
  );
}
