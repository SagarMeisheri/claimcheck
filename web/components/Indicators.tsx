import { BIAS_UI, CORRECTNESS_UI, EVIDENCE_UI, PATTERN, QUESTION_UI, biasOf, interviewProfile, stakeOf, type IndicatorUi } from "@/lib/indicators";
import type { Claim, CorrectnessLabel, QuestionAnalysis, QuestionType } from "@/lib/types";

/**
 * The indicators beside a question and its answer: colour, a glyph and one word each. They tally what was found, with the quote behind
 * each one a tap away in the detail panel. Colours: blue found / neutral, amber look closer, red independent sources differ,
 * grey unknown, purple an opinion with nothing to check.
 */

const NOTE = "Worked out by AI from the answer, the question and web pages, and checked against their quotes. It describes what was found and can be wrong.";

function Chip({ ui, category, onOpen, extra, approx }: { ui: IndicatorUi; category: string; onOpen?(): void; extra?: string; approx?: boolean }) {
  const body = (
    <>
      <span className="ind-cat">{category}</span>
      <span className="ind-glyph" aria-hidden="true">{ui.glyph}</span>
      <span className="ind-word">{ui.word}</span>
      {approx && <span className="ind-approx" aria-hidden="true">≈</span>}
    </>
  );
  const title = `${category}: ${ui.word}. ${ui.hint}${extra ? ` ${extra}` : ""}${approx ? " Approximate: tagged from the AI's plain-words version of the question, so leading wording may be missed." : ""}`;
  const cls = `ind is-${ui.tone}${approx ? " is-approx" : ""}`;
  return onOpen
    ? <button type="button" className={cls} onClick={onOpen} title={title} aria-label={`${category}: ${ui.word}${approx ? " (approximate)" : ""}. Open the details`}>{body}</button>
    : <span className={cls} title={title}>{body}</span>;
}

/** The question's chip: how it was asked. */
export function QuestionIndicator({ analysis, onOpen }: { analysis: QuestionAnalysis | null | undefined; onOpen?(): void }) {
  if (!analysis) return null;
  return (
    <p className="ind-row" aria-label="How the question was asked">
      <Chip ui={QUESTION_UI[analysis.type]} category="Question" onOpen={onOpen} approx={analysis.spoken === false} extra={analysis.quote ? `“${analysis.quote}”` : undefined} />
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

/** One answer's chips: correctness, bias, stake and how much evidence stands behind them. Nothing renders until the research has run. */
export function AnswerIndicators({ c, onOpen }: { c: Claim; onOpen(): void }) {
  const k = c.research?.correctness;
  const bias = biasOf(c);
  if (!k && !bias) return null;
  const stake = stakeOf(c);
  const evidence = k?.evidence;
  return (
    <p className="ind-row" aria-label="What was found about this answer">
      {k && <Chip ui={CORRECTNESS_UI[k.label]} category="Correctness" onOpen={onOpen}  />}
      {bias && <Chip ui={BIAS_UI[bias]} category="Bias" onOpen={onOpen} />}
      {stake && <Chip ui={{ word: "Yes", glyph: "◆", tone: "amber", hint: stake }} category="Stake" onOpen={onOpen} />}
      {evidence && <Meter level={evidence} />}
      <span className="op-ai" title={NOTE}>AI-assessed</span>
    </p>
  );
}

/** In the detail panel: the quotes the indicators rest on, so every chip can be checked. */
export function IndicatorEvidence({ c }: { c: Claim }) {
  const qa = c.question_analysis;
  const k = c.research?.correctness;
  if (!qa && !k) return null;
  return (
    <section className="ind-detail" aria-label="What the indicators rest on">
      <h4 className="rs-title">Indicators <span className="op-ai" title={NOTE}>AI-assessed</span></h4>
      {qa && (
        <div className="op-block">
          <p className="op-label">How the question was asked</p>
          <p className="op-value"><Chip ui={QUESTION_UI[qa.type]} category="Question" approx={qa.spoken === false} /></p>
          <p className="meta">{QUESTION_UI[qa.type].hint}</p>
          {qa.quote && <blockquote className="rs-quote">“{qa.quote}”</blockquote>}
        </div>
      )}
      {k && (
        <div className="op-block">
          <p className="op-label">What the pages found show</p>
          <p className="op-value"><Chip ui={CORRECTNESS_UI[k.label]} category="Correctness" /></p>
          <p className="meta">{CORRECTNESS_UI[k.label].hint}</p>
          {k.basis.length > 0 && (
            <ul className="rs-findings">
              {k.basis.map((b, i) => (
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

const Q_ORDER: QuestionType[] = ["open", "closed", "leading", "softball", "challenging", "unclear"];
const A_ORDER: CorrectnessLabel[] = ["supported", "partly", "contradicted", "unverified", "opinion"];

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

/** At the top of a video's questions: how the interview was run and what the sources show, as counts. The counts are the evidence; nothing is inferred from one answer. */
export function InterviewProfile({ claims }: { claims: Claim[] }) {
  const p = interviewProfile(claims);
  if (!p) return null;
  return (
    <section className="ip" aria-label="Interview profile">
      <h3 className="ip-title">Interview profile <span className="op-ai" title={NOTE}>AI-assessed</span></h3>
      {p.asked > 0 && (
        <div className="ip-block">
          <p className="ip-label">Questions <span className="meta">{p.asked} asked</span></p>
          <Segments order={Q_ORDER} counts={p.questions} ui={QUESTION_UI} label="Questions" />
          {p.approx > 0 && <p className="meta ip-approx">{p.approx === p.asked ? "All" : p.approx} tagged from the AI&apos;s plain-words version of the question (≈), so leading wording may be missed.</p>}
          <p className="ip-stats">
            <span className="ip-stat" title="Questions that put a criticism, a counter-view or a demand for evidence to the guest."><b>{p.questions.challenging}</b> of {p.asked} pushed back</span>
          </p>
        </div>
      )}
      {p.answered > 0 && (
        <div className="ip-block">
          <p className="ip-label">Answers, by what independent sources show <span className="meta">{p.answered} checked</span></p>
          <Segments order={A_ORDER} counts={p.answers} ui={CORRECTNESS_UI} label="Answers" />
          {p.stakeAnswers > 0 && (
            <p className="ip-stats"><span className="ip-stat is-amber" title="Answers where a quoted signal showed the speaker has a role or interest in the outcome."><span aria-hidden="true">◆</span> Speaker has a stake in <b>{p.stakeAnswers}</b> {p.stakeAnswers === 1 ? "answer" : "answers"}</span></p>
          )}
        </div>
      )}
      {p.pattern && (
        <p className="ip-pattern" title={`Shown only when there are at least ${PATTERN.minQuestions} questions, ${Math.round(PATTERN.softShare * 100)}% or more of them leading or softball, none pushing back, and the speaker has a stake in at least ${PATTERN.minStakeAnswers} answers.`}>
          Pattern: mostly leading or soft questions, no pushback, and the speaker has a stake in {p.stakeAnswers} answers.
        </p>
      )}
    </section>
  );
}
