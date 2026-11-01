"use client";

import Link from "next/link";
import { useState } from "react";
import type { ClaimTab, PreviewClaim } from "@/lib/types";
import { NOT_CHECKED, VERDICTS, clock } from "@/lib/verdicts";

const TABS: { key: ClaimTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "flagged", label: "Flagged" },
  { key: "checked", label: "Checked" },
  { key: "unchecked", label: "Not checked" },
];

function Card({ videoId, c, videoPending, active, onPlay }: {
  videoId: string; c: PreviewClaim; videoPending: boolean; active: boolean; onPlay(c: PreviewClaim): void;
}) {
  if (c.not_checked_reason === "outside_policy") { // text and moment stay unpublished
    return (
      <article className="ccard ccard-unchecked" role="listitem">
        <span className="ccard-main">
          <span className="ccard-head"><span className="pending-word">Not checked: {NOT_CHECKED.outside_policy}</span></span>
          <span className="ccard-text">A claim outside our content policy</span>
        </span>
      </article>
    );
  }
  const v = c.verdict ? VERDICTS[c.verdict] : null;
  return (
    <article className={`ccard${v ? "" : " ccard-unchecked"}${active ? " is-active" : ""}`} role="listitem">
      {/* Clicking the claim plays the video from its timestamp, right here on the home page. */}
      <button type="button" className="ccard-main ccard-playbtn" disabled={videoPending} onClick={() => onPlay(c)}
              aria-label={`Play the video from ${clock(c.start_s)}: ${c.claim_text}`}>
        <span className="ccard-head">
          <span className="ts">▶ {clock(c.start_s)}</span>
          {v
            ? <span className="vword" style={{ color: v.cssVar }}>{v.label}</span>
            : <span className="pending-word">{c.awaiting_review ? "With a reviewer" : `Not checked: ${NOT_CHECKED[c.not_checked_reason ?? ""] ?? c.not_checked_reason}`}</span>}
          {active && <span className="cc-playing">Playing</span>}
        </span>
        <span className="ccard-text">{c.claim_text}</span>
        {v && c.source_line && <span className="ccard-src" style={{ borderColor: v.cssVar }}>{c.source_line}</span>}
      </button>
      <Link href={`/v/${videoId}#claim-${c.id}`} className="ccard-play">Sources and details</Link>
    </article>
  );
}

/** Swipeable row of claim cards under a video, with tabs: Flagged, Checked, Not checked, All. */
export function ClaimCarousel({ videoId, tabs, counts, videoPending = false, activeId = null, onPlay }: {
  videoId: string; tabs: Record<ClaimTab, PreviewClaim[]>; counts: Record<ClaimTab, number>; videoPending?: boolean;
  activeId?: string | null; onPlay(c: PreviewClaim): void;
}) {
  const [tab, setTab] = useState<ClaimTab>("all");
  if (!counts.all) return null;
  const claims = tabs[tab] ?? [];
  return (
    <>
      <div className="seg seg-card" role="tablist" aria-label="Claims in this video">
        {TABS.map(({ key, label }) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{label} {counts[key]}</button>
        ))}
      </div>
      <div className="carousel" role="list" aria-label={`${TABS.find((t) => t.key === tab)?.label} claims`}>
        {claims.length === 0 && <p className="meta carousel-empty">{tab === "flagged" ? "Nothing flagged." : "None."}</p>}
        {claims.map((c) => <Card key={c.id} videoId={videoId} c={c} videoPending={videoPending} active={activeId === c.id} onPlay={onPlay} />)}
        {counts[tab] > 0 && (
          <Link href={`/v/${videoId}?view=${tab}`} className="ccard ccard-more" role="listitem">
            <span>See {counts[tab] > claims.length ? `all ${counts[tab]}` : "them"} on the video page</span>
          </Link>
        )}
      </div>
    </>
  );
}
