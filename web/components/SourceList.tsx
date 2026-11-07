import type { Source, SourcesMatch, SourcesRoute } from "@/lib/types";
import { domain, shortDate } from "@/lib/format";

export const SOURCES_NOTE =
  "Links found by a web search for this statement, in the search engine's order. Statements with figures or on disputed subjects also get a second search for official data, other figures or other viewpoints. The summaries are written by AI from the excerpts shown here and only describe what they say. None of this is a judgement of the statement or the speaker.";


/**
 * What a web search found for a claim: "Sources summary" (an AI summary of the excerpts), then the source links.
 * compact (home page): the summary and numbered site links. Full (video page): the summary and every source with
 * its excerpt. No verdict and no colours for right or wrong.
 */
/** How closely the sources match a statement, in words (no bars, no colours for right or wrong). */
export const MATCH_WORD: Record<SourcesMatch, string> = { high: "Direct", medium: "Partial", low: "Loose" };
export const MATCH_MEANING: Record<SourcesMatch, string> = {
  high: "The sources address this exact point.",
  medium: "The sources cover the topic, not this exact point.",
  low: "The sources are only loosely related.",
};
export const MATCH_NOTE =
  "Source match: how directly the excerpts address this claim's specific point, rated by AI. It is not whether they agree: a source giving a different figure for the same thing is a direct match.";

/** "Direct match", "Partial match", "Loose match". */
export function MatchBadge({ match }: { match: SourcesMatch }) {
  return (
    <span className={`src-match is-${match}`} title={`${MATCH_MEANING[match]} ${MATCH_NOTE}`}>
      {MATCH_WORD[match]} match
    </span>
  );
}

/** The second search's group: what it looked for, in neutral words. */
const COUNTER_LABEL: Record<"data" | "contested", { title: string; note: string; none: string }> = {
  data: { title: "Different figures", note: "A second search for official data and other figures for the same thing.",
          none: "A second search for official data and other figures found nothing new." },
  contested: { title: "Other perspectives", note: "A second search for analyses and reporting from other viewpoints.",
               none: "A second search for other viewpoints found nothing new." },
};

const plain = (t?: string | null) => (t ?? "").replace(/\s*\[\d+\]/g, "").replace(/\s+([.,;:])/g, "$1").trim();

/** The second group of sources (data / contested statements). Same neutral style as the first: no verdict. */
function CounterGroup({ route, sources, summary, compact }: { route: "data" | "contested"; sources: Source[]; summary?: string | null; compact: boolean }) {
  const label = COUNTER_LABEL[route];
  if (!sources.length) return <p className="meta src-counter-none">{label.none}</p>;
  const text = plain(summary);
  return (
    <div className="src-counter" aria-label={label.title}>
      <div className="src-head"><span className="src-label" title={label.note}>{label.title}</span></div>
      {text && <p className="src-summary">{text}</p>}
      {compact ? (
        <ol className="src-nums" aria-label={label.title}>
          {sources.map((s, i) => (
            <li key={s.url}>
              <a href={s.url} target="_blank" rel="noopener noreferrer" title={s.title || domain(s.url)}>
                <span className="src-n">{i + 1}</span><span className="src-site">{domain(s.url)}</span>
              </a>
            </li>
          ))}
        </ol>
      ) : (
        <ol className="src-items">
          {sources.map((s) => (
            <li key={s.url}>
              <a className="source-title" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
              <p className="meta source-site">{[domain(s.url), shortDate(s.publish_date)].filter(Boolean).join(" · ")}</p>
              {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function SourceList({ sources, summary, match, counter = [], counterSummary, route, compact = false }: {
  sources: Source[]; summary?: string | null; match?: SourcesMatch | null; counter?: Source[]; counterSummary?: string | null;
  route?: SourcesRoute | null; compact?: boolean;
}) {
  const second = route === "data" || route === "contested"
    ? <CounterGroup route={route} sources={counter} summary={counterSummary} compact={compact} /> : null;
  if (!sources.length) {
    return (
      <>
        <p className="meta source-none">The web search found no sources for this statement.</p>
        {second}
      </>
    );
  }
  const clean = plain(summary);
  const head = (
    <div className="src-head">
      <span className="src-label">{clean ? "Sources summary" : "Sources"}</span>
      {match && <MatchBadge match={match} />}
    </div>
  );
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
        {second}
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
              {[domain(s.url), shortDate(s.publish_date)].filter(Boolean).join(" · ")}
            </p>
            {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
          </li>
        ))}
      </ol>
      {second}
      <p className="meta source-note">{SOURCES_NOTE}</p>
    </section>
  );
}
