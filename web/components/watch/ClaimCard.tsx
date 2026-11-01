"use client";

import Link from "next/link";
import { FeedbackForm } from "@/components/FeedbackForm";
import type { Citation, Claim } from "@/lib/types";
import { NOT_CHECKED, TIER_LABEL, VERDICTS, clock, domain, ytLink } from "@/lib/verdicts";

export type CardPhase = "idle" | "playing" | "ended";

const PLAIN_TIER: Record<number, string> = {
  1: "Official statistics, regulator, court or peer-reviewed research",
  2: TIER_LABEL[2],
  3: TIER_LABEL[3],
};

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

/** A claim we found but did not rate (opinion, prediction, lower priority...), with the reason and its moment. */
export function UncheckedCard({ claim: c, videoId, active, phase, canWatch, onSeek, onWatch, onKeepWatching }: {
  claim: Claim; videoId: string; active: boolean; phase: CardPhase; canWatch: boolean;
  onSeek(): void; onWatch(): void; onKeepWatching(): void;
}) {
  const hidden = c.not_checked_reason === "outside_policy"; // text and moment stay unpublished
  return (
    <article id={`card-${c.id}`} data-claim={c.id} className={`claim-card claim-card-unchecked${active ? " is-active" : ""}`}>
      <div className="cc-head">
        {!hidden && <TimeLink videoId={videoId} seconds={c.start_s} onSeek={onSeek} />}
        {c.speaker && !hidden && <span className="meta">{c.speaker}</span>}
        {active && phase === "playing" && <span className="cc-playing">Playing</span>}
      </div>
      <p className="cc-verdict">
        <span className="pending-word">Not checked: {NOT_CHECKED[c.not_checked_reason ?? ""] ?? c.not_checked_reason}</span>
      </p>
      <p className="cc-claim">{hidden ? "A claim outside our content policy" : `“${c.claim_text}”`}</p>
      {!hidden && (
        <div className="cc-actions">
          {active && phase === "ended"
            ? <button className="btn small" onClick={onKeepWatching}>Keep watching</button>
            : canWatch && <button className="btn small" onClick={onWatch}>▶ Watch 20 s</button>}
        </div>
      )}
    </article>
  );
}

function SourceText({ s }: { s: Citation }) {
  return s.summary ? <>{s.quote}</> : <>“{s.quote}”</>;
}

function SourceFull({ s, color }: { s: Citation; color: string }) {
  return (
    <figure className="source" style={{ borderColor: color }}>
      {s.summary
        ? <p className="source-summary"><span className="meta">Source summary: </span>{s.quote}</p>
        : <blockquote>“{s.quote}”</blockquote>}
      <figcaption>
        {s.url
          ? <><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>
              <span className="meta"> {domain(s.url)}. {PLAIN_TIER[s.tier] ?? ""}</span></>
          : <><span>{s.title}</span><span className="meta"> (source link to be attached)</span></>}
      </figcaption>
    </figure>
  );
}

/**
 * A claim with its evidence visible up front. "Watch 20 s" plays the moment; after the clip the card
 * offers Keep watching or Next claim. "More" expands in place: what was said, why, all sources, actions.
 */
export function ClaimCard({ claim: c, videoId, expanded, active, phase, countdown, hasNext, canWatch, onToggle, onWatch, onKeepWatching, onNext, onSeek, onShare, onCopySource }: {
  claim: Claim; videoId: string; expanded: boolean; active: boolean; phase: CardPhase; countdown: number | null; hasNext: boolean; canWatch: boolean;
  onToggle(): void; onWatch(): void; onKeepWatching(): void; onNext(): void; onSeek(): void; onShare(): void; onCopySource(): void;
}) {
  const v = c.verdict;
  const color = v ? VERDICTS[v.verdict].cssVar : "var(--ink-soft)";
  const visibleSources = v ? (v.verdict === "disputed" ? v.citations : v.citations.slice(0, 1)) : [];

  return (
    <article id={`card-${c.id}`} data-claim={c.id} className={`claim-card${active ? " is-active" : ""}${expanded ? " is-open" : ""}`}>
      <div className="cc-head">
        <TimeLink videoId={videoId} seconds={c.start_s} onSeek={onSeek} />
        {c.speaker && <span className="meta">{c.speaker}</span>}
        {active && phase === "playing" && <span className="cc-playing">Playing</span>}
      </div>

      {v ? <p className="cc-verdict"><span className="vword" style={{ color }}>{VERDICTS[v.verdict].label}</span></p>
         : <p className="cc-verdict"><span className="pending-word">With a reviewer</span></p>}

      <p className="cc-claim">“{c.claim_text}”</p>

      {!expanded && visibleSources.length > 0 && (
        <div className="cc-sources">
          {visibleSources.map((s) => (
            <p key={`${s.title}-${s.url}`} className="cc-src" style={{ borderColor: color }}>
              <span className="cc-src-text"><SourceText s={s} /></span>
              <span className="meta"> {s.title ?? (s.url ? domain(s.url) : "")}</span>
            </p>
          ))}
        </div>
      )}
      {!v && <p className="meta">A reviewer is checking this verdict before it's shown.</p>}

      {expanded && v && (
        <div className="cc-more">
          {c.context_quote && <p className="said">What was said: “{c.context_quote}”</p>}
          <p className="meta">{VERDICTS[v.verdict].meaning}</p>
          <div className={`quotes${v.citations.length > 1 ? " quotes-two" : ""}`}>
            {v.citations.map((s) => <SourceFull key={`${s.title}-${s.url}`} s={s} color={color} />)}
          </div>
          <h3 className="sheet-h">Why</h3>
          <p>{v.reasoning}</p>
          {v.evidence_grade && v.evidence_grade !== "not_applicable" && (
            <p className="meta">Strength of evidence: {v.evidence_grade.replaceAll("_", " ")}</p>
          )}
          <p className="trust">
            {v.citations.some((s) => s.summary) ? "Imported verdict; the quote check hasn't run yet." : "Checked by AI; the quote was verified in the source."}
            {v.review_status === "approved" && " Reviewed by a person before publishing."}
            {v.review_status === "changed" && " Verdict changed after review by a person."}
          </p>
          {!!c.also_said_in?.length && (
            <>
              <h3 className="sheet-h">Also said in</h3>
              <ul className="also">
                {c.also_said_in.map((a) => (
                  <li key={a.claim_id}>
                    <Link href={`/v/${a.youtube_video_id}#claim-${a.claim_id}`}>{a.title}</Link>
                    <span className="meta"> {a.channel_name}, at {clock(a.start_s)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="cc-actions">
            <button className="btn secondary small" onClick={onShare}>Share</button>
            {v.citations.length > 0 && <button className="btn secondary small" onClick={onCopySource}>Copy source</button>}
          </div>
          <FeedbackForm claimId={c.id} />
        </div>
      )}

      <div className="cc-actions">
        {active && phase === "ended" ? (
          <>
            <button className="btn small" onClick={onKeepWatching}>Keep watching</button>
            {hasNext && <button className="btn secondary small" onClick={onNext}>Next claim{countdown !== null ? ` (${countdown})` : ""}</button>}
          </>
        ) : (
          canWatch && <button className="btn small" onClick={onWatch}>▶ Watch 20 s</button>
        )}
        {v && <button className="btn secondary small" onClick={onToggle} aria-expanded={expanded}>{expanded ? "Less" : "More"}</button>}
      </div>
    </article>
  );
}
