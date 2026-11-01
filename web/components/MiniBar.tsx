import type { VerdictName } from "@/lib/types";
import { VERDICTS, VERDICT_ORDER, tallyTotal } from "@/lib/verdicts";

/** Verdict strip: share of each verdict, same order everywhere. */
export function VerdictStrip({ tally, checking = false }: { tally: Partial<Record<VerdictName, number>>; checking?: boolean }) {
  const total = tallyTotal(tally);
  if (checking) return <div className="vstrip vstrip-checking" aria-label="Checking claims" />;
  if (!total) return <div className="vstrip vstrip-empty" aria-hidden="true" />;
  const label = VERDICT_ORDER.filter((v) => tally[v]).map((v) => `${tally[v]} ${VERDICTS[v].label}`).join(", ");
  return (
    <div className="vstrip" role="img" aria-label={label}>
      {VERDICT_ORDER.filter((v) => tally[v]).map((v) => (
        <span key={v} style={{ flex: tally[v], background: VERDICTS[v].cssVar }} />
      ))}
    </div>
  );
}

export const MiniBar = VerdictStrip;

export function TallySentence({ tally }: { tally: Partial<Record<VerdictName, number>> }) {
  const parts = VERDICT_ORDER.filter((v) => tally[v]);
  if (!parts.length) return null;
  return (
    <p className="tally">
      {tallyTotal(tally)} claims checked:{" "}
      {parts.map((v, i) => (
        <span key={v}>
          {i > 0 && <span className="tally-sep">, </span>}
          <span className="vword" style={{ color: VERDICTS[v].cssVar }}>{tally[v]} {VERDICTS[v].label.toLowerCase()}</span>
        </span>
      ))}
    </p>
  );
}
