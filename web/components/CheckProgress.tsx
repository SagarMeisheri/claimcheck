"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

type Status = { status: string; skip_reason: string | null; label: string | null; pct: number; statements: number };
const RUNNING = ["queued", "processing"];

/** Progress bar for a video being checked. Polls every 3 s and refreshes the page when the check ends. */
export function CheckProgress({ videoId, compact = false }: { videoId: string; compact?: boolean }) {
  const router = useRouter();
  const [s, setS] = useState<Status | null>(null);
  const seen = useRef(0);

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const r = await fetch(`/api/progress/${videoId}`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as Status;
        setS(j);
        // New statements were saved since the last look: refresh the page so they show up while the check runs.
        if (j.statements > seen.current) { seen.current = j.statements; router.refresh(); }
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
        <span><span className="spinner" aria-hidden="true" /> {label}</span>
        <span className="meta">{pct}%</span>
      </div>
      <div className="cprogress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
        <span style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
      {!compact && <p className="meta">Statements appear as they are found. This updates on its own.</p>}
    </div>
  );
}
