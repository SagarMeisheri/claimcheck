"use client";

import { useState, type ReactNode } from "react";
import { Chip, NOTE, stakeUi } from "@/components/Indicators";
import { MatchBadge, SOURCES_NOTE } from "@/components/SourceList";
import { domain } from "@/lib/format";
import {
  ANSWER_UI, CLAIM_UI, DISCLOSURE_UI, FLAG_UI, GROUNDING_UI, QUESTION_UI, SELF_REPORT_UI, TOUCHES_UI, chainOf, flagsOf,
} from "@/lib/indicators";
import type { Claim, Source } from "@/lib/types";

/**
 * The detail panel's top half, built to be read without scrolling: the verdict and the reason for it, the chips that
 * say how the answer was asked, answered and tied to the speaker (their definitions are on hover), and the pages
 * behind the verdict as one-line rows. The rest (stake, how it was asked, searches, transcript) sits in folded rows
 * below, each with its own one-line summary.
 */

const plain = (t?: string | null) => (t ?? "").replace(/\s*\[\d+\]/g, "").replace(/\s+([.,;:])/g, "$1").trim();

/** The verdict, why, and the other tags as chips. Nothing for a statement that has no tags. */
export function VerdictBrief({ c }: { c: Claim }) {
  const qa = c.question_analysis;
  const t = c.qa_tags;
  const g = t?.grounding;
  const k = g?.contradiction;
  const ui = g ? GROUNDING_UI[g.label] : null;
  const chips: ReactNode[] = [];
  if (t?.conflict) chips.push(<Chip key="conflict" ui={t.conflict.kind === "self_report" ? SELF_REPORT_UI : FLAG_UI.self_serving_pivot} category="Conflict" />);
  else if (t?.stake) chips.push(<Chip key="stake" ui={stakeUi(t.stake)} category="Stake" />);
  if (t?.conflict?.disclosure === "undisclosed") chips.push(<Chip key="disc" ui={DISCLOSURE_UI.undisclosed} category="Interest" />);
  for (const f of flagsOf(c).filter((x) => x !== "self_serving_pivot")) chips.push(<Chip key={f} ui={FLAG_UI[f]} category="Flag" />);
  if (t?.answer) chips.push(<Chip key="answer" ui={ANSWER_UI[t.answer.type]} tag={`a-${t.answer.type}`} category="Answer" />);
  if (t?.claim) chips.push(<Chip key="claim" ui={CLAIM_UI[t.claim.type]} category="Claim" />);
  if (qa && qa.type in QUESTION_UI) chips.push(<Chip key="q" ui={QUESTION_UI[qa.type]} tag={`q-${qa.type}`} category="Question" approx={qa.spoken === false} />);
  if (!g && !chips.length) return null;
  return (
    <section className={`vb${g ? ` ipt-g-${g.label}` : ""}`} aria-label="Verdict">
      {g && ui && (
        <>
          <p className="vb-verdict">
            <span className={`ind vbadge is-${ui.tone} ipt-g-${g.label}`}><span className="ind-glyph" aria-hidden="true">{ui.glyph}</span><span className="ind-word">{ui.word}</span></span>
            <span className="op-ai" title={NOTE}>AI-tagged</span>
          </p>
          {k ? (
            <>
              <p className="vb-why">{k.difference}</p>
              <p className="vb-vs"><span><b>Said</b> {k.said}</span><span><b>Pages say</b> {k.sources_say}</span></p>
            </>
          ) : <p className="vb-why">{ui.hint}{g.was ? ` The pages alone would make it ${GROUNDING_UI[g.was].word.toLowerCase()}.` : ""}</p>}
        </>
      )}
      {chips.length > 0 && <p className="ind-row vb-chips">{chips}</p>}
    </section>
  );
}

const ORIGIN: Record<string, string> = { own_organisation: "speaker's org", same_episode: "this episode" };
const SHOWN = 3;

interface Row { source: Source; quote: string; counter: boolean; differs: boolean }

