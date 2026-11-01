"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { requestVerification } from "@/app/actions";
import type { VerificationStatus } from "@/lib/types";
import { VERIFYING } from "@/lib/statements";

const POLL_MS = 4000;

/**
 * Verify button for one factual claim. Pressing it asks the pipeline to verify just this claim; the
 * verdict is saved for everyone. While it runs the button shows progress and polls the claim's status,
 * then refreshes the page to show the verdict (or "With a reviewer" for verdicts that need sign-off).
 */
export function VerifyButton({ claimId, status: initial, error: initialError }: {
  claimId: string; status: VerificationStatus; error: string | null;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<VerificationStatus>(initial);
  const [message, setMessage] = useState<string | null>(initialError);
  const [pending, start] = useTransition();
  const running = VERIFYING.includes(status);

  useEffect(() => { setStatus(initial); setMessage(initialError); }, [initial, initialError]);

  useEffect(() => {
    if (!running) return;
    let stop = false;
    const id = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/claims/${claimId}/status`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const j = (await r.json()) as { status: VerificationStatus; error: string | null };
        if (!VERIFYING.includes(j.status)) {
          stop = true;
          window.clearInterval(id);
          setStatus(j.status);
          setMessage(j.error);
          router.refresh();
        }
      } catch { /* try again next tick */ }
    }, POLL_MS);
    return () => { stop = true; window.clearInterval(id); };
  }, [running, claimId, router]);

  const verify = () => start(async () => {
    const r = await requestVerification(claimId);
    if (r.status) setStatus(r.status);
    setMessage(r.status && VERIFYING.includes(r.status) ? null : r.message);
    if (r.status === "verified" || r.status === "awaiting_review") router.refresh();
  });

  if (running) {
    return (
      <p className="verify-state" role="status">
        <span className="spinner" aria-hidden="true" /> {status === "queued" ? "Queued for verification" : "Verifying against official sources"}…
        <span className="meta"> usually a minute or two</span>
      </p>
    );
  }
  if (status === "awaiting_review") {
    return <p className="verify-state" role="status"><span className="pending-word">Verified, with a reviewer</span></p>;
  }
  return (
    <div className="verify-row">
      <button className="btn small verify-btn" onClick={verify} disabled={pending}>
        {pending ? "Sending…" : status === "failed" ? "Try verifying again" : "Verify this claim"}
      </button>
      {message && <span className="meta verify-msg" role="status">{message}</span>}
    </div>
  );
}
