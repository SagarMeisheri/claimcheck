"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";
import { previewVideo, submitVideo, type ActionResult, type Preview } from "@/app/actions";
import { Thumb } from "@/components/Thumb";
import { STATEMENT_TYPES, TYPE_ORDER } from "@/lib/statements";
import { parseVideoId } from "@/lib/youtube";

/**
 * The home page's link box. A valid link shows the video so people can confirm it; submitting queues the analysis
 * (or finds the existing one) and opens the video's page, which then shows up in the sidebar.
 */
export function UrlForm() {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionResult | null, FormData>(submitVideo, null);
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [settled, setSettled] = useState(""); // the last link the person stopped typing on
  const valid = parseVideoId(url) !== null;

  useEffect(() => {
    setPreview(null);
    if (!url.trim() || !valid) { const t = window.setTimeout(() => setSettled(url), 600); return () => window.clearTimeout(t); }
    let stale = false;
    const t = window.setTimeout(async () => {
      const p = await previewVideo(url).catch(() => null);
      if (!stale) setPreview(p);
    }, 350);
    return () => { stale = true; window.clearTimeout(t); };
  }, [url, valid]);

  useEffect(() => {
    if (state?.ok && state.videoId) router.push(`/v/${state.videoId}`);
  }, [state, router]);

  const opening = pending || (state?.ok && !!state.videoId);
  const label = opening ? "Opening…" : preview?.alreadyDone ? "Open" : "Analyse";

  return (
    <form action={action} className="urlform">
      <label htmlFor="url" className="visually-hidden">YouTube link</label>
      <div className="urlform-box">
        <input id="url" name="url" type="url" required inputMode="url" autoComplete="off" autoFocus value={url}
               onChange={(e) => setUrl(e.target.value)} placeholder="Paste a YouTube link" aria-describedby="url-help" />
        <button className="btn" disabled={opening || !valid}>
          {opening && <span className="spinner" aria-hidden="true" />} {label}
        </button>
        <span className="urlform-strip" aria-hidden="true">
          {TYPE_ORDER.map((t) => <span key={t} style={{ background: STATEMENT_TYPES[t].cssVar }} />)}
        </span>
      </div>

      {url.trim() && !valid && settled === url && (
        <p className="notice err" role="status">That isn&apos;t a YouTube video link. Paste a link like youtube.com/watch?v=… or youtu.be/…</p>
      )}
      {state && !state.ok && <p className="notice err" role="status">{state.message}</p>}

      {preview ? (
        <div className="urlform-preview">
          <Thumb videoId={preview.videoId} title={preview.title ?? "YouTube video"} />
          <div>
            <p className="preview-title">{preview.title ?? "YouTube video"}</p>
            {preview.channel && <p className="meta">{preview.channel}</p>}
            <p className="meta">{preview.alreadyDone ? "Already analysed. Open it to see its statements." : "Not analysed yet. Long videos take a few minutes."}</p>
          </div>
        </div>
      ) : (
        <p id="url-help" className="urlform-help">
          Any public YouTube video that has finished (not live). Up to 5 new videos a day.
        </p>
      )}
    </form>
  );
}
