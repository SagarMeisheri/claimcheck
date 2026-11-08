import { groupByQuestion } from "./qa";
import { visibleClaims } from "./notes";
import type { AnswerType, Claim, ClaimKind, Grounding, IncentiveTag, Interaction, QaFlag, QuestionType } from "./types";

/**
 * The colour language of the indicators. Each colour keeps one meaning on every chip:
 * blue = found / neutral, amber = look closer, red = independent sources differ, grey = unknown, purple = nothing to check.
 * Every chip also has a glyph and a word, so colour is never the only signal.
 */
export type Tone = "blue" | "amber" | "red" | "grey" | "purple";
export interface IndicatorUi { word: string; glyph: string; tone: Tone; hint: string }

export const QUESTION_UI: Record<QuestionType, IndicatorUi> = {
  factual: { word: "Factual", glyph: "□", tone: "blue", hint: "Asks for a fact, a definition or a figure." },
  explanatory: { word: "Explanatory", glyph: "↻", tone: "blue", hint: "Asks how or why: a process, a cause or a mechanism." },
  experiential: { word: "Experiential", glyph: "◎", tone: "blue", hint: "Asks for the guest's own story, history or decisions." },
  evaluative: { word: "Evaluative", glyph: "◇", tone: "blue", hint: "Asks for a judgement, a preference or a critique." },
  speculative: { word: "Speculative", glyph: "↗", tone: "blue", hint: "Asks for a prediction or a what-if." },
  challenging: { word: "Pushback", glyph: "!", tone: "blue", hint: "Tests a premise, puts a criticism or counter-view, or plays devil's advocate." },
  unclear: { word: "Unclear", glyph: "?", tone: "grey", hint: "Can't tell from the words." },
};

export const ANSWER_UI: Record<AnswerType, IndicatorUi> = {
  direct: { word: "Direct", glyph: "→", tone: "blue", hint: "Answers the exact question clearly and straight away." },
  narrative: { word: "Narrative", glyph: "❝", tone: "blue", hint: "Answers through a story, an example or an analogy." },
  structured: { word: "Structured", glyph: "≡", tone: "blue", hint: "Breaks the answer into a list, a framework or steps." },
  pivot: { word: "Pivot", glyph: "↪", tone: "amber", hint: "Shifts the topic or changes the question's premise before answering." },
  evasive: { word: "Evasive", glyph: "∅", tone: "amber", hint: "Dodges, deflects or gives a vague generality instead of an answer." },
  unclear: { word: "Unclear", glyph: "?", tone: "grey", hint: "Can't tell how it was answered." },
};

export const CLAIM_UI: Record<ClaimKind, IndicatorUi> = {
  objective_fact: { word: "Objective fact", glyph: "■", tone: "blue", hint: "Checkable data, events, rules, quotes or the speaker's own past actions." },
  anchored_opinion: { word: "Anchored opinion", glyph: "◆", tone: "blue", hint: "A judgement backed by a stated fact or figure." },
  pure_opinion: { word: "Pure opinion", glyph: "◇", tone: "purple", hint: "Taste, feeling or belief with no factual premise to check." },
  prediction: { word: "Prediction", glyph: "↗", tone: "blue", hint: "A guess about the future." },
};

export const GROUNDING_UI: Record<Grounding, IndicatorUi> = {
  grounded: { word: "Grounded", glyph: "✓", tone: "blue", hint: "The pages found state the same facts or premises." },
  plausible: { word: "Plausible", glyph: "~", tone: "grey", hint: "Fits what is known, but no page settles it either way. That says nothing against the answer." },
  contradicted: { word: "Contradicted", glyph: "✕", tone: "red", hint: "Pages give a different figure or account for a main point or premise." },
  exempt: { word: "Exempt", glyph: "◇", tone: "purple", hint: "An opinion, feeling or what-if: nothing a source could check." },
  ungrounded: { word: "Ungrounded", glyph: "⚠", tone: "amber", hint: "It serves the speaker's own interest and only their word backs it: no independent page does." },
};

