import { clock } from "@/lib/format";
import {
  ANSWER_UI, CLAIM_UI, DISCLOSURE_UI, DYNAMIC_UI, EVIDENCE_UI, FLAG_UI, GROUNDING_UI, INCENTIVE_UI, PATTERN_UI, QUESTION_UI, SELF_REPORT_UI,
  chainOf, flagsOf, interviewProfile, type IndicatorUi,
} from "@/lib/indicators";
import type { AnswerType, Claim, Grounding, Incentive, IncentiveTag, Interaction, QuestionAnalysis, QuestionType } from "@/lib/types";

/**
 * The indicators beside a question and its answer, from the Q&A taxonomy:
 *   [Question] → [Answer] → [Claim] → [Grounding + conflict flag]
 * Colour, a glyph and one word each; the pages and profile facts behind them are a tap away in the detail panel.
 */

const NOTE = "Tagged by AI classifiers from the question, the answer, the speakers' profiles and web pages. It describes what was found and can be wrong.";

function Chip({ ui, category, onOpen, extra, approx }: { ui: IndicatorUi; category: string; onOpen?(): void; extra?: string; approx?: boolean }) {
  const body = (
    <>
      <span className="ind-cat">{category}</span>
      <span className="ind-glyph" aria-hidden="true">{ui.glyph}</span>
      <span className="ind-word">{ui.word}</span>
      {approx && <span className="ind-approx" aria-hidden="true">≈</span>}
    </>
  );
  const title = `${category}: ${ui.word}. ${ui.hint}${extra ? ` ${extra}` : ""}${approx ? " Approximate: tagged from the AI's plain-words version of the question, so framing may be missed." : ""}`;
  const cls = `ind is-${ui.tone}${approx ? " is-approx" : ""}`;
  return onOpen
    ? <button type="button" className={cls} onClick={onOpen} title={title} aria-label={`${category}: ${ui.word}${approx ? " (approximate)" : ""}. Open the details`}>{body}</button>
    : <span className={cls} title={title}>{body}</span>;
}

/** The question's chip: what kind of question it was. */
export function QuestionIndicator({ analysis, onOpen }: { analysis: QuestionAnalysis | null | undefined; onOpen?(): void }) {
  if (!analysis || !(analysis.type in QUESTION_UI)) return null;
  return (
    <p className="ind-row" aria-label="How the question was asked">
      <Chip ui={QUESTION_UI[analysis.type]} category="Question" onOpen={onOpen} approx={analysis.spoken === false} />
    </p>
  );
}

function Meter({ level }: { level: keyof typeof EVIDENCE_UI }) {
  const e = EVIDENCE_UI[level];
  return (
    <span className="ind is-meter" title={`Evidence: ${e.word}. ${e.hint}`} aria-label={`Evidence: ${e.word}`}>
      <span className="ind-cat">Evidence</span>
      <span className="ind-bars" aria-hidden="true">{[0, 1].map((i) => <i key={i} className={i < e.bars ? "on" : ""} />)}</span>
    </span>
  );
}

