"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Status = { status: string; skip_reason: string | null; label: string | null; pct: number };
const RUNNING = ["queued", "processing"];

/** Progress bar for a video being checked. Polls every 3 s and refreshes the page when the check ends. */
export function CheckProgress({ videoId, compact = false }: { videoId: string; compact?: boolean }) {
  const router = useRouter();
  const [s, setS] = useState<Status | null>(null);

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const r = await fetch(`/api/progress/${videoId}`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as Status;
        setS(j);
        if (!RUNNING.includes(j.status)) { stop = true; window.clearInterval(id); router.refresh(); }
      } catch { /* keep the last state; try again next tick */ }
    }
    const id = window.setInterval(tick, 3000);
    tick();
    return () => { stop = true; window.clearInterval(id); };
  }, [videoId, router]);

  const pct = s?.pct ?? 0;
  const label = s?.status === "queued" || !s?.label ? "Waiting to start" : s.label;
  return (
    <div className={`cprogress${compact ? " compact" : ""}`}>
      <div className="cprogress-top">
        <span>{label}</span>
        <span className="meta">{pct}%</span>
      </div>
      <div className="cprogress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
        <span style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
      {!compact && <p className="meta">Usually 10 to 30 minutes. This updates on its own.</p>}
    </div>
  );
}