export const FLAG_UI: Record<QaFlag, IndicatorUi> = {
  missing_context: { word: "Missing context", glyph: "⋯", tone: "amber", hint: "The facts check out, but the pages give a figure, period or caveat the answer leaves out." },
  staged_pushback: { word: "Staged pushback", glyph: "◔", tone: "amber", hint: "A generic criticism, from a host tied to the guest, that sets up a ready rebuttal." },
  self_serving_pivot: { word: "Self-serving pivot", glyph: "↪", tone: "amber", hint: "The reframe steers toward the speaker's own product, company or holding." },
};

export const DISCLOSURE_UI = {
  disclosed: { word: "Disclosed", glyph: "◆", tone: "blue", hint: "The speaker's interest was made known to viewers." },
  undisclosed: { word: "Undisclosed", glyph: "◆", tone: "amber", hint: "The answer serves an interest of the speaker's that viewers weren't told about." },
} satisfies Record<string, IndicatorUi>;

export const SELF_REPORT_UI: IndicatorUi = { word: "Self-report", glyph: "◆", tone: "amber", hint: "The claim serves the speaker's own commercial or financial interest." };

/** What the Conflict and Stake chips say when nothing was found, so every tagged answer shows both results. */
export const NO_CONFLICT_UI: IndicatorUi = { word: "None", glyph: "○", tone: "grey", hint: "No conflict of interest was found: the answer doesn't serve a commercial or financial interest of the speaker's." };
export const NO_STAKE_UI: IndicatorUi = { word: "None", glyph: "○", tone: "grey", hint: "The answer doesn't serve an interest of the speaker's, so there was nothing to disclose." };

export const INCENTIVE_UI: Record<IncentiveTag, IndicatorUi> = {
  commercial: { word: "Commercial", glyph: "$", tone: "amber", hint: "Sells a book, product, course, service or show of their own." },
  financial: { word: "Financial", glyph: "%", tone: "amber", hint: "Holds equity or investments in companies, assets or a sector." },
  ideological: { word: "Ideological", glyph: "⚑", tone: "amber", hint: "Advocates for a party, government, policy or worldview." },
  reputational: { word: "Reputational", glyph: "◐", tone: "amber", hint: "Dealing with a controversy or rebuilding a public image." },
  academic: { word: "Institutional", glyph: "▲", tone: "amber", hint: "A researcher, academic or official with findings or a post to defend." },
  sponsor_aligned: { word: "Sponsor-aligned", glyph: "$", tone: "amber", hint: "The show's sponsors or paid partners sell in the subjects it covers." },
  invested_peer: { word: "Invested peer", glyph: "⇄", tone: "amber", hint: "The host is tied to the guest's company." },
  adversarial: { word: "Adversarial", glyph: "!", tone: "blue", hint: "Known for tough, accountability-style questioning." },
};

export const DYNAMIC_UI: Record<NonNullable<Interaction["dynamic"]>, IndicatorUi> = {
  promotional: { word: "Promotional", glyph: "◔", tone: "amber", hint: "Friendly and aligned: soft or teed-up questions, little real pushback." },
  neutral: { word: "Exploratory", glyph: "○", tone: "blue", hint: "Genuine curiosity, with occasional follow-ups or counter-views." },
  adversarial: { word: "Adversarial", glyph: "!", tone: "blue", hint: "The host repeatedly presses or stress-tests the guest's claims." },
};

export const EVIDENCE_UI = {
  strong: { bars: 2, word: "Strong", hint: "Pages from three or more sites came back for this answer." },
  limited: { bars: 1, word: "Limited", hint: "Pages from one or two sites came back for this answer." },
  none: { bars: 0, word: "None", hint: "No page came back for this answer." },
} as const;

/** The staged-pushback flag counts only when the question really was a challenge. */
export function flagsOf(c: Claim): QaFlag[] {
  const flags = c.qa_tags?.flags ?? [];
  return flags.filter((f) => f !== "staged_pushback" || c.question_analysis?.type === "challenging");
}

/** "Challenging Q → Pivot A → Anchored opinion → Grounded (missing context)": the one-line tagging string. */
export function chainOf(c: Claim): string {
  const qt = c.question_kind !== "implied" ? c.question_analysis?.type : undefined;
  const q = qt && qt in QUESTION_UI ? `${qt === "challenging" ? "Challenging" : QUESTION_UI[qt].word} Q` : "";
  const parts = [q, c.qa_tags?.chain ?? ""].filter(Boolean);
  return parts.join(" → ");
}

