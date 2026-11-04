"use client";

import type { PreviewClaim, SourcesMatch } from "@/lib/types";
import { MATCH_NOTE } from "@/components/SourceList";

const BARS: Record<SourcesMatch, number> = { high: 3, medium: 2, low: 1 };

/** "5 + 3 figures", "5 + 2 views", "5": the related links, and what the second search found. */
export function sourcesTagText(c: Pick<PreviewClaim, "sources" | "counter_sources" | "sources_route">): string {
  if (!c.sources.length && !c.counter_sources.length) return "none found";
  const n = c.counter_sources.length;
  if (c.sources_route === "data") return `${c.sources.length} + ${n} ${n === 1 ? "figure" : "figures"}`;
  if (c.sources_route === "contested") return `${c.sources.length} + ${n} ${n === 1 ? "view" : "views"}`;
  return `${c.sources.length}`;
}

/** A small tag for a statement whose sources are in: match bars and counts. Opens the sources drawer. */
export function SourcesTag({ c, onOpen, label = false }: {
  c: Pick<PreviewClaim, "sources" | "counter_sources" | "sources_route" | "sources_match">; onOpen(): void; label?: boolean;
}) {
  return (
    <button type="button" className="tl-tag" onClick={onOpen} title={MATCH_NOTE}
            aria-label={`Sources: ${c.sources_match ?? "no"} match, ${sourcesTagText(c)}. Open`}>
      {label && <span className="tl-tag-label">Sources</span>}
      {c.sources_match && (
        <span className="src-bars" aria-hidden="true">{[1, 2, 3].map((i) => <i key={i} className={i <= BARS[c.sources_match!] ? "on" : ""} />)}</span>
      )}
      <span>{sourcesTagText(c)}</span>
      <span aria-hidden="true">›</span>
    </button>
  );
}
