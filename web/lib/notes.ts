import type { Claim, Source } from "./types";

/** Statements the Q&A page may show: never the ones the content policy redacted. */
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

export function trim(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, max).replace(/\s+\S*$/, "")}…`;
}
