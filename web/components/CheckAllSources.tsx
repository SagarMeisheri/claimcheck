"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { requestAllSources, stopVideo } from "@/app/actions";

type Live = { batch: string | null; looked_up: number; searching: number; label: string | null; pct: number };

/** A circular progress ring: fills with pct, or spins when the progress isn't known yet. */
function Ring({ pct }: { pct: number | null }) {
  const r = 7, c = 2 * Math.PI * r;
  return (
    <svg className={`ring${pct === null ? " ring-spin" : ""}`} width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <circle cx="9" cy="9" r={r} className="ring-track" />
      <circle cx="9" cy="9" r={r} className="ring-fill" strokeDasharray={c} strokeDashoffset={c * (1 - (pct === null ? 0.28 : pct / 100))} />
    </svg>
  );
}

/**
 * "Check sources for all statements": starts the whole-video lookup. While it runs the button turns into a ring with
 * "Checking sources: 3 of 10", polls the video, and refreshes the page whenever another claim has its sources.
 */
export function CheckAllSources({ videoId, running: initialRunning, eligible, canRecheck = false, onRecheck, compact = false }: {
  videoId: string; running: boolean; eligible: boolean; compact?: boolean;
  /** Some answers already have a result: "Re-check all statements" looks every one up again with the current method. */
  canRecheck?: boolean; onRecheck?(): void;
}) {
  const router = useRouter();
  const [running, setRunning] = useState(initialRunning);
  const [live, setLive] = useState<Live | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const seen = useRef<number | null>(null);

  useEffect(() => setRunning(initialRunning), [initialRunning]);

  useEffect(() => {
    if (!running) return;
    let stop = false;
    async function tick() {
      try {
        const r = await fetch(`/api/progress/${videoId}`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as Live;
        setLive(j);
        if (seen.current !== null && j.looked_up !== seen.current) router.refresh();
        seen.current = j.looked_up;
        if (j.batch !== "running" && j.searching === 0) { stop = true; window.clearInterval(id); setRunning(false); router.refresh(); }
      } catch { /* try again next tick */ }
    }
    const id = window.setInterval(tick, 2500);
    tick();
    return () => { stop = true; window.clearInterval(id); };
  }, [running, videoId, router]);

  const go = (recheck = false) => start(async () => {
    const r = await requestAllSources(videoId, recheck);
    setMessage(r.ok ? null : r.message);
    if (r.ok) { if (recheck) onRecheck?.(); setRunning(true); router.refresh(); }
  });

  const halt = () => start(async () => {
    const r = await stopVideo(videoId);
    setMessage(r.ok ? null : r.message);
    if (r.ok) setRunning(false);
    router.refresh();
  });

  if (running || pending) {
    const pct = live?.pct ?? 0;
    return (
      <p className={`verify-all${compact ? " compact" : ""}`} role="status" aria-live="polite">
        <button type="button" className="btn secondary small verify-all-btn is-running" disabled>
          <Ring pct={live && live.pct > 0 ? pct : null} />
          {live?.label ?? "Starting…"}
        </button>
        <button type="button" className="btn secondary small verify-all-stop" onClick={halt}
                title="Stops checking sources. Answers already checked are kept.">Stop</button>
        {message && <span className="meta verify-all-msg" role="status">{message}</span>}
      </p>
    );
  }
  if (!eligible && !canRecheck) return null;
  return (
    <p className={`verify-all${compact ? " compact" : ""}`}>
      {eligible
        ? <button type="button" className="btn small verify-all-btn" onClick={() => go()}>Check sources for all statements</button>
        : <button type="button" className="btn secondary small verify-all-btn" onClick={() => go(true)}
                  title="Looks every answer up again with the current method. The old results are replaced as the new ones arrive.">Re-check all statements</button>}
      {message && <span className="meta verify-all-msg" role="status">{message}</span>}
    </p>
  );
}
