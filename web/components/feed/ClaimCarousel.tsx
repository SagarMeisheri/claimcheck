"use client";

import Link from "next/link";
import type { PreviewClaim, StatementType } from "@/lib/types";
import { STATEMENT_TYPES, TYPE_ORDER, totalStatements } from "@/lib/statements";
import { VERDICTS, clock } from "@/lib/verdicts";

function Card({ videoId, c, videoPending, active, onPlay }: {
  videoId: string; c: PreviewClaim; videoPending: boolean; active: boolean; onPlay(c: PreviewClaim): void;
}) {
  const v = c.verdict ? VERDICTS[c.verdict] : null;
  if (!v) return null; // the carousel shows verified claims only
  return (
    <article className={`ccard${active ? " is-active" : ""}`} role="listitem">
      {/* Clicking the claim plays the video from its timestamp, right here on the home page. */}
      <button type="button" className="ccard-main ccard-playbtn" disabled={videoPending} onClick={() => onPlay(c)}
              aria-label={`Play the video from ${clock(c.start_s)}: ${c.claim_text}`}>
        <span className="ccard-head">
          <span className="ts">▶ {clock(c.start_s)}</span>
          <span className="vword" style={{ color: v.cssVar }}>{v.label}</span>
          {active && <span className="cc-playing">Playing</span>}
        </span>
        <span className="ccard-text">{c.claim_text}</span>
        {c.source_line && <span className="ccard-src" style={{ borderColor: v.cssVar }}>{c.source_line}</span>}
      </button>
      <Link href={`/v/${videoId}#claim-${c.id}`} className="ccard-play">Sources and details</Link>
    </article>
  );
}

/** First card of every video's row: what the video is made of, by statement type, and how much is verified. */
export function BreakdownCard({ videoId, counts, verified, reviewing }: {
  videoId: string; counts: Partial<Record<StatementType, number>>; verified: number; reviewing: number;
}) {
  const total = totalStatements(counts);
  const types = TYPE_ORDER.filter((t) => counts[t]);
  return (
    <Link href={`/v/${videoId}`} className="ccard ccard-breakdown" role="listitem"
          aria-label={`${total} statements in this video, ${verified} verified. Open the video page.`}>
      <span className="ccard-main">
        <span className="ccard-head"><strong>{total} statements</strong></span>
        <span className="type-bar" aria-hidden="true">
          {types.map((t) => <span key={t} style={{ flexGrow: counts[t], background: STATEMENT_TYPES[t].cssVar }} />)}
        </span>
        <span className="bd-list">
          {types.map((t) => (
            <span key={t} className="bd-row">
              <span className="bd-dot" style={{ background: STATEMENT_TYPES[t].cssVar }} aria-hidden="true" />
              {STATEMENT_TYPES[t].label} <span className="meta">{counts[t]}</span>
            </span>
          ))}
        </span>
        <span className="bd-verified">
          {verified} verified{reviewing ? `, ${reviewing} with a reviewer` : ""}
        </span>
      </span>
      <span className="ccard-play">See all and verify more</span>
    </Link>
  );
}

/** Swipeable row under a video: the breakdown card, then its verified claims (supported first, then flagged). */
export function ClaimCarousel({ videoId, claims, verifiedCount, counts, reviewing, videoPending = false, activeId = null, onPlay }: {
  videoId: string; claims: PreviewClaim[]; verifiedCount: number; counts: Partial<Record<StatementType, number>>; reviewing: number;
  videoPending?: boolean; activeId?: string | null; onPlay(c: PreviewClaim): void;
}) {
  const verified = claims.filter((c) => c.verdict);
  if (!totalStatements(counts) && !verified.length) return null;
  return (
    <div className="carousel" role="list" aria-label="Verified claims in this video">
      <BreakdownCard videoId={videoId} counts={counts} verified={Math.max(verifiedCount, verified.length)} reviewing={reviewing} />
      {verified.map((c) => <Card key={c.id} videoId={videoId} c={c} videoPending={videoPending} active={activeId === c.id} onPlay={onPlay} />)}
    </div>
  );
}