export type PatternKind = "staged_pushback" | "self_serving_pivot" | "unchallenged_anchored";
export const PATTERN_UI: Record<PatternKind, { word: string; hint: string }> = {
  staged_pushback: { word: "Softball setup", hint: "A pushback question from a host tied to the guest, answered with a ready rebuttal the host doesn't press." },
  self_serving_pivot: { word: "Self-serving pivot", hint: "The guest reframes a broad question toward their own product, company or holding." },
  unchallenged_anchored: { word: "Unchallenged opinion", hint: "An opinion resting on an unverified or self-reported premise, and the host's next question doesn't push back." },
};
export interface Pattern { kind: PatternKind; claim: Claim }

export interface InterviewProfile {
  asked: number; // exchanges with a tagged question
  questions: Record<QuestionType, number>;
  approx: number; // questions tagged from the AI's plain-words version (older videos), where framing may be missed
  answered: number; // answers with an answer type
  answers: Record<AnswerType, number>;
  grounded: number; // answers with a grounding label
  grounding: Record<Grounding, number>;
  conflicts: number; // answers flagged self-report or self-serving pivot
  undisclosed: number;
  patterns: Pattern[];
}

const zero = <K extends string>(keys: readonly K[]) => Object.fromEntries(keys.map((k) => [k, 0])) as Record<K, number>;

/** Tallies of how the questions were asked and answered and what the evidence shows, plus the patterns found in sequence. */
export function interviewProfile(claims: Claim[]): InterviewProfile | null {
  const visible = visibleClaims(claims).filter((c) => c.question).sort((a, b) => a.start_s - b.start_s);
  const questions = zero(["factual", "explanatory", "experiential", "evaluative", "speculative", "challenging", "unclear"] as const);
  const answers = zero(["direct", "narrative", "structured", "pivot", "evasive", "unclear"] as const);
  const grounding = zero(["grounded", "plausible", "contradicted", "exempt", "ungrounded"] as const);
  let asked = 0, approx = 0, answered = 0, grounded = 0, conflicts = 0, undisclosed = 0;
  const groups = groupByQuestion(visible);
  const patterns: Pattern[] = [];
  groups.forEach((g, i) => {
    const qa = g.answers[0].question_analysis;
    if (qa && !g.implied && qa.type in questions) { asked++; questions[qa.type]++; if (qa.spoken === false) approx++; }
    const nextQ = groups.slice(i + 1).find((x) => !x.implied)?.answers[0].question_analysis?.type;
    for (const c of g.answers) {
      const t = c.qa_tags;
      if (!t) continue;
      if (t.answer) { answered++; answers[t.answer.type]++; }
      if (t.grounding) { grounded++; grounding[t.grounding.label]++; }
      if (t.conflict) { conflicts++; if (t.conflict.disclosure === "undisclosed") undisclosed++; }
      const flags = flagsOf(c);
      if (flags.includes("staged_pushback")) patterns.push({ kind: "staged_pushback", claim: c });
      if (flags.includes("self_serving_pivot")) patterns.push({ kind: "self_serving_pivot", claim: c });
      if (t.claim?.type === "anchored_opinion" && ["plausible", "ungrounded"].includes(t.grounding?.label ?? "") && nextQ && nextQ !== "challenging") {
        patterns.push({ kind: "unchallenged_anchored", claim: c });
      }
    }
  });
  if (!asked && !answered) return null;
  return { asked, questions, approx, answered, answers, grounded, grounding, conflicts, undisclosed, patterns };
}

/** One tag picked at the top of the questions as a filter: how the question was asked, how it was answered, or the evidence. */
export type TagFilter = { dim: "q"; key: QuestionType } | { dim: "a"; key: AnswerType } | { dim: "g"; key: Grounding };

/** The answers a tag filter keeps. A question tag keeps every answer to a question tagged that way. */
export function applyTagFilter(claims: Claim[], f: TagFilter | null): Claim[] {
  if (!f) return claims;
  if (f.dim === "a") return claims.filter((c) => c.qa_tags?.answer?.type === f.key);
  if (f.dim === "g") return claims.filter((c) => c.qa_tags?.grounding?.label === f.key);
  return groupByQuestion(claims).filter((g) => !g.implied && g.answers[0].question_analysis?.type === f.key).flatMap((g) => g.answers);
}
