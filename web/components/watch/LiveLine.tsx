import { liveLine } from "@/lib/live";
import type { Claim } from "@/lib/types";

/**
 * What a card shows while its sources are being looked up: one line, the step and what that step has found so far (the tags, the points
 * being chosen, the searches, the sites being read, the verdict). One line of fixed height, so the card never changes size as it fills in.
 * Screen readers hear the step when it changes, not every piece of text.
 */
export function LiveLine({ c }: { c: Claim }) {
  const l = liveLine(c);
  return (
    <div className="live-line" data-stage={l.stage}>
      <span className="sr-only" role="status" aria-live="polite" key={l.stage}>{l.label}</span>
      <span className="spinner" aria-hidden="true" />
      <span className="live-label" aria-hidden="true">{l.label}</span>
      {l.detail && <span className="live-detail" aria-hidden="true" key={l.detail} title={l.detail}>{l.detail}</span>}
    </div>
  );
}
