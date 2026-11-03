import type { SourcesMatch } from "@/lib/types";
import { MATCH_NOTE } from "@/components/SourceList";

const LEVELS: { key: SourcesMatch; label: string; bars: number }[] = [
  { key: "high", label: "High match", bars: 3 },
  { key: "medium", label: "Medium match", bars: 2 },
  { key: "low", label: "Low match", bars: 1 },
];

/** Count of statements per source match level. */
export function matchCounts(items: { sources_match?: SourcesMatch | null }[]): Record<SourcesMatch, number> {
  const n: Record<SourcesMatch, number> = { high: 0, medium: 0, low: 0 };
  for (const c of items) if (c.sources_match) n[c.sources_match] += 1;
  return n;
}

/**
 * Filter chips by source match (how directly the sources address a statement; relevance, not agreement).
 * Shown only once at least one statement in view has a match.
 */
export function MatchFilter({ counts, value, onChange }: {
  counts: Record<SourcesMatch, number>; value: SourcesMatch | null; onChange(m: SourcesMatch | null): void;
}) {
  if (!counts.high && !counts.medium && !counts.low) return null;
  return (
    <div className="filters match-filters" role="group" aria-label="Filter by source match" title={MATCH_NOTE}>
      {LEVELS.map(({ key, label, bars }) => (
        <button key={key} type="button" className="chip match-chip" aria-pressed={value === key}
                disabled={!counts[key] && value !== key} onClick={() => onChange(value === key ? null : key)}>
          <span className="src-bars" aria-hidden="true">{[1, 2, 3].map((i) => <i key={i} className={i <= bars ? "on" : ""} />)}</span>
          {label} <span className="tag-n">{counts[key]}</span>
        </button>
      ))}
      {value && <button type="button" className="chip match-clear" onClick={() => onChange(null)}>Clear ×</button>}
    </div>
  );
}
