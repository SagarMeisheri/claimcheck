import type { SourcesMatch } from "@/lib/types";
import { MATCH_MEANING, MATCH_NOTE, MATCH_WORD } from "@/components/SourceList";

const LEVELS: SourcesMatch[] = ["high", "medium", "low"];

/** Count of statements per source match level. */
export function matchCounts(items: { sources_match?: SourcesMatch | null }[]): Record<SourcesMatch, number> {
  const n: Record<SourcesMatch, number> = { high: 0, medium: 0, low: 0 };
  for (const c of items) if (c.sources_match) n[c.sources_match] += 1;
  return n;
}

/**
 * Filter chips by source match: Direct / Partial / Loose (how directly the sources address a statement; relevance,
 * not agreement). Shown only once at least one statement in view has a match.
 */
export function MatchFilter({ counts, value, onChange }: {
  counts: Record<SourcesMatch, number>; value: SourcesMatch | null; onChange(m: SourcesMatch | null): void;
}) {
  if (!counts.high && !counts.medium && !counts.low) return null;
  return (
    <div className="filters match-filters" role="group" aria-label="Filter by how closely the sources match" title={MATCH_NOTE}>
      {LEVELS.map((key) => (
        <button key={key} type="button" className={`chip match-chip is-${key}`} aria-pressed={value === key} title={MATCH_MEANING[key]}
                disabled={!counts[key] && value !== key} onClick={() => onChange(value === key ? null : key)}>
          {MATCH_WORD[key]} <span className="tag-n">{counts[key]}</span>
        </button>
      ))}
      {value && <button type="button" className="chip match-clear" onClick={() => onChange(null)}>Clear ×</button>}
    </div>
  );
}
