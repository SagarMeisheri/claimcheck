"use client";

import { useRef, useState } from "react";
import type { Claim } from "@/lib/types";
import { STATEMENT_TYPES, typeOf } from "@/lib/statements";
import { VERDICTS, clock } from "@/lib/verdicts";

function tickClass(c: Claim): string {
  if (c.verdict) return `tick tick-${c.verdict.verdict}`;
  if (c.awaiting_review) return "tick tick-pending";
  if (c.not_checked_reason === "outside_policy") return "tick tick-skipped";
  return "tick tick-stmt"; // unverified statement: short tick in its type colour
}

function statusLabel(c: Claim): string {
  if (c.verdict) return VERDICTS[c.verdict.verdict].label;
  if (c.awaiting_review) return "with a reviewer";
  return STATEMENT_TYPES[typeOf(c.statement_type)].label.toLowerCase();
}

export function tickLabel(c: Claim): string {
  return `${clock(c.start_s)}, ${statusLabel(c)}: ${c.claim_text}`;
}

/**
 * Our timeline under the player: one tick per claim at its timestamp, a playhead that follows the
 * video, tap a tick to seek, drag along the track to scrub from claim to claim.
 */
export function ClaimTrack({ claims, duration, time, currentId, onSeekClaim }: {
  claims: Claim[]; duration: number; time: number; currentId: string | null; onSeekClaim(c: Claim): void;
}) {
  const total = Math.max(duration, ...claims.map((c) => c.start_s + 20), 60);
  const ref = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<{ claim: Claim; x: number } | null>(null);
  const seekable = claims.filter((c) => c.not_checked_reason !== "outside_policy"); // redacted claims stay unlinked

  const nearest = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    const t = ((clientX - r.left) / r.width) * total;
    let best = seekable[0];
    for (const c of seekable) if (Math.abs(c.start_s - t) < Math.abs(best.start_s - t)) best = c;
    return { claim: best, x: Math.min(Math.max(clientX - r.left, 0), r.width) };
  };

  return (
    <div className="track-wrap">
      <div
        ref={ref}
        className="track"
        onPointerDown={(e) => {
          if (!seekable.length || (e.target as HTMLElement).closest("button")) return;
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          setPreview(nearest(e.clientX));
        }}
        onPointerMove={(e) => preview && setPreview(nearest(e.clientX))}
        onPointerUp={() => {
          if (preview) onSeekClaim(preview.claim);
          setPreview(null);
        }}
        onPointerCancel={() => setPreview(null)}
      >
        {claims.map((c) => (
          <button
            key={c.id}
            className={`${tickClass(c)}${c.id === currentId ? " tick-current" : ""}`}
            style={{ left: `${(c.start_s / total) * 100}%`, ["--tick" as string]: c.verdict ? VERDICTS[c.verdict.verdict].cssVar : STATEMENT_TYPES[typeOf(c.statement_type)].cssVar }}
            aria-label={tickLabel(c)}
            title={tickLabel(c)}
            disabled={c.not_checked_reason === "outside_policy"}
            onClick={() => onSeekClaim(c)}
          />
        ))}
        <span className="playhead" style={{ left: `${Math.min(100, (time / total) * 100)}%` }} aria-hidden="true" />
        {preview && (
          <span className="track-preview" style={{ left: preview.x }}>
            {clock(preview.claim.start_s)}{" "}
            {statusLabel(preview.claim)}
            <span className="track-preview-text">{preview.claim.claim_text}</span>
          </span>
        )}
      </div>
      <div className="track-scale" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => <span key={i}>{clock(Math.round((total * i) / 4))}</span>)}
      </div>
    </div>
  );
}
