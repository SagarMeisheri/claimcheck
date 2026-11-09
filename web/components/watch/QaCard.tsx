"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckSources, type SourcesResult } from "@/components/CheckSources";
import { AnswerSignals, QuestionIndicator, VerdictBadge } from "@/components/Indicators";
import { MatchBadge } from "@/components/SourceList";
import { SourcesTag } from "@/components/SourcesTag";
import { LiveLine } from "@/components/watch/LiveLine";
import { inFlight } from "@/lib/live";
import { clock } from "@/lib/format";
import { proofOf, severity, verdictOf } from "@/lib/indicators";
import { playFromS, type QaGroup } from "@/lib/qa";
import { STATEMENT_TYPES, hasSources, speakerName, typeOf } from "@/lib/statements";
import type { Claim } from "@/lib/types";

/**
 * One question in the feed, as a verdict-first card. A rail down its left side and a badge at the top carry the evidence
 * verdict (Contradicted, Grounded...), so a scan of the feed shows what needs a look. Then the question and who asked it,
 * then every answer given to it. A contradicted or ungrounded answer sets what was said beside what the sources say;
 * the others show the answer and a one-line summary of the sources. At the foot: the sources, and only the signals that
 * were found (conflict, stake, flags): nothing found, nothing shown. Clicking the question or the time plays the video;
 * the badge, the chips, the sources and Details open the detail panel. A card never changes size when a lookup runs:
 * progress shows in place. When sources are looked up automatically (`auto`) there is no button: the card shows a spinner
 * from the moment the answer appears, until its sources arrive.
 */
export function QaCard({ n, group, auto, running, streaming, activeId, selectedId, onPlay, onSelect, onLookedUp }: {
  n?: number; group: QaGroup; auto: boolean; running: boolean; streaming: boolean; activeId: string | null; selectedId: string | null;
  onPlay(c: Claim): void; onSelect(c: Claim): void; onLookedUp(c: Claim, r: SourcesResult): void
}) {
  const first = group.answers[0];
  const type = STATEMENT_TYPES[typeOf(first.statement_type)];
  const active = group.answers.some((a) => a.id === activeId);
  const selected = group.answers.some((a) => a.id === selectedId);
  const asker = speakerName(group.askedBy);
  const solo = group.answers.length === 1;
  // The card takes the colour of its worst answer.
  const worst = group.answers.reduce((w, a) => (severity(a) < severity(w) ? a : w), first);
  const verdict = verdictOf(worst);
  const qType = first.question_analysis?.type;
  return (
    <li id={`card-${first.id}`} className={`qa-item${verdict ? ` ipt-g-${verdict}` : ""}${active ? " is-active" : ""}${selected ? " is-selected" : ""}`}
        style={{ ["--stype" as string]: type.cssVar }}>
      <article className="qa-card">
        <div className="vc-top">
          <span className="vc-lead">
            {n !== undefined && <span className="qa-num" title="Question number: the buttons at the top jump to it">Q{n}</span>}
            {solo && verdict && <VerdictBadge c={first} onOpen={() => onSelect(first)} />}
          </span>
          <button type="button" className="vc-time" onClick={() => onPlay(first)} aria-label={`Play from ${clock(playFromS(first))}`}>{clock(playFromS(first))} ▶</button>
        </div>
        {group.q && (
          <header className="qa-head">
            <h4 className="qa-q"><button type="button" onClick={() => onPlay(first)} title="Play the video from here">{group.q}</button></h4>
            <div className="qa-meta">
              <p className="qa-asked">
                {group.implied ? "Question written by AI to fit what was said" : asker ? `Asked by ${asker}` : group.askedBy ? `Asked by ${group.askedBy}` : "Asked in the video"}
              </p>
              {qType && qType !== "unclear" && <QuestionIndicator analysis={first.question_analysis} onOpen={() => onSelect(first)} />}
            </div>
          </header>
        )}
        {group.answers.map((a) => <Answer key={a.id} c={a} solo={solo} auto={auto} running={running} streaming={streaming} onPlay={onPlay} onSelect={onSelect} onLookedUp={onLookedUp} />)}
      </article>
    </li>
  );
}

