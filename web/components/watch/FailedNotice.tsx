"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { submitVideo } from "@/app/actions";

/** Shown in place of the progress bar when a video's analysis stopped with an error: says why, and runs it again on request. */
export function FailedNotice({ videoId, reason }: { videoId: string; reason: string | null }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  // Older rows hold the raw error text; never show that.
  const text = reason && !/[{}]|Error:/.test(reason) ? reason : "Something went wrong while reading this video. Try again.";
  const retry = () => start(async () => {
    const form = new FormData();
    form.set("url", `https://www.youtube.com/watch?v=${videoId}`);
    const r = await submitVideo(null, form);
    setMsg(r.ok ? null : r.message);
    router.refresh();
  });
  return (
    <div className="failed-notice" role="alert">
      <p><strong>This video couldn&apos;t be analysed.</strong> {text}</p>
      <button type="button" className="btn secondary small" onClick={retry} disabled={pending}>{pending ? "Starting…" : "Try again"}</button>
      {msg && <p className="meta" role="status">{msg}</p>}
    </div>
  );
}
