import type { Source } from "@/lib/types";
import { TIER_LABEL, domain, shortDate } from "@/lib/format";

export const SOURCES_NOTE =
  "Links found by a web search for this statement, in the search engine's order. The sources summary is written by AI from the excerpts shown here and only describes what they say. Neither is a judgement of the statement or the speaker.";


/**
 * What a web search found for a claim: "Sources summary" (an AI summary of the excerpts), then the source links.
 * compact (home page): the summary and numbered site links. Full (video page): the summary and every source with
 * its excerpt. No verdict and no colours for right or wrong.
 */
export function SourceList({ sources, summary, compact = false }: { sources: Source[]; summary?: string | null; compact?: boolean }) {
  if (!sources.length) {
    return <p className="meta source-none">The web search found no sources for this statement.</p>;
  }
  const clean = (summary ?? "").replace(/\s*\[\d+\]/g, "").replace(/\s+([.,;:])/g, "$1").trim(); // plain text
  const head = <p className="src-label">{clean ? "Sources summary" : "Sources"}</p>;
  const text = clean ? <p className="src-summary">{clean}</p> : null;

  if (compact) {
    return (
      <div className="source-list is-compact">
        {head}
        {text}
        <ol className="src-nums" aria-label="Sources">
          {sources.map((s, i) => (
            <li key={s.url}>
              <a href={s.url} target="_blank" rel="noopener noreferrer" title={s.title || domain(s.url)}>
                <span className="src-n">{i + 1}</span><span className="src-site">{domain(s.url)}</span>
              </a>
            </li>
          ))}
        </ol>
      </div>
    );
  }

  return (
    <section className="source-list" aria-label="Sources summary">
      {head}
      {text}
      <ol className="src-items">
        {sources.map((s) => (
          <li key={s.url}>
            <a className="source-title" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
            <p className="meta source-site">
              {[domain(s.url), TIER_LABEL[s.tier], shortDate(s.publish_date)].filter(Boolean).join(" · ")}
            </p>
            {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
          </li>
        ))}
      </ol>
      <p className="meta source-note">{SOURCES_NOTE}</p>
    </section>
  );
}
