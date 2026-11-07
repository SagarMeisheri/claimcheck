import type { Pestle } from "./types";

export const PESTLE: Record<Pestle, string> = {
  political: "Political",
  economic: "Economic",
  social: "Social",
  technological: "Technological",
  legal: "Legal",
  environmental: "Environmental",
};

/** Labels for the kind of site a source comes from. Other sites are shown too, just without a label. */

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
  const s = key.replaceAll("_", " ").replace(/\b(ai|gpu|gpus|ipo|upi|gdp|api|us|uk|eu|nvidia|ev|ml|llm)\b/gi, (w) => (w.toLowerCase() === "nvidia" ? "Nvidia" : w.toUpperCase()));
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) { const d = Math.round(s / 86400); return d === 1 ? "1 day ago" : `${d} days ago`; }
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** "30 May 2026" from a source's publish date, or null when it can't be read. */
export function shortDate(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const t = Date.parse(raw);
  return Number.isNaN(t) ? null : new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
