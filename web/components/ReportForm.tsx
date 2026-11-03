"use client";

import { useActionState, useState } from "react";
import { sendReport, type ActionResult } from "@/app/actions";
import type { ReportKind } from "@/lib/types";

const KINDS: { value: ReportKind; label: string }[] = [
  { value: "wrong_quote", label: "The words aren't what was said" },
  { value: "wrong_speaker", label: "Wrong speaker" },
  { value: "wrong_tag", label: "Wrong tag (claim, opinion, forecast, other)" },
  { value: "wrong_time", label: "Wrong timestamp" },
  { value: "bad_source", label: "A source is wrong or irrelevant" },
  { value: "other", label: "Something else (including a legal concern)" },
];

/** "Report a problem" on any statement. Reports go to the reviewer queue. */
export function ReportForm({ claimId, hasSources = false }: { claimId: string; hasSources?: boolean }) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<ActionResult | null, FormData>(sendReport, null);
  if (state?.ok) return <p className="notice ok report-done">Thanks. Someone will look at this.</p>;
  if (!open) {
    return <button type="button" className="linkish report-open" onClick={() => setOpen(true)}>Report a problem</button>;
  }
  return (
    <form action={action} className="report-form">
      <input type="hidden" name="claim_id" value={claimId} />
      <div className="field">
        <label htmlFor={`rk-${claimId}`}>What&apos;s wrong?</label>
        <select id={`rk-${claimId}`} name="kind" defaultValue="wrong_quote">
          {KINDS.filter((k) => hasSources || k.value !== "bad_source").map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`rn-${claimId}`}>Details</label>
        <textarea id={`rn-${claimId}`} name="note" rows={3} maxLength={2000} required />
      </div>
      {state && !state.ok && <p className="notice err">{state.message}</p>}
      <div className="row">
        <button className="btn small" disabled={pending}>{pending ? "Sending…" : "Send report"}</button>
        <button type="button" className="btn secondary small" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}
