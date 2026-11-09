"use client";

import { useEffect, useState } from "react";
import { CheckSources, type SourcesResult } from "@/components/CheckSources";
import { ReportForm } from "@/components/ReportForm";
import { ResearchPanel } from "@/components/ResearchPanel";
import { SearchResults } from "@/components/SearchResults";
import { inFlight } from "@/lib/live";
import { playFromS } from "@/lib/qa";
import type { Claim } from "@/lib/types";
import { SEARCHING, canCheckSources, hasSources, typeOf } from "@/lib/statements";
import { TimeLink, TypeTag, type CardPhase } from "./ClaimCard";
import { Fold, SourceRows, TagFolds, VerdictBrief } from "./DetailBrief";

const LONG = 220; // an answer longer than this shows three lines and a "more"

/**
 * Everything about one statement on the video page, ordered so the answer to "can I trust this?" is on screen without
 * scrolling: tag, time and speaker, the question and a short answer, the verdict with its reason and chips, the pages
 * behind it as one-line rows, then folded rows (stake, how asked, searches, context and transcript) and the 20 s clip
 * controls, Share and Report. Shown docked beside the list on wide screens, in a drawer on smaller ones.
 */
export function StatementDetail({ claim: c, videoId, phase, countdown, hasNext, canLookUp, titleId,
  onSeek, onWatch, onKeepWatching, onNext, onShare, onLookedUp }: {
  claim: Claim; videoId: string; phase: CardPhase; countdown: number | null; hasNext: boolean; canLookUp: boolean; titleId: string;
  onSeek(): void; onWatch(): void; onKeepWatching(): void; onNext(): void; onShare(): void; onLookedUp(r: SourcesResult): void;
}) {
  const [fullAnswer, setFullAnswer] = useState(false);
  useEffect(() => setFullAnswer(false), [c.id]);
  const type = typeOf(c.statement_type);
  const sourceable = hasSources(type); // every type except questions and stories
  const live = inFlight(c.sources_status) && !!c.research?.stage;
  const researched = (c.research?.points?.length ?? 0) > 0 || (c.research?.searches?.length ?? 0) > 0;
  const lookup = sourceable && canLookUp && (canCheckSources(c) || SEARCHING.includes(c.sources_status));
  return (
    <div className="sdetail">
      <p className="sdetail-head">
        <TypeTag type={type} />
        <TimeLink videoId={videoId} seconds={playFromS(c)} onSeek={onSeek} />
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
          <p className={`sdetail-answer${fullAnswer || c.claim_text.length <= LONG ? "" : " is-clamped"}`}>
            <span className="ai-note">Answer</span> {c.claim_text}
            {c.claim_text.length > LONG && <> <button type="button" className="linkish" onClick={() => setFullAnswer((v) => !v)}>{fullAnswer ? "less" : "more"}</button></>}
          </p>
        </>
      ) : <h3 id={titleId} className="sdrawer-claim">{c.claim_text}</h3>}

      <VerdictBrief key={`v-${c.id}`} c={c} />
      {/* While a lookup runs (research.stage is set) the points, searches and pages found so far show as they arrive. */}
      {sourceable && live && c.research && (c.research.points?.length ?? 0) > 0 && <ResearchPanel research={c.research} />}
      {sourceable && live && c.research?.searches?.length ? <SearchResults research={c.research} sources={c.sources} /> : null}
      {sourceable && c.sources_status === "done" && <SourceRows key={`s-${c.id}`} c={c} />}
      {lookup && c.sources_status !== "done" && (
        <CheckSources claimId={c.id} status={c.sources_status} error={c.sources_error} route={c.sources_route} onDone={onLookedUp} />
      )}
      {!sourceable && <p className="meta">{type === "question" ? "A question" : "A personal story"}: there are no sources to look up.</p>}

      <div key={`f-${c.id}`} className="df-list">
        <TagFolds c={c} />
        {sourceable && c.sources_status === "done" && researched && (
          <Fold label="Searches" summary={`${c.research?.searches?.length ?? c.research?.queries?.length ?? 0} searches · ${c.research?.pages?.length ?? c.sources.length} pages`}>
            {(c.research?.points?.length ?? 0) > 0 && c.research && <ResearchPanel research={c.research} />}
            {c.research?.searches?.length ? <SearchResults research={c.research} sources={c.sources} /> : null}
          </Fold>
        )}
        {(c.statement_context || c.context_quote) && (
          <Fold label="Context" summary={c.statement_context ?? "What was said"}>
            {c.statement_context && <p className="cc-context"><span className="ai-note">Context</span> {c.statement_context}</p>}
            {c.context_quote && <p className="said"><span className="ai-note">AI transcript, may contain errors. Check the video.</span><br />“{c.context_quote}”</p>}
          </Fold>
        )}
      </div>

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
    </div>
  );
}