/** One answer's chips: how it was answered, what it claims, whether evidence backs it, and any conflict. */
export function AnswerIndicators({ c, onOpen }: { c: Claim; onOpen(): void }) {
  const t = c.qa_tags;
  if (!t) return null;
  const g = t.grounding;
  const flags = flagsOf(c);
  return (
    <p className="ind-row" aria-label="How this answer was tagged">
      {t.answer && <Chip ui={ANSWER_UI[t.answer.type]} category="Answer" onOpen={onOpen} />}
      {t.claim && <Chip ui={CLAIM_UI[t.claim.type]} category="Claim" onOpen={onOpen} />}
      {g && <Chip ui={GROUNDING_UI[g.label]} category="Evidence" onOpen={onOpen} extra={g.was ? `Without the self-report rule it would read ${GROUNDING_UI[g.was].word}.` : undefined} />}
      {t.conflict?.kind === "self_report" && <Chip ui={SELF_REPORT_UI} category="Conflict" onOpen={onOpen} />}
      {t.conflict?.disclosure && <Chip ui={DISCLOSURE_UI[t.conflict.disclosure]} category="Stake" onOpen={onOpen} />}
      {flags.map((f) => <Chip key={f} ui={FLAG_UI[f]} category="Flag" onOpen={onOpen} />)}
      {g && g.label !== "exempt" && g.evidence && <Meter level={g.evidence} />}
      <span className="op-ai" title={NOTE}>AI-tagged</span>
    </p>
  );
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
          <p className="op-value"><Chip ui={QUESTION_UI[qa.type]} category="Question" approx={qa.spoken === false} /></p>
          <p className="meta">{QUESTION_UI[qa.type].hint}</p>
        </div>
      )}
      {t?.answer && (
        <div className="op-block">
          <p className="op-label">How it was answered</p>
          <p className="op-value"><Chip ui={ANSWER_UI[t.answer.type]} category="Answer" />{t.claim && <> <Chip ui={CLAIM_UI[t.claim.type]} category="Claim" /></>}</p>
          <p className="meta">{ANSWER_UI[t.answer.type].hint}{t.claim ? ` ${CLAIM_UI[t.claim.type].hint}` : ""}</p>
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
          <p className="op-value"><Chip ui={GROUNDING_UI[g.label]} category="Evidence" /></p>
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

const Q_ORDER: QuestionType[] = ["factual", "explanatory", "experiential", "evaluative", "speculative", "challenging", "unclear"];
const A_ORDER: AnswerType[] = ["direct", "narrative", "structured", "pivot", "evasive", "unclear"];
const G_ORDER: Grounding[] = ["grounded", "plausible", "ungrounded", "contradicted", "exempt"];

function Segments<K extends string>({ order, counts, ui, label }: { order: K[]; counts: Record<K, number>; ui: Record<K, IndicatorUi>; label: string }) {
  const total = order.reduce((n, k) => n + counts[k], 0);
  if (!total) return null;
  return (
    <>
      <p className="ip-bar" role="img" aria-label={`${label}: ${order.filter((k) => counts[k]).map((k) => `${counts[k]} ${ui[k].word.toLowerCase()}`).join(", ")}`}>
        {order.filter((k) => counts[k]).map((k) => <span key={k} className={`is-${ui[k].tone}`} style={{ flexGrow: counts[k] }} title={`${ui[k].word}: ${counts[k]}. ${ui[k].hint}`} />)}
      </p>
      <p className="ip-legend">
        {order.filter((k) => counts[k]).map((k) => (
          <span key={k} className={`ind is-${ui[k].tone}`} title={ui[k].hint}><span className="ind-glyph" aria-hidden="true">{ui[k].glyph}</span><span className="ind-word">{ui[k].word}</span> <b>{counts[k]}</b></span>
        ))}
      </p>
    </>
  );
}

/** At the top of a video's questions: how the interview was run, how it was answered, what the evidence shows, and the patterns found. */
export function InterviewProfile({ claims, interaction, onOpen }: { claims: Claim[]; interaction?: Interaction | null; onOpen?(c: Claim): void }) {
  const p = interviewProfile(claims);
  if (!p) return null;
  const dyn = interaction?.dynamic ? DYNAMIC_UI[interaction.dynamic] : null;
  return (
    <section className="ip" aria-label="Interview profile">
      <h3 className="ip-title">Interview profile <span className="op-ai" title={NOTE}>AI-tagged</span></h3>
      {dyn && <p className="ip-stats"><Chip ui={dyn} category="Dynamic" /></p>}
      {p.asked > 0 && (
        <div className="ip-block">
          <p className="ip-label">Questions <span className="meta">{p.asked} asked</span></p>
          <Segments order={Q_ORDER} counts={p.questions} ui={QUESTION_UI} label="Questions" />
          {p.approx > 0 && <p className="meta ip-approx">{p.approx === p.asked ? "All" : p.approx} tagged from the AI&apos;s plain-words version of the question (≈), so framing may be missed.</p>}
        </div>
      )}
      {p.answered > 0 && (
        <div className="ip-block">
          <p className="ip-label">Answers <span className="meta">{p.answered} tagged</span></p>
          <Segments order={A_ORDER} counts={p.answers} ui={ANSWER_UI} label="Answers" />
        </div>
      )}
      {p.grounded > 0 && (
        <div className="ip-block">
          <p className="ip-label">Evidence <span className="meta">{p.grounded} answers</span></p>
          <Segments order={G_ORDER} counts={p.grounding} ui={GROUNDING_UI} label="Evidence" />
          {p.conflicts > 0 && (
            <p className="ip-stats"><span className="ip-stat is-amber" title="Answers whose claim serves the speaker's own commercial or financial interest."><span aria-hidden="true">◆</span> Self-serving in <b>{p.conflicts}</b> {p.conflicts === 1 ? "answer" : "answers"}{p.undisclosed ? `, ${p.undisclosed} undisclosed` : ""}</span></p>
          )}
        </div>
      )}
      {p.patterns.length > 0 && (
        <div className="ip-block">
          <p className="ip-label">Patterns</p>
          <ul className="ip-patterns">
            {p.patterns.map((x, i) => (
              <li key={i} title={PATTERN_UI[x.kind].hint}>
                <b>{PATTERN_UI[x.kind].word}</b>{" "}
                {onOpen ? <button type="button" className="linkish" onClick={() => onOpen(x.claim)}>at {clock(x.claim.start_s)}</button> : <span className="meta">at {clock(x.claim.start_s)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
