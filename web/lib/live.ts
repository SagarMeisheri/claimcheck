import { ANSWER_UI, CLAIM_UI, GROUNDING_UI } from "./indicators";
import { SEARCHING } from "./statements";
import type { Claim, QaTags, Research, SourcesRoute, SourcesStatus } from "./types";

/**
 * A source lookup in flight, as the page hears about it. The pipeline saves what a lookup has found at each stage (tags, the points the
 * planner is writing, the queries, the pages as each search returns, the verdict) and the database sends every update here, so a card
 * fills in while the lookup runs. These are the pure parts: what a row carries, how it lays over a claim, and the one line a card shows.
 */

/** What an update of a claim row carries about its lookup. Fields a row did not carry are left out. */
export interface LivePatch {
  sources_status: SourcesStatus;
  sources_error?: string | null;
  qa_tags?: QaTags | null;
  research?: Research | null;
  sources_route?: SourcesRoute | null;
}

export const inFlight = (s: SourcesStatus | undefined | null): boolean => !!s && SEARCHING.includes(s);

/** A claims row (a Realtime update, or a row from /api/live) as a patch; null when it is not a claim row with a lookup status. */
export function patchOf(row: Record<string, unknown> | null | undefined): LivePatch | null {
  const status = row?.sources_status as SourcesStatus | undefined;
  if (!row || typeof status !== "string") return null;
  const p: LivePatch = { sources_status: status };
  // A column the database left out (a large value that did not change) is absent, not null: keep what was known.
  if (row.sources_error !== undefined) p.sources_error = row.sources_error as string | null;
  if (row.qa_tags !== undefined) p.qa_tags = row.qa_tags as QaTags | null;
  if (row.research !== undefined) p.research = row.research as Research | null;
  if (row.sources_route !== undefined) p.sources_route = row.sources_route as SourcesRoute | null;
  return p;
}

/** The latest update laid over what was known. A lookup that has just started begins again: nothing is kept from the one before. */
export function mergePatch(prev: LivePatch | undefined, next: LivePatch): LivePatch {
  if (!prev || !inFlight(prev.sources_status) || !inFlight(next.sources_status)) return next;
  return { ...prev, ...next };
}

/** The claim as it stands while its lookup runs. A finished lookup is not laid over: its sources are not in the row, the page fetches them. */
export function applyLive(c: Claim, p: LivePatch | undefined): Claim {
  if (!p) return c;
  if (inFlight(p.sources_status)) {
    return { ...c, sources_status: p.sources_status, sources_error: null, qa_tags: p.qa_tags ?? c.qa_tags, research: p.research ?? c.research,
      sources_route: p.sources_route ?? c.sources_route };
  }
  if (p.sources_status === "failed" || p.sources_status === "not_requested") return { ...c, sources_status: p.sources_status, sources_error: p.sources_error ?? null };
  return c;
}

export interface LiveLine {
  /** Which step it is on; changes when the step does (screen readers hear that, not every piece of text). */
  stage: "waiting" | "tagged" | "planning" | "searching" | "reading" | "weighing" | "verdict";
  label: string;
  detail: string;
}

const unique = (xs: string[]): string[] => [...new Set(xs.filter(Boolean))];
const pages = (n: number) => `${n} ${n === 1 ? "page" : "pages"}`;

/** The one line a card shows while its lookup runs: the step, and what that step has found so far. */
export function liveLine(c: Claim): LiveLine {
  const r = c.research;
  const t = c.qa_tags;
  const n = r?.pages?.length ?? 0;
  const sites = unique((r?.pages ?? []).map((p) => p.site)).slice(0, 4).join(", ");
  switch (r?.stage) {
    case "planning":
      return { stage: "planning", label: "Choosing what to check", detail: (r.points ?? []).map((p) => p.text).join(" · ") };
    case "searching":
      return { stage: "searching", label: "Searching the web", detail: (r.queries ?? []).join(" · ") };
    case "reading":
      return { stage: "reading", label: n ? `Reading ${pages(n)}` : "Searching the web", detail: n ? sites : (r.queries ?? []).join(" · ") };
    case "grounding": {
      const g = t?.grounding?.label;
      if (g) return { stage: "verdict", label: GROUNDING_UI[g].word, detail: g === "contradicted" ? "Writing how the sources differ…" : "Finishing…" };
      return { stage: "weighing", label: `Weighing ${pages(n)} against the answer`, detail: sites };
    }
  }
  // Tags from this lookup have no verdict yet; a tag set with one is from an earlier lookup, not this one.
  if (t && !t.grounding && (t.answer || t.claim)) {
    const words = [t.answer && `${ANSWER_UI[t.answer.type]?.word ?? ""} answer`, t.claim && CLAIM_UI[t.claim.type]?.word].filter(Boolean).join(" · ");
    return { stage: "tagged", label: "Tagged", detail: `${words} · planning the checks` };
  }
  return { stage: "waiting", label: "Checking sources…", detail: "" };
}