/** The pages behind the answer: the ones the verdict rests on first, each as a site, a title and the line that matters. */
export function SourceRows({ c }: { c: Claim }) {
  const [all, setAll] = useState(false);
  const g = c.qa_tags?.grounding;
  const basis = new Map((g?.basis ?? []).map((b) => [b.url, b]));
  const diff = g?.contradiction;
  const seen = new Set<string>();
  const rows: Row[] = [
    ...c.sources.map((source) => ({ source, counter: false })),
    ...(c.counter_sources ?? []).map((source) => ({ source, counter: true })),
    ...(g?.basis ?? []).filter((b) => !c.sources.some((s) => s.url === b.url)).map((b) => ({ source: { url: b.url, title: null, excerpt: "", publish_date: null, rank: 99 } as Source, counter: false })),
  ].filter(({ source }) => !seen.has(source.url) && !!seen.add(source.url)).map(({ source, counter }) => {
    const b = basis.get(source.url);
    const differs = !!diff && diff.url === source.url;
    return { source, counter, differs, quote: plain(differs && diff.quote ? diff.quote : b?.quote || b?.finding || source.excerpt) };
  });
  // Stable: pages the verdict rests on, and the one that differs, come first.
  const weight = (r: Row) => (r.differs ? 0 : basis.has(r.source.url) ? 1 : 2);
  rows.sort((a, b) => weight(a) - weight(b));
  const summary = !g ? plain(c.sources_summary) : "";
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <section className="dr" aria-label="Sources">
      <div className="src-head">
        <span className="src-label" title={SOURCES_NOTE}>Sources <span className="dr-count">{rows.length} {rows.length === 1 ? "page" : "pages"}</span></span>
        {c.sources_match && <MatchBadge match={c.sources_match} />}
      </div>
      {summary && <p className="dr-sum">{summary}</p>}
      {rows.length === 0 ? <p className="meta source-none">The web search found no sources for this statement.</p> : (
        <ul className="dr-list">
          {shown.map(({ source: s, quote, counter, differs }) => {
            const site = domain(s.url);
            const title = s.title && s.title !== site ? s.title : "";
            return (
              <li key={s.url} className={differs ? "is-differs" : undefined}>
                <a className="dr-link" href={s.url} target="_blank" rel="noopener noreferrer nofollow" title={title || site}>
                  <span className="dr-head">
                    <span className="dr-site">{site}</span>
                    {differs && <span className="dr-tag is-differs">differs</span>}
                    {ORIGIN[s.independence ?? ""] && <span className="dr-tag">{ORIGIN[s.independence ?? ""]}</span>}
                    {counter && !differs && <span className="dr-tag">other view</span>}
                  </span>
                  {title && <span className="dr-title">{title}</span>}
                </a>
                {quote && <p className="dr-quote">“{quote}”</p>}
              </li>
            );
          })}
        </ul>
      )}
      {rows.length > SHOWN && <button type="button" className="linkish dr-more" onClick={() => setAll((v) => !v)} aria-expanded={all}>{all ? "Show fewer" : `+ ${rows.length - SHOWN} more`}</button>}
    </section>
  );
}

/** A folded row: a label and a one-line summary, the whole line opens it. */
export function Fold({ label, summary, tone, children }: { label: string; summary: ReactNode; tone?: "amber"; children: ReactNode }) {
  return (
    <details className="df">
      <summary><span className="df-label">{label}</span><span className={`df-sum${tone ? ` is-${tone}` : ""}`}>{summary}</span></summary>
      <div className="df-body">{children}</div>
    </details>
  );
}

/** The folded rows under the sources: who or what the answer favours, how it was asked and answered. */
export function TagFolds({ c }: { c: Claim }) {
  const t = c.qa_tags;
  const qa = c.question_analysis;
  const flags = flagsOf(c);
  const hasStake = !!t && (t.stake || t.conflict || flags.length > 0 || t.profile_checked !== undefined);
  const chain = chainOf(c);
  const speaker = c.speaker ?? "the speaker";
  return (
    <>
      {t && hasStake && (
        <Fold label="Stake" tone={t.stake?.disclosure === "undisclosed" ? "amber" : undefined}
              summary={t.stake ? <>{t.stake.item.text}{t.stake.disclosure ? <span className="df-note"> · {DISCLOSURE_UI[t.stake.disclosure].word.toLowerCase()}</span> : null}</>
                : t.conflict || flags.length ? "Flagged, no profile item" : `none of ${t.profile_checked} profile ${t.profile_checked === 1 ? "item" : "items"}`}>
          {t.stake && (
            <>
              <p className="df-line"><span className="df-k">{speaker}&apos;s profile</span></p>
              <blockquote className="rs-quote">{t.stake.item.text}{t.stake.item.url ? <> <a className="meta" href={t.stake.item.url} target="_blank" rel="noopener noreferrer nofollow">{t.stake.item.site || "source"}</a></> : null}</blockquote>
              <p className="meta">{t.stake.link === "touches" ? TOUCHES_UI.hint : SELF_REPORT_UI.hint}{t.stake.disclosure ? ` ${DISCLOSURE_UI[t.stake.disclosure].hint}` : ""}</p>
            </>
          )}
          {(t.conflict?.kind === "self_serving_pivot" || flags.length > 0) && (
            <ul className="nclist">
              {t.conflict?.kind === "self_serving_pivot" && <li>{FLAG_UI.self_serving_pivot.hint}</li>}
              {flags.filter((f) => f !== "self_serving_pivot").map((f) => <li key={f}>{FLAG_UI[f].hint}</li>)}
            </ul>
          )}
          {!t.stake && !t.conflict && !flags.length && <p className="meta">The answer ties to none of the {t.profile_checked} profile {t.profile_checked === 1 ? "item" : "items"} checked.</p>}
        </Fold>
      )}
      {(qa || t?.answer) && (
        <Fold label="How asked" summary={chain || "Question and answer"}>
          <dl className="df-dl">
            {qa && qa.type in QUESTION_UI && <><dt>Question</dt><dd><b>{QUESTION_UI[qa.type].word}.</b> {QUESTION_UI[qa.type].hint}{qa.spoken === false ? " Approximate: tagged from the AI's plain-words version of the question." : ""}</dd></>}
            {t?.answer && <><dt>Answer</dt><dd><b>{ANSWER_UI[t.answer.type].word}.</b> {ANSWER_UI[t.answer.type].hint}</dd></>}
            {t?.claim && <><dt>Claim</dt><dd><b>{CLAIM_UI[t.claim.type].word}.</b> {CLAIM_UI[t.claim.type].hint}</dd></>}
          </dl>
        </Fold>
      )}
    </>
  );
}
