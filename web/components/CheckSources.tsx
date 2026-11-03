"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { requestSources } from "@/app/actions";
import type { Source, SourcesStatus } from "@/lib/types";
import { SEARCHING } from "@/lib/statements";
import { SourceList } from "./SourceList";

const POLL_MS = 3000;
const NONE: Source[] = []; // stable default: a fresh [] each render would re-run the sync effect forever

/**
 * "Check sources" for one claim. Pressing it asks the pipeline to look up sources (saved for everyone). While it runs
 * the button shows progress and polls the claim; when done it shows the sources in place.
 *
 * full: the video page (shows the whole list). compact: the home carousel (shows the first source).
 */
export function CheckSources({ claimId, status: initial, error: initialError, sources: initialSources = NONE, compact = false, onBusy }: {
  claimId: string; status: SourcesStatus; error: string | null; sources?: Source[]; compact?: boolean; onBusy?(busy: boolean): void;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<SourcesStatus>(initial);
  const [message, setMessage] = useState<string | null>(initialError);
  const [sources, setSources] = useState<Source[]>(initialSources);
  const [pending, start] = useTransition();
  const running = SEARCHING.includes(status);

  useEffect(() => { setStatus(initial); setMessage(initialError); setSources(initialSources); }, [initial, initialError, initialSources]);
  useEffect(() => { onBusy?.(running || pending); }, [running, pending, onBusy]);

  useEffect(() => {
    if (!running) return;
    let stop = false;
    const id = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/claims/${claimId}/sources`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as { status: SourcesStatus; error: string | null; sources: Source[] };
        if (SEARCHING.includes(j.status)) return;
        stop = true;
        window.clearInterval(id);
        setStatus(j.status);
        setMessage(j.error);
        setSources(j.sources ?? []);
        if (!compact) router.refresh();
      } catch { /* try again next tick */ }
    }, POLL_MS);
    return () => { stop = true; window.clearInterval(id); };
  }, [running, claimId, compact, router]);

  const go = () => start(async () => {
    const r = await requestSources(claimId);
    if (r.status) setStatus(r.status);
    setMessage(r.status && SEARCHING.includes(r.status) ? null : r.message);
    if (r.status === "done") {
      const j = await fetch(`/api/claims/${claimId}/sources`, { cache: "no-store" }).then((x) => x.json()).catch(() => null);
      setSources(j?.sources ?? []);
    }
  });

  if (status === "done") return <SourceList sources={sources} compact={compact} />;
  if (running || pending) {
    return (
      <p className={compact ? "ccard-verifying" : "verify-state"} role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" /> {status === "queued" || pending ? "Queued…" : "Searching sources…"}
        {!compact && <span className="meta"> usually a few seconds</span>}
      </p>
    );
  }
  return (
    <div className={compact ? "ccard-verify" : "verify-row"}>
      <button type="button" className={`btn small${compact ? "" : " verify-btn"}`} onClick={go}>
        {status === "failed" ? "Try again" : "Check sources"}
      </button>
      {message && <span className="meta verify-msg" role="status">{message}</span>}
    </div>
  );
}
