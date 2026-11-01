import { ImageResponse } from "next/og";
import { getClaimForCard } from "@/lib/data";
import { VERDICTS, clock, domain } from "@/lib/verdicts";

// Fact-card image (1200x630) for sharing a single verdict.
const HEX: Record<string, string> = {
  supported: "#1f7a4d", misleading: "#a86a12", false: "#c2362f", outdated: "#3e6fb0", disputed: "#7b4fa6", unverifiable: "#7a8581",
};

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const found = await getClaimForCard((await params).id);
  if (!found || !found.claim.verdict) return new Response("Not found", { status: 404 });
  const { claim, episode } = found;
  const v = claim.verdict!;
  const color = HEX[v.verdict];
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", background: "#f3f6f4",
                    color: "#17221f", padding: "48px 64px", fontSize: 30 }}>
        <div style={{ display: "flex", fontSize: 26, color: "#4d5a56" }}>
          {episode.channel_name} at {clock(claim.start_s)}
        </div>
        <div style={{ display: "flex", fontSize: v.verdict === "disputed" || claim.claim_text.length > 120 ? 42 : 54, fontWeight: 700, lineHeight: 1.15, marginTop: 24 }}>
          “{claim.claim_text}”
        </div>
        <div style={{ display: "flex", alignItems: "center", marginTop: v.verdict === "disputed" ? 22 : 36 }}>
          <div style={{ width: 28, height: 28, background: color, marginRight: 16 }} />
          <div style={{ display: "flex", fontSize: 44, fontWeight: 700, color }}>{VERDICTS[v.verdict].label}</div>
        </div>
        {(v.verdict === "disputed" ? v.citations.slice(0, 2) : v.citations.slice(0, 1)).map((s) => (
          <div key={s.url} style={{ display: "flex", flexDirection: "column", marginTop: 20, borderLeft: `6px solid ${color}`, paddingLeft: 20 }}>
            <div style={{ display: "flex", fontSize: v.verdict === "disputed" ? 23 : 26 }}>
              {(() => { const q = s.quote.length > 150 ? s.quote.slice(0, 147) + "…" : s.quote; return s.summary ? q : `“${q}”`; })()}
            </div>
            <div style={{ display: "flex", fontSize: 21, color: "#4d5a56", marginTop: 6 }}>{s.title || domain(s.url)}</div>
          </div>
        ))}
        <div style={{ display: "flex", marginTop: "auto", fontSize: 24, color: "#4d5a56", justifyContent: "space-between" }}>
          <span>ClaimCheck</span>
          <span>Full sources and timestamp on the scorecard</span>
        </div>
      </div>
    ),
    { width: 1200, height: 630 },
  );
}
