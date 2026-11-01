import type { StatementType, VerificationStatus } from "./types";

/** Statement types, in the order filter chips and breakdowns show them. */
export const STATEMENT_TYPES: Record<StatementType, { label: string; one: string; plural: string; meaning: string; cssVar: string }> = {
  factual_claim: { one: "claim", label: "Claim", plural: "claims", meaning: "A statement about the past or present that can be checked against sources. Not yet judged true or false.", cssVar: "var(--t-factual)" },
  opinion: { one: "opinion", label: "Opinion", plural: "opinions", meaning: "A value judgement that can't be proven true or false.", cssVar: "var(--t-opinion)" },
  forecast: { one: "forecast", label: "Forecast", plural: "forecasts", meaning: "A prediction. It can't be checked until it happens.", cssVar: "var(--t-forecast)" },
  hearsay: { one: "hearsay", label: "Hearsay", plural: "hearsay", meaning: "Rests on vague or anonymous sources (\"people are saying\").", cssVar: "var(--t-hearsay)" },
  analogy: { one: "analogy", label: "Analogy", plural: "analogies", meaning: "Compares now to a past event to borrow its weight.", cssVar: "var(--t-analogy)" },
  loaded_language: { one: "loaded language", label: "Loaded language", plural: "loaded language", meaning: "Emotionally charged wording doing the work of an argument.", cssVar: "var(--t-loaded)" },
  other: { one: "other", label: "Other", plural: "other", meaning: "A personal story or other statement.", cssVar: "var(--t-other)" },
};

export const TYPE_ORDER: StatementType[] = ["factual_claim", "opinion", "forecast", "hearsay", "analogy", "loaded_language", "other"];
/** Filter chips always shown on the video page, even at zero; the rest appear only when present. */
export const CORE_TYPES: StatementType[] = ["factual_claim", "opinion", "forecast", "hearsay"];

export function typeOf(t: string | null | undefined): StatementType {
  return t && t in STATEMENT_TYPES ? (t as StatementType) : "other";
}

export const VERIFYING: VerificationStatus[] = ["queued", "verifying"];

/** Whether a Verify button makes sense for this claim right now. */
export function canRequestVerify(c: { statement_type: string; verification_status: VerificationStatus; not_checked_reason: string | null }): boolean {
  return c.statement_type === "factual_claim" && c.not_checked_reason !== "outside_policy"
    && (c.verification_status === "not_requested" || c.verification_status === "failed");
}

/** "42 statements: 9 claims, 14 opinions, ..." */
export function breakdownParts(counts: Partial<Record<StatementType, number>>): string[] {
  return TYPE_ORDER.filter((t) => counts[t]).map((t) => `${counts[t]} ${counts[t] === 1 ? STATEMENT_TYPES[t].one : STATEMENT_TYPES[t].plural}`);
}

export function totalStatements(counts: Partial<Record<StatementType, number>>): number {
  return Object.values(counts).reduce((a, b) => a + (b || 0), 0);
}
