import { groupByQuestion } from "./qa";
import { visibleClaims } from "./notes";
import type { Claim, CorrectnessLabel, QuestionType } from "./types";

/**
 * The colour language of the indicators. Blue, amber, red, grey and purple each keep one meaning on every chip:
 * blue = found / neutral, amber = look closer, red = independent sources differ, grey = unknown, purple = an opinion with nothing to check.
 * Every chip also has a glyph and a word, so colour is never the only signal.
 */
export type Tone = "blue" | "amber" | "red" | "grey" | "purple";
export interface IndicatorUi { word: string; glyph: string; tone: Tone; hint: string }

export const CORRECTNESS_UI: Record<CorrectnessLabel, IndicatorUi> = {
  supported: { word: "Supported", glyph: "✓", tone: "blue", hint: "The pages found say the same as the answer." },
  partly: { word: "Partly", glyph: "◐", tone: "amber", hint: "Pages back some of the answer's points; others have none or conflict." },
  contradicted: { word: "Contradicted", glyph: "✕", tone: "red", hint: "Pages give a different figure or account, and none says the same." },
  unverified: { word: "Unverified", glyph: "?", tone: "grey", hint: "The pages found don't speak to the answer's points, or none came back. That says nothing about the answer itself." },
  opinion: { word: "Opinion", glyph: "◇", tone: "purple", hint: "A value judgement: there is nothing to check." },
};

export const BIAS_UI: Record<"balanced" | "leans" | "one_sided" | "cant_tell", IndicatorUi> = {
  balanced: { word: "Balanced", glyph: "●", tone: "blue", hint: "The answer weighs other views and shows few slant signals." },
  leans: { word: "Leans", glyph: "◐", tone: "amber", hint: "Two or more quoted signals point one way." },
  one_sided: { word: "One-sided", glyph: "◑", tone: "amber", hint: "It presents one side as settled, with quoted signals." },
  cant_tell: { word: "Can't tell", glyph: "?", tone: "grey", hint: "Too little evidence to say." },
};

export const QUESTION_UI: Record<QuestionType, IndicatorUi> = {
  open: { word: "Open", glyph: "○", tone: "blue", hint: "Invites the guest to explain in their own terms." },
  closed: { word: "Closed", glyph: "□", tone: "blue", hint: "A yes/no or single-fact question." },
  leading: { word: "Leading", glyph: "↪", tone: "amber", hint: "The wording steers toward the answer wanted." },
  softball: { word: "Softball", glyph: "◔", tone: "amber", hint: "An easy question that invites praise or self-description." },
  challenging: { word: "Pushback", glyph: "!", tone: "blue", hint: "Puts a criticism, a counter-view or a demand for evidence to the guest." },
  unclear: { word: "Unclear", glyph: "?", tone: "grey", hint: "Can't tell from the words." },
};

export const EVIDENCE_UI = {
  strong: { bars: 2, word: "Strong", hint: "Pages from three or more sites came back for this answer." },
  limited: { bars: 1, word: "Limited", hint: "Pages from one or two sites came back for this answer." },
  none: { bars: 0, word: "None", hint: "No page came back for this answer." },
} as const;

/** The stake tag: the speaker, or an organisation they lead or work for, has an interest in the outcome, or the answer promotes their own company, product or channel. */
export function stakeOf(c: Claim): string | null {
  return c.research?.tags?.stake?.yes ? "The speaker, or an organisation they lead or work for, has an interest in the outcome, or the answer promotes their own company, product or channel." : null;
}

/** The bias tag from the classifier. */
export function biasOf(c: Claim): "balanced" | "leans" | "one_sided" | "cant_tell" | null {
  return c.research?.tags?.bias?.label ?? null;
}

export interface InterviewProfile {
  asked: number; // exchanges with an analysed question
  questions: Record<QuestionType, number>;
  approx: number; // questions tagged from the AI's plain-words version (older videos), where leading wording may be missed
  answered: number; // answers with a correctness label
  answers: Record<CorrectnessLabel, number>;
  stakeAnswers: number;
  pattern: boolean; // see PATTERN
}

/** The profile calls an interview promotional-style only when all three hold, and never from approximate question tags. */
export const PATTERN = { minQuestions: 5, softShare: 0.7, minStakeAnswers: 2 };

const zero = <K extends string>(keys: readonly K[]) => Object.fromEntries(keys.map((k) => [k, 0])) as Record<K, number>;

/** Tallies of how the questions were asked and what the sources show about the answers. Null when nothing was analysed. */
export function interviewProfile(claims: Claim[]): InterviewProfile | null {
  const visible = visibleClaims(claims).filter((c) => c.question).sort((a, b) => a.start_s - b.start_s);
  const questions = zero(["open", "closed", "leading", "softball", "challenging", "unclear"] as const);
  const answers = zero(["supported", "partly", "contradicted", "unverified", "opinion"] as const);
  let asked = 0, answered = 0, stakeAnswers = 0, approx = 0;
  for (const g of groupByQuestion(visible)) {
    const qa = g.answers[0].question_analysis;
    if (qa && !g.implied) { asked++; questions[qa.type]++; if (qa.spoken === false) approx++; }
  }
  for (const c of visible) {
    const k = c.research?.correctness;
    if (k) { answered++; answers[k.label]++; }
    if (stakeOf(c)) stakeAnswers++;
  }
  if (!asked && !answered) return null;
  const soft = questions.leading + questions.softball;
  const pattern = approx === 0 && asked >= PATTERN.minQuestions && soft / asked >= PATTERN.softShare && questions.challenging === 0 && stakeAnswers >= PATTERN.minStakeAnswers;
  return { asked, questions, approx, answered, answers, stakeAnswers, pattern };
}
