"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { PreviewClaim, Source } from "@/lib/types";
import { Drawer, PaneNav } from "@/components/Drawer";
import { SourceList } from "@/components/SourceList";
import { STATEMENT_TYPES, typeOf } from "@/lib/statements";
import { clock } from "@/lib/format";

type Full = { sources: Source[]; counter: Source[] };

/** The full sources (with excerpts) of one statement, fetched once; the home page keeps them without excerpts. */
export function useFullSources(claimId: string): Full | null {
  const [full, setFull] = useState<Record<string, Full>>({});
  useEffect(() => {
    if (full[claimId]) return;
    let stop = false;
    fetch(`/api/claims/${claimId}/sources`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (!stop && j?.status === "done") setFull((f) => ({ ...f, [claimId]: { sources: j.sources ?? [], counter: j.counter ?? [] } }));
    }).catch(() => {});
    return () => { stop = true; };
  }, [claimId, full]);
  return full[claimId] ?? null;
}

/** A statement's sources in a drawer (home page). Previous / Next step through the statements that have sources. */
export function SourcesDrawer({ videoId, claim, hasPrev, hasNext, onPrev, onNext, onClose, onPlay }: {
  videoId: string; claim: PreviewClaim; hasPrev: boolean; hasNext: boolean;
  onPrev(): void; onNext(): void; onClose(): void; onPlay(c: PreviewClaim): void;
}) {
  const got = useFullSources(claim.id);
  const t = STATEMENT_TYPES[typeOf(claim.statement_type)];
  return (
    <Drawer onClose={onClose} labelledBy="sdrawer-title" accent={t.cssVar} onPrev={hasPrev ? onPrev : undefined} onNext={hasNext ? onNext : undefined}
            nav={<PaneNav hasPrev={hasPrev} hasNext={hasNext} onPrev={onPrev} onNext={onNext} what="statement with sources" />}>
      <p className="sdrawer-head">
        <button type="button" className="linkish cc-ts" onClick={() => onPlay(claim)}>▶ {clock(claim.start_s)}</button>
        <span className="stype-tag"><span className="bd-dot" style={{ background: t.cssVar }} aria-hidden="true" />{t.label}</span>
      </p>
      <h3 id="sdrawer-title" className="sdrawer-claim">{claim.claim_text}</h3>
      {claim.statement_context && <p className="cc-context"><span className="ai-note">Context</span> {claim.statement_context}</p>}
      <SourceList sources={got?.sources ?? claim.sources} summary={claim.sources_summary} match={claim.sources_match}
                  counter={got?.counter ?? claim.counter_sources} counterSummary={claim.counter_summary} route={claim.sources_route} />
      <p><Link href={`/v/${videoId}#claim-${claim.id}`} className="srow-open">Open in the video page</Link></p>
    </Drawer>
  );
}
