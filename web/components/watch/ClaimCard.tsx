"use client";

import { useState } from "react";
import { CheckSources } from "@/components/CheckSources";
import { ReportForm } from "@/components/ReportForm";
import { SourceList } from "@/components/SourceList";
import type { Claim } from "@/lib/types";
import { STATEMENT_TYPES, SEARCHING, canCheckSources, hasSources, typeOf } from "@/lib/statements";
import { clock, ytLink } from "@/lib/format";

export type CardPhase = "idle" | "playing" | "ended";

/** A real link to the moment on YouTube (works with open-in-new-tab); a normal click seeks the player here instead. */
export function TimeLink({ videoId, seconds, onSeek, className = "cc-ts" }: {
  videoId: string; seconds: number; onSeek(): void; className?: string;
}) {
  return (
    <a className={className} href={ytLink(videoId, seconds)} target="_blank" rel="noopener noreferrer"
       aria-label={`Go to ${clock(seconds)} in the video`}
       onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; e.preventDefault(); onSeek(); }}>
      {clock(seconds)}
    </a>
  );
}

/** Colour-coded tag for a statement's type (Claim, Opinion, Forecast, Other). */
export function TypeTag({ type }: { type: string }) {
  const t = STATEMENT_TYPES[typeOf(type)];
  return <span className="stype" style={{ ["--stype" as string]: t.cssVar }} title={`${t.meaning} Tagged by AI.`}>{t.label}</span>;
}

/**
 * One statement: its AI tag, time, the AI's plain-words version of what was said, the AI transcript on request,
 * and "Check sources" or the sources already found. Nothing here judges the statement or the speaker.
 */
export function StatementCard({ claim: c, videoId, active, phase, canWatch, canLookUp = true, hasNext, countdown,
  onSeek, onWatch, onKeepWatching, onNext, onShare }: {
  claim: Claim; videoId: string; active: boolean; phase: CardPhase; canWatch: boolean;
  canLookUp?: boolean; // false while the video is still being analysed
  hasNext: boolean; countdown: number | null;
  onSeek(): void; onWatch(): void; onKeepWatching(): void; onNext(): void; onShare(): void;
}) {
  const [showQuote, setShowQuote] = useState(false);
  const hidden = c.not_checked_reason === "outside_policy"; // text and moment stay unpublished
  const type = typeOf(c.statement_type);
  const isClaim = type === "factual_claim" && !hidden;
  const sourceable = !hidden && hasSources(type); // every type except questions and stories
  const showSources = sourceable && canLookUp && (canCheckSources(c) || SEARCHING.includes(c.sources_status));
  return (
    <article id={`card-${c.id}`} data-claim={c.id} data-type={type}
             className={`claim-card stmt-card${isClaim ? "" : " claim-card-unchecked"}${active ? " is-active" : ""}`}
             style={{ ["--stype" as string]: STATEMENT_TYPES[type].cssVar }}>
      <div className="cc-head">
        <TypeTag type={type} />
        {!hidden && <TimeLink videoId={videoId} seconds={c.start_s} onSeek={onSeek} />}
        {c.speaker && !hidden && <span className="meta" title="Speaker as identified by AI from the video">{c.speaker} <span className="ai-note">(identified by AI)</span></span>}
        {active && phase === "playing" && <span className="cc-playing">Playing</span>}
      </div>
      <p className="cc-claim">{hidden ? "A statement that isn't shown under our content policy" : c.claim_text}</p>
      {!hidden && c.statement_context && (
        <p className="cc-context" title="What was being discussed, written by AI"><span className="ai-note">Context</span> {c.statement_context}</p>
      )}

      {!hidden && c.context_quote && (
        showQuote
          ? <p className="said"><span className="ai-note">AI transcript, may contain errors. Check the video.</span><br />“{c.context_quote}”</p>
          : <button type="button" className="linkish said-toggle" onClick={() => setShowQuote(true)}>What was said</button>
      )}

      {sourceable && c.sources_status === "done" && (
        <SourceList sources={c.sources} summary={c.sources_summary} match={c.sources_match} counter={c.counter_sources}
                    counterSummary={c.counter_summary} route={c.sources_route} />
      )}
      {showSources && <CheckSources claimId={c.id} status={c.sources_status} error={c.sources_error} route={c.sources_route} />}

      {!hidden && (
        <div className="cc-actions">
          {active && phase === "ended" ? (
            <>
              <button className="btn small" onClick={onKeepWatching}>Keep watching</button>
              {hasNext && <button className="btn secondary small" onClick={onNext}>Next{countdown !== null ? ` (${countdown})` : ""}</button>}
            </>
          ) : (
            canWatch && <button className="btn secondary small" onClick={onWatch}>▶ Watch 20 s</button>
          )}
          <button className="btn secondary small" onClick={onShare}>Share</button>
          <ReportForm claimId={c.id} hasSources={c.sources.length > 0} />
        </div>
      )}
    </article>
  );
}
