import type { Claim, Source } from "./types";
import { topicLabel } from "./format";

/** Statements the notes page may show: never the ones the content policy redacted. */
export function visibleClaims(claims: Claim[]): Claim[] {
  return claims.filter((c) => c.not_checked_reason !== "outside_policy" && c.policy_tier !== "never");
}

/** The same page reached through different tracking or query strings is one source. */
function sourceKey(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname.replace(/^www\./, "")}${u.pathname.replace(/\/+$/, "")}`.toLowerCase();
  } catch {
    return url;
  }
}

/** Sources with repeats removed (same page, different query string), keeping the search's order. */
export function dedupeSources(sources: Source[]): Source[] {
  const seen = new Set<string>();
  return sources.filter((s) => {
    const k = sourceKey(s.url);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export type TopicGroup = { key: string; label: string; claims: Claim[] };

const MIN_GROUP = 2;

/**
 * Statements with sources, grouped by their first subject tag and listed in the order said. Subjects with a single
 * statement are folded into "Other points" so the page doesn't become a list of one-item sections.
 */
export function groupByTopic(claims: Claim[]): TopicGroup[] {
  const withSources = claims.filter((c) => c.sources.length > 0).sort((a, b) => a.start_s - b.start_s);
  const byKey = new Map<string, Claim[]>();
  for (const c of withSources) {
    const key = c.topics[0] ?? c.topic ?? "other";
    byKey.set(key, [...(byKey.get(key) ?? []), c]);
  }
  const groups: TopicGroup[] = [];
  const rest: Claim[] = [];
  for (const [key, list] of byKey) {
    if (list.length >= MIN_GROUP) groups.push({ key, label: topicLabel(key), claims: list });
    else rest.push(...list);
  }
  groups.sort((a, b) => b.claims.length - a.claims.length || a.claims[0].start_s - b.claims[0].start_s);
  if (rest.length) groups.push({ key: "other-points", label: "Other points", claims: rest.sort((a, b) => a.start_s - b.start_s) });
  return groups;
}

/** ISO 8601 duration ("PT19M13S") for structured data. */
export function isoDuration(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `PT${h ? `${h}H` : ""}${m ? `${m}M` : ""}${s || (!h && !m) ? `${s}S` : ""}`;
}

export function trim(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, max).replace(/\s+\S*$/, "")}…`;
}
