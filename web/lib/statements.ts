import type { SourcesStatus, StatementType } from "./types";

/** Statement types, in the order filter chips and breakdowns show them. */
export const STATEMENT_TYPES: Record<StatementType, { label: string; one: string; plural: string; meaning: string; cssVar: string }> = {
  factual_claim: { one: "claim", label: "Claim", plural: "claims", meaning: "A statement about the past or present that sources could address. Tagged by AI; not judged true or false.", cssVar: "var(--t-factual)" },
  opinion: { one: "opinion", label: "Opinion", plural: "opinions", meaning: "A view or value judgement.", cssVar: "var(--t-opinion)" },
  forecast: { one: "forecast", label: "Forecast", plural: "forecasts", meaning: "A statement about the future.", cssVar: "var(--t-forecast)" },
  advice: { one: "advice", label: "Advice", plural: "advice", meaning: "A recommendation to the listener about what to do.", cssVar: "var(--t-advice)" },
  story: { one: "story", label: "Story", plural: "stories", meaning: "A personal experience or anecdote. No sources to look up.", cssVar: "var(--t-story)" },
  question: { one: "question", label: "Question", plural: "questions", meaning: "A question that moves the conversation. No sources to look up.", cssVar: "var(--t-question)" },
  other: { one: "other", label: "Other", plural: "other", meaning: "A comparison, a reference to what others say, or another remark.", cssVar: "var(--t-other)" },
};

export const TYPE_ORDER: StatementType[] = ["factual_claim", "opinion", "forecast", "advice", "story", "question", "other"];

/** Questions and personal stories assert nothing a source could address: no "Check sources" for them. */
export const NO_SOURCE_TYPES: StatementType[] = ["question", "story"];
export function hasSources(t: string): boolean {
  return !NO_SOURCE_TYPES.includes(t as StatementType);
}

/** Tags from before the four-tag set fold into "other" (the database was migrated too; this covers cached pages). */
export function typeOf(t: string | null | undefined): StatementType {
  return t && t in STATEMENT_TYPES ? (t as StatementType) : "other";
}

export const SEARCHING: SourcesStatus[] = ["queued", "searching"];

/** Whether a "Check sources" button makes sense for this statement right now. */
export function canCheckSources(c: { statement_type: string; sources_status: SourcesStatus; not_checked_reason: string | null }): boolean {
  return hasSources(c.statement_type) && c.not_checked_reason !== "outside_policy"
    && (c.sources_status === "not_requested" || c.sources_status === "failed");
}

/** "42 statements: 9 claims, 14 opinions, ..." */
export function breakdownParts(counts: Partial<Record<StatementType, number>>): string[] {
  const merged = mergeCounts(counts);
  return TYPE_ORDER.filter((t) => merged[t]).map((t) => `${merged[t]} ${merged[t] === 1 ? STATEMENT_TYPES[t].one : STATEMENT_TYPES[t].plural}`);
}

export function totalStatements(counts: Partial<Record<StatementType, number>>): number {
  return Object.values(counts).reduce((a, b) => a + (b || 0), 0);
}

/** Counts keyed by any stored type, folded into the four tags. */
export function mergeCounts(counts: Record<string, number | undefined>): Partial<Record<StatementType, number>> {
  const out: Partial<Record<StatementType, number>> = {};
  for (const [k, n] of Object.entries(counts)) out[typeOf(k)] = (out[typeOf(k)] ?? 0) + (n ?? 0);
  return out;
}
