"use client";

import { useCallback, useState } from "react";
import { CheckSources, type SourcesResult } from "@/components/CheckSources";
import { MatchBadge } from "@/components/SourceList";
import { SourcesTag } from "@/components/SourcesTag";
import { clock } from "@/lib/format";
import type { QaGroup } from "@/lib/qa";
import { STATEMENT_TYPES, hasSources, speakerName, typeOf } from "@/lib/statements";
import type { Claim } from "@/lib/types";
import { TypeTag } from "./ClaimCard";

/**
 * One question in the timeline, as a card: the question, who asked it, then every answer given to it with who answered,
 * the answer and what web pages found for it. It never changes size when a lookup runs: progress shows in place, and
 * the full source list opens in the detail panel. When sources are looked up automatically (`auto`) there is no button:
 * the card shows a spinner from the moment the answer appears, until its sources arrive. Nothing here judges an answer.
 */
export function QaCard({ group, auto, running, activeId, selectedId, onPlay, onSelect, onLookedUp }: {
  group: QaGroup; auto: boolean; running: boolean; activeId: string | null; selectedId: string | null;
  onPlay(c: Claim): void; onSelect(c: Claim): void; onLookedUp(c: Claim, r: SourcesResult): void;
}) {
  const first = group.answers[0];
  const type = STATEMENT_TYPES[typeOf(first.statement_type)];
  const active = group.answers.some((a) => a.id === activeId);
  const selected = group.answers.some((a) => a.id === selectedId);
  const asker = speakerName(group.askedBy);
  return (
    <li id={`card-${first.id}`} className={`qa-item${active ? " is-active" : ""}${selected ? " is-selected" : ""}`}
        style={{ ["--stype" as string]: type.cssVar }}>
      <button type="button" className="qa-time" onClick={() => onPlay(first)} aria-label={`Play from ${clock(first.start_s)}`}>{clock(first.start_s)}</button>
      <span className="qa-dot" aria-hidden="true" />
      <article className="qa-card">
        {group.q && (
          <header className="qa-head">
            <h4 className="qa-q"><button type="button" onClick={() => onSelect(first)}>{group.q}</button></h4>
            <p className="qa-asked">
              {group.implied ? "Question written by AI to fit what was said" : asker ? `Asked by ${asker}` : group.askedBy ? `Asked by ${group.askedBy}` : "Asked in the video"}
            </p>
          </header>
        )}
        {group.answers.map((a) => <Answer key={a.id} c={a} auto={auto} running={running} onPlay={onPlay} onSelect={onSelect} onLookedUp={onLookedUp} />)}
      </article>
    </li>
  );
}

function Answer({ c, auto, running, onPlay, onSelect, onLookedUp }: {
  c: Claim; auto: boolean; running: boolean; onPlay(c: Claim): void; onSelect(c: Claim): void; onLookedUp(c: Claim, r: SourcesResult): void;
}) {
  const [busy, setBusy] = useState(false);
  const onBusy = useCallback((b: boolean) => setBusy(b), []);
  const who = speakerName(c.speaker);
  const sourceable = c.sources_status !== "not_eligible" && hasSources(c.statement_type);
  const done = c.sources_status === "done";
  const skipped = c.sources_route === "skip";
  const check = (
    <CheckSources claimId={c.id} status={c.sources_status} error={null} route={c.sources_route} compact onBusy={onBusy} onDone={(r) => onLookedUp(c, r)} />
  );
  // Automatic videos: no button. Searching shows progress; an answer the lookup is about to reach shows it already.
  const autoState = ["searching", "queued", "failed"].includes(c.sources_status) ? check
    : c.sources_status === "not_requested" && !skipped && running
      ? <p className="ccard-verifying" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /> Checking sources…</p>
      : <p className="meta qa-note">{skipped ? "Not looked up: it reads as background, or the speaker on themselves." : "Sources weren't looked up for this answer."}</p>;
  return (
    <div className={`qa-ans${busy ? " is-verifying" : ""}`}>
      <p className="qa-ans-head">
        <span className="qa-who" title="Speaker as identified by AI from the video">{who ?? "Speaker"} <span className="ai-note">(identified by AI)</span></span>
        <TypeTag type={c.statement_type} />
        <button type="button" className="qa-ts" onClick={() => onPlay(c)} aria-label={`Play from ${clock(c.start_s)}`}>▶ {clock(c.start_s)}</button>
      </p>
      <p className="qa-ans-text"><button type="button" onClick={() => onSelect(c)}>{c.claim_text}</button></p>
      {sourceable && (
        <div className="qa-src">
          {done ? (
            <>
              {c.sources_summary && <p className="qa-src-text"><b>What web pages say.</b> {c.sources_summary}</p>}
              {c.counter_summary && <p className="qa-src-text"><b>Other figures and views.</b> {c.counter_summary}</p>}
              <p className="qa-src-row">
                <SourcesTag c={c} onOpen={() => onSelect(c)} label />
                {c.sources_match && <MatchBadge match={c.sources_match} />}
                <button type="button" className="linkish" onClick={() => onSelect(c)}>Details</button>
              </p>
            </>
          ) : auto ? (
            <div className="qa-check">{autoState}</div>
          ) : ["not_requested", "failed", "queued", "searching"].includes(c.sources_status) ? (
            <div className="qa-check">{check}</div>
          ) : null}
        </div>
      )}
    </div>
  );
}
