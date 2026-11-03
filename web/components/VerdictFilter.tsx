"use client";

import type { VerdictName } from "@/lib/types";
import { VERDICTS, VERDICT_ORDER } from "@/lib/verdicts";

/** Filter chips by verification result (True, False, Misleading, ...), with counts. Like the topic tags, but for verdicts. */
export function VerdictFilter({ counts, active, onPick }: {
  counts: Partial<Record<VerdictName, number>>; active: VerdictName | null; onPick(v: VerdictName | null): void;
}) {
  const present = VERDICT_ORDER.filter((v) => counts[v]);
  if (!present.length) return null;
  return (
    <div className="vfilter" role="group" aria-label="Filter by verification result">
      {present.map((v) => (
        <button key={v} type="button" className="vchip" aria-pressed={active === v}
                style={{ ["--vc" as string]: VERDICTS[v].cssVar }} title={VERDICTS[v].meaning}
                onClick={() => onPick(active === v ? null : v)}>
          <span className="vchip-dot" aria-hidden="true" />
          {VERDICTS[v].label} <span className="tag-n">{counts[v]}</span>
        </button>
      ))}
      {active && <button type="button" className="vchip vchip-clear" onClick={() => onPick(null)}>Clear ×</button>}
    </div>
  );
}
