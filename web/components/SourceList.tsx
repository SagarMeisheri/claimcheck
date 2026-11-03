import type { ReactNode } from "react";
import type { Source } from "@/lib/types";
import { TIER_LABEL, domain, shortDate } from "@/lib/format";

export const SOURCES_NOTE =
  "Links found by a web search for this statement, in the search engine's order. The summary is written by AI from the pages' text and only describes what they say. Neither is a judgement of the statement or the speaker: open the links and decide for yourself.";

/** "[1][3]" in the AI summary become small numbered links to those sources. */
function withCitations(text: string, sources: Source[]): ReactNode[] {
  return text.split(/(\[\d+\])/).map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    const s = m ? sources[Number(m[1]) - 1] : undefined;
    if (!m) return part;
    if (!s) return null;
    return (
      <a key={i} className="cite" href={s.url} target="_blank" rel="noopener noreferrer" title={s.title || domain(s.url)}>{m[1]}</a>
    );
  });
}

function SourcesTag({ n }: { n: number }) {
  return <span className="src-tag">✓ {n} {n === 1 ? "source" : "sources"}</span>;
}

/**
 * Web search results for a claim, with an AI summary of what they say. No verdict and no colours for right or wrong.
 * compact (home page): tag, numbered links, summary. Full (video page): tag, summary, numbered list with excerpts.
 */
export function SourceList({ sources, summary, compact = false }: { sources: Source[]; summary?: string | null; compact?: boolean }) {
  if (!sources.length) {
    return <p className="meta source-none">The web search found no sources for this statement.</p>;
  }
  const said = summary ? (
    <p className="src-summary">
      {!compact && <span className="ai-note">What the sources say (AI summary): </span>}
      {withCitations(summary, sources)}
    </p>
  ) : null;

  if (compact) {
    return (
      <div className="source-list is-compact">
        <div className="src-row">
          <SourcesTag n={sources.length} />
          <ol className="src-nums" aria-label="Sources">
            {sources.map((s, i) => (
              <li key={s.url}>
                <a className="cite" href={s.url} target="_blank" rel="noopener noreferrer"
                   title={`${domain(s.url)}: ${s.title || ""}`} aria-label={`Source ${i + 1}: ${domain(s.url)}`}>{i + 1}</a>
              </li>
            ))}
          </ol>
        </div>
        {said}
      </div>
    );
  }

  return (
    <div className="source-list">
      <SourcesTag n={sources.length} />
      {said}
      <ol className="src-items">
        {sources.map((s, i) => (
          <li key={s.url}>
            <span className="src-n">{i + 1}</span>
            <div className="src-body">
              <a className="source-title" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
              <p className="meta source-site">
                {[domain(s.url), TIER_LABEL[s.tier], shortDate(s.publish_date)].filter(Boolean).join(" · ")}
              </p>
              {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
            </div>
          </li>
        ))}
      </ol>
      <p className="meta source-note">{SOURCES_NOTE}</p>
    </div>
  );
}
