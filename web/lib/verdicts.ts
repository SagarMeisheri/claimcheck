import type { Pestle, VerdictName } from "./types";

export const VERDICTS: Record<VerdictName, { label: string; meaning: string; cssVar: string }> = {
  supported: { label: "True", meaning: "A reliable source states the same fact.", cssVar: "var(--v-supported)" },
  misleading: { label: "Misleading", meaning: "Close, but the period, base or framing is wrong.", cssVar: "var(--v-misleading)" },
  false: { label: "False", meaning: "The best available source contradicts it. The correction is shown.", cssVar: "var(--v-false)" },
  outdated: { label: "Outdated", meaning: "True once, but the figure or rule has changed.", cssVar: "var(--v-outdated)" },
  disputed: { label: "Disputed data", meaning: "Official and independent sources disagree; both are shown.", cssVar: "var(--v-disputed)" },
  unverifiable: { label: "Unverifiable", meaning: "The sources don't settle it. The reason is given.", cssVar: "var(--v-unverifiable)" },
};

/** "True · 92/100" style label for a verdict word with its score. */
export function scoreLabel(score: number | null | undefined): string | null {
  return score === null || score === undefined ? null : `${score}/100`;
}

export const VERDICT_ORDER: VerdictName[] = ["false", "misleading", "disputed", "outdated", "supported", "unverifiable"];

export const PESTLE: Record<Pestle, string> = {
  political: "Political",
  economic: "Economic",
  social: "Social",
  technological: "Technological",
  legal: "Legal",
  environmental: "Environmental",
};

export const NOT_CHECKED: Record<string, string> = {
  opinion: "opinion",
  prediction: "prediction",
  anecdote: "personal story",
  outside_policy: "outside our content policy",
  not_checkworthy: "too minor to check",
  not_prioritised: "lower priority",
  budget: "stopped by cost limit",
  error: "couldn't be checked",
  analysis: "analysis no public source can confirm",
  own_formula: "the speaker's own formula, not a standard measure",
  private_information: "based on private information",
};

export const TIER_LABEL: Record<number, string> = {
  1: "Official or peer-reviewed source",
  2: "Established news or research organisation",
  3: "Other source",
};

export function clock(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
}

export function ytLink(videoId: string, s: number): string {
  return `https://www.youtube.com/watch?v=${videoId}&t=${s}s`;
}

export function domain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function tallyTotal(t: Partial<Record<VerdictName, number>>): number {
  return Object.values(t).reduce((a, b) => a + (b || 0), 0);
}

const TOPIC_LABELS: Record<string, string> = {
  gdp: "GDP", welfare_schemes: "Welfare schemes", foreign_policy: "Foreign policy", real_estate: "Real estate",
  illicit_economy: "Illicit economy", air_pollution: "Air pollution", rare_earths: "Rare earths and minerals",
};

/** A stable soft colour (hue in degrees) per topic, so the same topic always has the same tint. */
export function topicHue(key: string): number {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return [210, 150, 30, 280, 340, 175, 50, 250][h % 8];
}

export function topicLabel(key: string): string {
  if (TOPIC_LABELS[key]) return TOPIC_LABELS[key];
  const s = key.replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) { const d = Math.round(s / 86400); return d === 1 ? "1 day ago" : `${d} days ago`; }
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
