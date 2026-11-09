"use client";

import { useState } from "react";
import { clock } from "@/lib/format";
import {
  ANSWER_UI, CLAIM_UI, DISCLOSURE_UI, DYNAMIC_UI, FLAG_UI, GROUNDING_UI, INCENTIVE_UI, NO_STAKE_UI, PATTERN_UI, QUESTION_UI, SELF_REPORT_UI, STAKE_KIND_WORD, TOUCHES_UI,
  chainOf, flagsOf, interviewProfile, verdictOf, type IndicatorUi, type TagFilter,
} from "@/lib/indicators";
import type { AnswerType, Claim, QaTags, Grounding, Incentive, IncentiveTag, Interaction, QuestionAnalysis, QuestionType } from "@/lib/types";

/**
 * The indicators beside a question and its answer, from the Q&A taxonomy:
 *   [Question] → [Answer] → [Claim] → [Grounding + conflict flag]
 * Colour, a glyph and one word each; the pages and profile facts behind them are a tap away in the detail panel.
 */

const NOTE = "Tagged by AI classifiers from the question, the answer, the speakers' profiles and web pages. It describes what was found and can be wrong.";

function Chip({ ui, category, onOpen, extra, approx, tag, bare }: { ui: IndicatorUi; category: string; onOpen?(): void; extra?: string; approx?: boolean; tag?: string; bare?: boolean }) {
  const body = (
    <>
      {!bare && <span className="ind-cat">{category}</span>}
      <span className="ind-glyph" aria-hidden="true">{ui.glyph}</span>
      <span className="ind-word">{ui.word}</span>
      {approx && <span className="ind-approx" aria-hidden="true">≈</span>}
    </>
  );
  const title = `${category}: ${ui.word}. ${ui.hint}${extra ? ` ${extra}` : ""}${approx ? " Approximate: tagged from the AI's plain-words version of the question, so framing may be missed." : ""}`;
  const cls = `ind is-${ui.tone}${tag ? ` ipt-${tag}` : ""}${approx ? " is-approx" : ""}`; // tag: the colour shared with the interview profile at the top
  return onOpen
    ? <button type="button" className={cls} onClick={onOpen} title={title} aria-label={`${category}: ${ui.word}${approx ? " (approximate)" : ""}. Open the details`}>{body}</button>
    : <span className={cls} title={title}>{body}</span>;
}

/** The question's chip: what kind of question it was. */
export function QuestionIndicator({ analysis, onOpen }: { analysis: QuestionAnalysis | null | undefined; onOpen?(): void }) {
  if (!analysis || !(analysis.type in QUESTION_UI)) return null;
  return (
    <p className="ind-row" aria-label="How the question was asked">
      <Chip ui={QUESTION_UI[analysis.type]} tag={`q-${analysis.type}`} category="Question" onOpen={onOpen} approx={analysis.spoken === false} />
    </p>
  );
}

/** The Stake chip: the kind of profile item the answer ties to (amber when undisclosed), or None. */
function stakeUi(stake: QaTags["stake"]): IndicatorUi {
  if (!stake) return NO_STAKE_UI;
  const word = STAKE_KIND_WORD[stake.item.kind] ?? "Profile";
  const base = stake.link === "touches" ? TOUCHES_UI : SELF_REPORT_UI;
  return { word: `${word}${stake.disclosure === "undisclosed" ? ", undisclosed" : stake.disclosure === "disclosed" ? ", disclosed" : ""}`, glyph: base.glyph, tone: stake.disclosure === "disclosed" ? "blue" : "amber",
           hint: `${stake.link === "touches" ? TOUCHES_UI.hint : "The answer favours this item of the speaker's profile."}` };
}

/** The verdict of an answer, as the first thing on its card: glyph and word in the verdict's colour. Opens the details. */
export function VerdictBadge({ c, onOpen }: { c: Claim; onOpen(): void }) {
  const g = verdictOf(c);
  if (!g) return null;
  const ui = GROUNDING_UI[g];
  const was = c.qa_tags?.grounding?.was;
  return (
    <button type="button" className={`ind vbadge is-${ui.tone} ipt-g-${g}`} onClick={onOpen}
            title={`${ui.hint}${was ? ` Without the self-report rule it would read ${GROUNDING_UI[was].word}.` : ""} Tagged by AI. Open the details.`}
            aria-label={`Evidence: ${ui.word}. Open the details`}>
      <span className="ind-glyph" aria-hidden="true">{ui.glyph}</span>
      <span className="ind-word">{ui.word}</span>
    </button>
  );
}

/** Only what was found about an answer besides its verdict: a conflict, a stake, a flag, a pivot or an evasive answer. Nothing found, nothing shown. */
export function AnswerSignals({ c, onOpen }: { c: Claim; onOpen(): void }) {
  const t = c.qa_tags;
  if (!t) return null;
  const chips: React.ReactNode[] = [];
  if (t.conflict) {
    chips.push(<Chip key="conflict" ui={t.conflict.kind === "self_report" ? SELF_REPORT_UI : FLAG_UI.self_serving_pivot} category="Conflict" onOpen={onOpen}
                     extra={t.stake?.link === "benefits" ? `Tied to: ${t.stake.item.text}` : undefined} />);
  }
  if (t.stake) chips.push(<Chip key="stake" ui={stakeUi(t.stake)} category="Stake" onOpen={onOpen} extra={`${t.stake.item.text}${t.stake.disclosure ? ` (${t.stake.disclosure})` : ""}`} />);
  if (t.answer && (t.answer.type === "pivot" || t.answer.type === "evasive")) chips.push(<Chip key="answer" ui={ANSWER_UI[t.answer.type]} tag={`a-${t.answer.type}`} category="Answer" onOpen={onOpen} />);
  for (const f of flagsOf(c).filter((x) => x !== "self_serving_pivot")) chips.push(<Chip key={f} ui={FLAG_UI[f]} category="Flag" onOpen={onOpen} />);
  return chips.length ? <span className="vc-signals" aria-label="Also found">{chips}</span> : null;
}

