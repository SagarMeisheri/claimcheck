"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Step } from "@/lib/types";

type Status = { status: string; skip_reason: string | null; label: string | null; pct: number; statements: number; steps?: Step[] };
const RUNNING = ["queued", "processing"];
const ICON: Record<Step["status"], string> = { done: "✓", running: "", pending: "", skipped: "–" };
const SR: Record<Step["status"], string> = { done: "Done", running: "In progress", pending: "Waiting", skipped: "Skipped" };

/**
 * Progress for a video being analysed: a bar, and the list of steps with the ones already done ticked, the current
 * one spinning and the rest waiting. Polls every 3 s and refreshes the page when the analysis ends.
 */
export function CheckProgress({ videoId, compact = false, initialSteps = [] }: { videoId: string; compact?: boolean; initialSteps?: Step[] }) {
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
  const steps = s?.steps?.length ? s.steps : initialSteps;
  return (
    <div className={`cprogress${compact ? " compact" : ""}`}>
      <div className="cprogress-top">
        <span><span className="spinner" aria-hidden="true" /> {label}</span>
        <span className="meta">{pct}%</span>
      </div>
      <div className="cprogress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
        <span style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
      {!compact && steps.length > 0 && (
        <ol className="steps" aria-label="Analysis steps">
          {steps.map((st) => (
            <li key={st.key} className={`step is-${st.status}`}>
              <span className="step-icon" aria-hidden="true">{st.status === "running" ? <span className="spinner" /> : ICON[st.status]}</span>
              <span className="step-body">
                <span className="step-label">{st.label}<span className="sr-only"> ({SR[st.status]})</span></span>
                {st.status === "running" && s?.label && s.label !== st.label
                  ? <span className="meta step-detail">{s.label}</span>
                  : st.detail ? <span className="meta step-detail">{st.detail}</span> : null}
              </span>
            </li>
          ))}
        </ol>
      )}
      {!compact && <p className="meta">Statements appear as they are found. This updates on its own.</p>}
    </div>
  );
}
