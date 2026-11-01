import type { Metadata } from "next";
import { MiniBar } from "@/components/MiniBar";
import { getBalance } from "@/lib/data";
import { VERDICTS, VERDICT_ORDER, tallyTotal } from "@/lib/verdicts";

export const metadata: Metadata = { title: "Balance" };
export const revalidate = 300;

export default async function BalancePage() {
  const rows = await getBalance();
  const politics = rows.filter((r) => r.track === "politics");
  const sideCount = (s: string) => politics.filter((r) => r.side === s).reduce((a, r) => a + r.episodes, 0);
  const sup = sideCount("supportive"), crit = sideCount("critical"), neu = sideCount("neutral");
  const total = sup + crit + neu || 1;
  return (
    <>
      <h1>Who we check, and how often</h1>
      <p className="lede">
        We check the same number of videos each week from channels that tend to support the government and channels
        that tend to criticise it, using the same rules for both. This page shows the result.
      </p>

      <section>
        <h2>Political videos checked, by the channel&apos;s usual stance</h2>
        <div className="balance-split" role="img"
             aria-label={`Government-supportive ${sup}, government-critical ${crit}, news and neutral ${neu}`}>
          {sup > 0 && <span style={{ flex: sup, background: "var(--v-outdated)" }}>Supportive {sup}</span>}
          {crit > 0 && <span style={{ flex: crit, background: "var(--v-disputed)" }}>Critical {crit}</span>}
          {neu > 0 && <span style={{ flex: neu, background: "var(--v-unverifiable)" }}>News and neutral {neu}</span>}
        </div>
        <p className="meta">
          Supportive and critical channels: {Math.round((sup / total) * 100)}% and {Math.round((crit / total) * 100)}% of
          political videos. Our target is within 45 to 55% of each other.
        </p>
      </section>

      <section>
        <h2>Verdicts by channel</h2>
        <div className="table-scroll"><table>
          <thead>
            <tr><th>Channel</th><th className="num">Videos</th><th className="num">Claims</th><th>Verdict mix</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td className="num">{r.episodes}</td>
                <td className="num">{r.claims_checked}</td>
                <td style={{ minWidth: "8rem" }}>
                  <MiniBar tally={r.tally} />
                  <span className="meta" style={{ fontSize: "0.82rem" }}>
                    {VERDICT_ORDER.filter((v) => r.tally[v]).map((v) => `${Math.round(((r.tally[v] ?? 0) / tallyTotal(r.tally)) * 100)}% ${VERDICTS[v].label.toLowerCase()}`).join(", ")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </section>
    </>
  );
}