/** In the detail panel: the tagging string and what each tag rests on. */
export function IndicatorEvidence({ c }: { c: Claim }) {
  const qa = c.question_analysis;
  const t = c.qa_tags;
  if (!qa && !t) return null;
  const g = t?.grounding;
  return (
    <section className="ind-detail" aria-label="What the tags rest on">
      <h4 className="rs-title">Tags <span className="op-ai" title={NOTE}>AI-tagged</span></h4>
      <p className="qa-chain">{chainOf(c)}</p>
      {qa && qa.type in QUESTION_UI && (
        <div className="op-block">
          <p className="op-label">How the question was asked</p>
          <p className="op-value"><Chip ui={QUESTION_UI[qa.type]} tag={`q-${qa.type}`} category="Question" approx={qa.spoken === false} /></p>
          <p className="meta">{QUESTION_UI[qa.type].hint}</p>
        </div>
      )}
      {t?.answer && (
        <div className="op-block">
          <p className="op-label">How it was answered</p>
          <p className="op-value"><Chip ui={ANSWER_UI[t.answer.type]} tag={`a-${t.answer.type}`} category="Answer" />{t.claim && <> <Chip ui={CLAIM_UI[t.claim.type]} category="Claim" /></>}</p>
          <p className="meta">{ANSWER_UI[t.answer.type].hint}{t.claim ? ` ${CLAIM_UI[t.claim.type].hint}` : ""}</p>
        </div>
      )}
      {t && (t.stake || t.profile_checked !== undefined) && (
        <div className="op-block">
          <p className="op-label">Compared with {c.speaker ?? "the speaker"}&apos;s profile</p>
          {t.stake ? (
            <>
              <p className="op-value"><Chip ui={t.stake.link === "touches" ? TOUCHES_UI : SELF_REPORT_UI} category={t.stake.link === "touches" ? "Stake" : "Conflict"} /></p>
              <blockquote className="rs-quote">{t.stake.item.text}{t.stake.item.url ? <> <a className="meta" href={t.stake.item.url} target="_blank" rel="noopener noreferrer nofollow">{t.stake.item.site || "source"}</a></> : null}</blockquote>
              <p className="meta">{t.stake.link === "touches" ? TOUCHES_UI.hint : SELF_REPORT_UI.hint}{t.stake.disclosure ? ` ${DISCLOSURE_UI[t.stake.disclosure].hint}` : ""}</p>
            </>
          ) : <p className="meta">{t.profile_checked} profile {t.profile_checked === 1 ? "item" : "items"} checked; the answer ties to none of them.</p>}
        </div>
      )}
      {(t?.conflict || flagsOf(c).length > 0) && (
        <div className="op-block">
          <p className="op-label">Conflicts and flags</p>
          <ul className="nclist">
            {t?.conflict?.kind === "self_report" && <li>{SELF_REPORT_UI.hint}</li>}
            {t?.conflict?.kind === "self_serving_pivot" && <li>{FLAG_UI.self_serving_pivot.hint}</li>}
            {t?.conflict?.disclosure && <li>{DISCLOSURE_UI[t.conflict.disclosure].hint}</li>}
            {flagsOf(c).filter((f) => f !== "self_serving_pivot").map((f) => <li key={f}>{FLAG_UI[f].hint}</li>)}
          </ul>
        </div>
      )}
      {g && (
        <div className="op-block">
          <p className="op-label">Is it backed by evidence?</p>
          <p className="op-value"><Chip ui={GROUNDING_UI[g.label]} tag={`g-${g.label}`} category="Evidence" /></p>
          <p className="meta">{GROUNDING_UI[g.label].hint}{g.was ? ` The pages alone would make it ${GROUNDING_UI[g.was].word.toLowerCase()}.` : ""}</p>
          {g.basis.length > 0 && (
            <ul className="rs-findings">
              {g.basis.map((b, i) => (
                <li key={i} className="rs-finding">
                  <p className="rs-f-head"><a href={b.url} target="_blank" rel="noopener noreferrer nofollow">{b.site}</a></p>
                  {b.finding && <p className="rs-f-text">{b.finding}</p>}
                  {b.quote && <blockquote className="rs-quote">“{b.quote}”</blockquote>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

/** A person's incentive tags for this video, each with the fact behind it and where it was found. */
export function IncentiveChips({ incentives, detail = false }: { incentives: Partial<Record<IncentiveTag, Incentive>> | null | undefined; detail?: boolean }) {
  const tags = Object.entries(incentives ?? {}).filter(([k]) => k in INCENTIVE_UI) as [IncentiveTag, Incentive][];
  if (!tags.length) return null;
  return detail ? (
    <ul className="incentives">
      {tags.map(([k, v]) => (
        <li key={k}>
          <Chip ui={INCENTIVE_UI[k]} category="Stake" />{" "}
          <span>{v.reason}</span>
          {v.url ? <> <a className="meta" href={v.url} target="_blank" rel="noopener noreferrer nofollow">{v.site || "source"}</a></> : v.site ? <span className="meta"> ({v.site})</span> : null}
        </li>
      ))}
    </ul>
  ) : (
    <p className="ind-row">{tags.map(([k, v]) => <Chip key={k} ui={INCENTIVE_UI[k]} category="Stake" extra={v.reason} />)}</p>
  );
}
