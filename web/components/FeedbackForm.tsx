"use client";

import { useActionState, useState } from "react";
import { sendFeedback, type ActionResult } from "@/app/actions";
import { VERDICTS } from "@/lib/verdicts";

export function FeedbackForm({ claimId }: { claimId: string }) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<ActionResult | null, FormData>(sendFeedback, null);
  if (state?.ok) return <p className="notice ok">Thanks. A reviewer will look at this verdict.</p>;
  if (!open) {
    return (
      <p style={{ marginTop: "0.6rem" }}>
        <button className="btn secondary" style={{ padding: "0.25rem 0.7rem", fontSize: "0.9rem" }} onClick={() => setOpen(true)}>
          Wrong verdict?
        </button>
      </p>
    );
  }
  return (
    <form action={action} style={{ marginTop: "0.75rem" }}>
      <input type="hidden" name="claim_id" value={claimId} />
      <div className="field">
        <label htmlFor={`sv-${claimId}`}>What should the verdict be?</label>
        <select id={`sv-${claimId}`} name="suggested_verdict" defaultValue="">
          <option value="">Not sure</option>
          {Object.entries(VERDICTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`note-${claimId}`}>Why? A link to a better source helps most.</label>
        <textarea id={`note-${claimId}`} name="note" rows={3} maxLength={2000} required />
      </div>
      {state && !state.ok && <p className="notice err">{state.message}</p>}
      <button className="btn" disabled={pending}>{pending ? "Sending…" : "Send to reviewer"}</button>
    </form>
  );
}
