import { visibleClaims } from "./notes";
import type { Claim, Episode, QaEntry } from "./types";

export type QaItem = { q: string; claims: Claim[]; askedBy?: string | null; implied?: boolean };

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/** One question with every answer given to it (a panel gives several). `q` is null for rows saved before answers carried questions. */
export type QaGroup = { q: string | null; askedBy?: string | null; implied?: boolean; answers: Claim[] };

/** Consecutive answers to the same question become one group, in the order given; a row without a question is its own group. */
export function groupByQuestion(items: Claim[]): QaGroup[] {
  const groups: QaGroup[] = [];
  for (const c of items) {
    const last = groups[groups.length - 1];
    if (c.question && last?.q && norm(last.q) === norm(c.question)) last.answers.push(c);
    else groups.push({ q: c.question ?? null, askedBy: c.asked_by, implied: c.question_kind === "implied", answers: [c] });
  }
  return groups;
}

/**
 * The questions and answers of a video. Videos analysed since answers were extracted carry the question on each answer,
 * so the page reads them straight from the rows; answers to the same question (a panel) are grouped. Older videos have
 * written questions in `episodes.qa` that point at their statements. Either way the text shown is read from the current
 * rows, never a copy, and anything redacted by the content policy is left out.
 */
export function resolveQa(entries: QaEntry[] | null | undefined, claims: Claim[]): QaItem[] {
  const visible = visibleClaims(claims);
  const answers = visible.filter((c) => c.question).sort((a, b) => a.start_s - b.start_s);
  if (answers.length > 0) return groupByQuestion(answers).map((g) => ({ q: g.q!, claims: g.answers, askedBy: g.askedBy, implied: g.implied }));
  const byId = new Map(visible.map((c) => [c.id, c]));
  return (entries ?? [])
    .map((e) => ({ q: e.q, claims: e.claim_ids.map((id) => byId.get(id)).filter((c): c is Claim => !!c) }))
    .filter((i) => i.claims.length > 0);
}

/** Whether a finished video has a Q&A page. */
export function hasQa(ep: Pick<Episode, "qa"> & { claims: Claim[] }): boolean {
  return (ep.qa?.length ?? 0) > 0 || ep.claims.some((c) => !!c.question);
}

/** A passage with no question asked starts a few seconds ahead of its answer. */
export const LEAD_S = 3;

/**
 * Where the video starts for an answer: at the asker's first word, so the question is heard before the answer. Videos read since
 * the question's own time was extracted carry it. For older ones (and implied questions) the start is estimated from the length of the
 * question: about two and a half words a second, plus a few seconds for the lead-in.
 */
export function playFromS(c: Pick<Claim, "start_s" | "question" | "question_kind" | "question_start_s">): number {
  if (c.question_start_s != null && c.question_start_s <= c.start_s) return c.question_start_s;
  if (c.question && c.question_kind !== "implied") {
    const words = c.question.trim().split(/\s+/).length;
    return Math.max(0, c.start_s - Math.min(20, Math.max(5, Math.round(words / 2.5) + 4)));
  }
  return Math.max(0, c.start_s - LEAD_S);
}