function Answer({ c, solo, auto, running, streaming, onPlay, onSelect, onLookedUp }: {
  c: Claim; solo: boolean; auto: boolean; running: boolean; streaming: boolean; onPlay(c: Claim): void; onSelect(c: Claim): void; onLookedUp(c: Claim, r: SourcesResult): void;
}) {
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const onBusy = useCallback((b: boolean) => setBusy(b), []);
  const who = speakerName(c.speaker);
  const type = STATEMENT_TYPES[typeOf(c.statement_type)];
  const sourceable = c.sources_status !== "not_eligible" && hasSources(c.statement_type);
  const done = c.sources_status === "done";
  const indicated = !!c.qa_tags;
  const skipped = c.sources_route === "skip";
  const verdict = verdictOf(c);
  const proof = done ? proofOf(c) : null;
  const con = verdict === "contradicted" ? c.qa_tags?.grounding?.contradiction : undefined; // what was said and how the page differs (written by AI)
  const sideBySide = !con && (verdict === "contradicted" || verdict === "ungrounded") && !!proof;
  // An answer is shown in three lines; "Show more" appears only when the text really is cut off.
  const textRef = useRef<HTMLParagraphElement>(null);
  const [cut, setCut] = useState(false);
  useEffect(() => {
    const el = textRef.current;
    if (!el || more) return;
    const measure = () => setCut(el.scrollHeight > el.clientHeight + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [more, c.claim_text, sideBySide]);
  const long = cut || more;
  // A lookup the pipeline is running for the whole video: the card shows what it has found so far, as it arrives.
  const live = streaming && inFlight(c.sources_status) && (auto || running);
  const check = (
    <CheckSources claimId={c.id} status={c.sources_status} error={null} route={c.sources_route} compact quietFail onBusy={onBusy} onDone={(r) => onLookedUp(c, r)} />
  );
  // Automatic videos: no button. Searching shows progress; an answer the lookup is about to reach shows it already.
  const autoState = ["searching", "queued", "failed"].includes(c.sources_status) ? check
    : c.sources_status === "not_requested" && !skipped && running
      ? <p className="ccard-verifying" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /> Checking sources…</p>
      : <p className="meta qa-note">{skipped ? "Not looked up: nothing in it a source could check." : "Sources weren't looked up for this answer."}</p>;
  const details = <button type="button" className="linkish vc-details" onClick={() => onSelect(c)}>Details ›</button>;
  const toggle = long && (
    <button type="button" className="linkish vc-more" onClick={() => setMore((m) => !m)} aria-expanded={more}>{more ? "Show less" : "Show more"}</button>
  );
  const said = <p ref={textRef} className={`vc-text${more ? "" : " is-clamped"}`}>{c.claim_text}</p>;
  return (
    <div className={`qa-ans${busy || live ? " is-verifying" : ""}`} style={{ ["--stype" as string]: type.cssVar }}>
      <p className="qa-ans-head">
        <span className="qa-who" title="Speaker as identified by AI from the video">{who ?? "Speaker"} <span className="ai-note">(identified by AI)</span></span>
        <span className="qa-type" title={`${type.meaning} Tagged by AI.`}><span className="stype">{type.label}</span></span>
        {!solo && <VerdictBadge c={c} onOpen={() => onSelect(c)} />}
        {!solo && <button type="button" className="qa-ts" onClick={() => onPlay(c)} aria-label={`Play from ${clock(c.start_s)}`}>▶ {clock(c.start_s)}</button>}
      </p>

      {con ? (
        <div className="vc-con">
          <div className="vc-vs">
            <div className="vc-said">
              <p className="vc-lab">Said</p>
              <p className="vc-claim">{con.said}</p>
              <button type="button" className="linkish vc-more" onClick={() => setMore((m) => !m)} aria-expanded={more}>{more ? "Hide full answer" : "Full answer"}</button>
            </div>
            <div className="vc-says">
              <p className="vc-lab">Sources say</p>
              <p className="vc-claim">{con.sources_say}</p>
              {con.quote && <blockquote className="vc-quote">“{con.quote}”</blockquote>}
              <p className="vc-cite">
                <a href={con.url} target="_blank" rel="noopener noreferrer nofollow" title={con.title}>{con.site} ↗</a>
                {(c.qa_tags?.grounding?.basis.length ?? 0) > 1 && <button type="button" className="linkish" onClick={() => onSelect(c)}>+{(c.qa_tags?.grounding?.basis.length ?? 1) - 1} more</button>}
              </p>
            </div>
          </div>
          <p className="vc-diff"><span className="vc-lab">How they differ</span> {con.difference}</p>
          {more && <p className="vc-full"><span className="vc-lab">Full answer</span> {c.claim_text}</p>}
        </div>
      ) : sideBySide ? (
        <div className="vc-vs">
          <div className="vc-said">
            <p className="vc-lab">Said</p>
            {said}
            {toggle}
          </div>
          <div className="vc-says">
            <p className="vc-lab">Sources say</p>
            <p className="vc-text">{proof!.text}</p>
            {proof!.quote && <blockquote className="vc-quote">“{proof!.quote}”</blockquote>}
            <p className="vc-cite">
              {proof!.site && (proof!.url
                ? <a href={proof!.url} target="_blank" rel="noopener noreferrer nofollow">{proof!.site} ↗</a>
                : <span>{proof!.site}</span>)}
              {proof!.more > 0 && <button type="button" className="linkish" onClick={() => onSelect(c)}>+{proof!.more} more</button>}
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="vc-answer">
            {said}
            {toggle}
          </div>
          {sourceable && done && indicated && proof && <p className="vc-line"><b>Sources say</b> {proof.text}</p>}
          {sourceable && done && !indicated && (
            <>
              {c.sources_summary && <p className="vc-line"><b>What web pages say.</b> {c.sources_summary}</p>}
              {c.counter_summary && <p className="vc-line"><b>Other figures and views.</b> {c.counter_summary}</p>}
            </>
          )}
        </>
      )}

      {sourceable && skipped && indicated && c.sources_status !== "searching" && (
        <div className="vc-foot"><AnswerSignals c={c} onOpen={() => onSelect(c)} />{details}</div>  // tagged, no search needed (an opinion, or nothing checkable)
      )}
      {sourceable && !(skipped && indicated && c.sources_status !== "searching") && (
        done ? (
          <div className="vc-foot">
            <SourcesTag c={c} onOpen={() => onSelect(c)} label />
            {c.sources_match && <MatchBadge match={c.sources_match} />}
            <AnswerSignals c={c} onOpen={() => onSelect(c)} />
            {details}
          </div>
        ) : live ? (
          <div className="qa-check"><LiveLine c={c} /></div>
        ) : auto ? (
          <div className="qa-check">{autoState}</div>
        ) : ["not_requested", "failed", "queued", "searching"].includes(c.sources_status) ? (
          <div className="qa-check">{check}</div>
        ) : null
      )}
    </div>
  );
}
