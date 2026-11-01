"use client";

import { useEffect, useState, useTransition } from "react";
import { requestVerification } from "@/app/actions";
import type { ClaimOutcome, VerificationStatus } from "@/lib/types";
import { VERIFYING } from "@/lib/statements";

const POLL_MS = 3000;

export type InlineResult = { status: VerificationStatus; outcome: ClaimOutcome | null };

/**
 * Verify button for the home-page carousel. Pressing it queues the claim, shows a loader while the
 * pipeline searches (up to 3 searches at once), polls the claim's status, and hands the finished verdict
 * to the card so it can colour itself. Verdicts that need a reviewer come back with no outcome.
 */
export function InlineVerify({ claimId, status: initial, onBusy, onDone }: {
  claimId: string; status: VerificationStatus; onBusy(busy: boolean): void; onDone(r: InlineResult): void;
}) {
  const [status, setStatus] = useState<VerificationStatus>(initial);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const running = VERIFYING.includes(status);

  useEffect(() => { onBusy(running); }, [running, onBusy]);

  useEffect(() => {
    if (!running) return;
    let stop = false;
    const id = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/claims/${claimId}/status`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as { status: VerificationStatus; error: string | null; outcome: ClaimOutcome | null };
        if (VERIFYING.includes(j.status)) return;
        stop = true;
        window.clearInterval(id);
        setStatus(j.status);
        setMessage(j.error);
        if (j.status === "verified" || j.status === "awaiting_review") onDone({ status: j.status, outcome: j.outcome });
      } catch { /* try again next tick */ }
    }, POLL_MS);
    return () => { stop = true; window.clearInterval(id); };
  }, [running, claimId, onDone]);

  const verify = () => start(async () => {
    const r = await requestVerification(claimId);
    if (r.status) setStatus(r.status);
    setMessage(r.status && VERIFYING.includes(r.status) ? null : r.message);
    if (r.status === "verified" || r.status === "awaiting_review") {
      const j = await fetch(`/api/claims/${claimId}/status`, { cache: "no-store" }).then((x) => x.json()).catch(() => null);
      onDone({ status: r.status, outcome: j?.outcome ?? null });
    }
  });

  if (running || pending) {
    return (
      <p className="ccard-verifying" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        {status === "queued" || pending ? "Queued…" : "Checking sources…"}
      </p>
    );
  }
  return (
    <div className="ccard-verify">
      <button type="button" className="btn small" onClick={verify}>Verify</button>
      {message && <span className="meta ccard-verify-msg" role="status">{message}</span>}
    </div>
  );
}
