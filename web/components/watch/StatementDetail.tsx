"use client";

import { useEffect, useState } from "react";
import { CheckSources, type SourcesResult } from "@/components/CheckSources";
import { IndicatorEvidence } from "@/components/Indicators";
import { ReportForm } from "@/components/ReportForm";
import { ResearchPanel } from "@/components/ResearchPanel";
import { SearchResults } from "@/components/SearchResults";
import { SourceList } from "@/components/SourceList";
import type { Claim } from "@/lib/types";
import { SEARCHING, canCheckSources, hasSources, typeOf } from "@/lib/statements";
import { TimeLink, TypeTag, type CardPhase } from "./ClaimCard";

/**
 * Everything about one statement on the video page: its tag, time and speaker, the AI's wording and context, the
 * transcript on request, the 20 s clip controls, Share and Report, and its sources (or Check sources). Shown docked
 * beside the list on wide screens, in a drawer on smaller ones. Nothing here judges the statement or the speaker.
 */
export function StatementDetail({ claim: c, videoId, phase, countdown, hasNext, canLookUp, titleId,
  onSeek, onWatch, onKeepWatching, onNext, onShare, onLookedUp }: {
  claim: Claim; videoId: string; phase: CardPhase; countdown: number | null; hasNext: boolean; canLookUp: boolean; titleId: string;
  onSeek(): void; onWatch(): void; onKeepWatching(): void; onNext(): void; onShare(): void; onLookedUp(r: SourcesResult): void;
}) {
  const [showQuote, setShowQuote] = useState(false);
  useEffect(() => setShowQuote(false), [c.id]);
  const type = typeOf(c.statement_type);
  const sourceable = hasSources(type); // every type except questions and stories
  const lookup = sourceable && canLookUp && (canCheckSources(c) || SEARCHING.includes(c.sources_status));
  return (
    <div className="sdetail">
      <p className="sdetail-head">
        <TypeTag type={type} />
        <TimeLink videoId={videoId} seconds={c.start_s} onSeek={onSeek} />
        {c.speaker && <span className="meta" title="Speaker as identified by AI from the video">{c.speaker} <span className="ai-note">(identified by AI)</span></span>}
        {phase === "playing" && <span className="cc-playing">Playing</span>}
      </p>
      {c.question ? (
        <>
          <h3 id={titleId} className="sdrawer-claim">{c.question}</h3>
          <p className="sdetail-asked">
            {c.question_kind === "implied" ? "Question written by AI to fit what was said"
              : c.asked_by ? `Asked by ${c.asked_by}` : "Question"}
          </p>
          <p className="sdetail-answer"><span className="ai-note">Answer</span> {c.claim_text}</p>
        </>
      ) : <h3 id={titleId} className="sdrawer-claim">{c.claim_text}</h3>}
      {c.statement_context && <p className="cc-context"><span className="ai-note">Context</span> {c.statement_context}</p>}
      {c.context_quote && (
        showQuote
          ? <p className="said"><span className="ai-note">AI transcript, may contain errors. Check the video.</span><br />“{c.context_quote}”</p>
          : <button type="button" className="linkish said-toggle" onClick={() => setShowQuote(true)}>What was said</button>
      )}

      <div className="cc-actions">
        {phase === "ended" ? (
          <>
            <button className="btn small" onClick={onKeepWatching}>Keep watching</button>
            {hasNext && <button className="btn secondary small" onClick={onNext}>Next{countdown !== null ? ` (${countdown})` : ""}</button>}
          </>
        ) : (
          <button className="btn secondary small" onClick={onWatch}>▶ Watch 20 s</button>
        )}
        <button className="btn secondary small" onClick={onShare}>Share</button>
        <ReportForm claimId={c.id} hasSources={c.sources.length > 0} />
      </div>

      <IndicatorEvidence c={c} />
      {sourceable && c.sources_status === "done" && c.research && (c.research.points?.length ?? 0) > 0 && <ResearchPanel research={c.research} />}
      {sourceable && c.sources_status === "done" && (c.research?.searches?.length
        ? <SearchResults research={c.research} sources={c.sources} />
        : <SourceList sources={c.sources} summary={c.sources_summary} match={c.sources_match} counter={c.counter_sources}
                      counterSummary={c.counter_summary} route={c.sources_route} />)}
      {lookup && c.sources_status !== "done" && (
        <CheckSources claimId={c.id} status={c.sources_status} error={c.sources_error} route={c.sources_route} onDone={onLookedUp} />
      )}
      {!sourceable && <p className="meta">{type === "question" ? "A question" : "A personal story"}: there are no sources to look up.</p>}
    </div>
  );
}
