"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { requestSources } from "@/app/actions";
import type { Source, SourcesMatch, SourcesRoute, SourcesStatus } from "@/lib/types";
import { SEARCHING } from "@/lib/statements";
import { SourceList } from "./SourceList";

const POLL_MS = 3000;
const NONE: Source[] = []; // stable default: a fresh [] each render would re-run the sync effect forever

/**
 * "Check sources" for one claim. Pressing it asks the pipeline to look up sources (saved for everyone). While it runs
 * the button shows progress and polls the claim; when done it shows the sources in place.
 *
 * full: the video page (summary and the numbered list). compact: the home carousel (summary and numbered site links).
 */
type Result = { status: SourcesStatus; error: string | null; sources: Source[]; summary: string | null; match: SourcesMatch | null;
  counter?: Source[]; counter_summary?: string | null; route?: SourcesRoute | null };

export function CheckSources({ claimId, status: initial, error: initialError, sources: initialSources = NONE, summary: initialSummary = null,
  match: initialMatch = null, counter: initialCounter = NONE, counterSummary: initialCounterSummary = null, route: initialRoute = null,
  compact = false, onBusy }: {
  claimId: string; status: SourcesStatus; error: string | null; sources?: Source[]; summary?: string | null;
  match?: SourcesMatch | null; counter?: Source[]; counterSummary?: string | null; route?: SourcesRoute | null; compact?: boolean;
  onBusy?(busy: boolean): void;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<SourcesStatus>(initial);
  const [message, setMessage] = useState<string | null>(initialError);
  const [sources, setSources] = useState<Source[]>(initialSources);
  const [summary, setSummary] = useState<string | null>(initialSummary);
  const [match, setMatch] = useState<SourcesMatch | null>(initialMatch);
  const [counter, setCounter] = useState<Source[]>(initialCounter);
  const [counterSummary, setCounterSummary] = useState<string | null>(initialCounterSummary);
  const [route, setRoute] = useState<SourcesRoute | null>(initialRoute);
  const apply = (j: Result | null) => {
    setSources(j?.sources ?? []); setSummary(j?.summary ?? null); setMatch(j?.match ?? null);
    setCounter(j?.counter ?? []); setCounterSummary(j?.counter_summary ?? null); setRoute(j?.route ?? null);
  };
  const [pending, start] = useTransition();
  const running = SEARCHING.includes(status);

  useEffect(() => {
    setStatus(initial); setMessage(initialError); setSources(initialSources); setSummary(initialSummary); setMatch(initialMatch);
    setCounter(initialCounter); setCounterSummary(initialCounterSummary); setRoute(initialRoute);
  }, [initial, initialError, initialSources, initialSummary, initialMatch, initialCounter, initialCounterSummary, initialRoute]);
  useEffect(() => { onBusy?.(running || pending); }, [running, pending, onBusy]);

  useEffect(() => {
    if (!running) return;
    let stop = false;
    const id = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/claims/${claimId}/sources`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as Result;
        if (SEARCHING.includes(j.status)) return;
        stop = true;
        window.clearInterval(id);
        setStatus(j.status);
        setMessage(j.error);
        apply(j);
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
      apply(j);
    }
  });

  if (status === "done") {
    return <SourceList sources={sources} summary={summary} match={match} counter={counter} counterSummary={counterSummary} route={route} compact={compact} />;
  }
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
      {!message && route === "skip" && (
        <span className="meta verify-msg">Not looked up automatically: it reads as background or the speaker on themselves.</span>
      )}
    </div>
  );
}
