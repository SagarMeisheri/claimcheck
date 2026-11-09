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

export const NOTE = "Tagged by AI classifiers from the question, the answer, the speakers' profiles and web pages. It describes what was found and can be wrong.";

export function Chip({ ui, category, onOpen, extra, approx, tag, bare }: { ui: IndicatorUi; category: string; onOpen?(): void; extra?: string; approx?: boolean; tag?: string; bare?: boolean }) {
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
export function stakeUi(stake: QaTags["stake"]): IndicatorUi {
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
