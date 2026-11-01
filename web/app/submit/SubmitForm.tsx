"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";
import { previewVideo, submitVideo, type ActionResult, type Preview } from "@/app/actions";
import { CheckProgress } from "@/components/CheckProgress";
import { Thumb } from "@/components/Thumb";
import { parseVideoId } from "@/lib/youtube";

/** `inline` = the compact home-page version: it stays on the page and the new video appears in the feed below. */
export function SubmitForm({ inline = false }: { inline?: boolean }) {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionResult | null, FormData>(submitVideo, null);
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [settled, setSettled] = useState("");  // the last link the person stopped typing on
  const valid = parseVideoId(url) !== null;

  // Show the video as soon as a valid link is pasted, so people confirm it's the right one.
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

  // Inline: clear the box and let the feed show the new video with its own progress.
  useEffect(() => {
    if (inline && state?.ok && state.videoId) { setUrl(""); setPreview(null); router.refresh(); }
  }, [inline, state, router]);

  if (!inline && state?.ok && state.videoId) {
    return (
      <div className="notice ok">
        <p>{state.message}</p>
        <CheckProgress videoId={state.videoId} />
        <p><Link href={`/v/${state.videoId}`}>Open the video and its claims</Link></p>
      </div>
    );
  }

  return (
    <form action={action} className={`submit-form${inline ? " inline" : ""}`}>
      {inline && state?.ok && <p className="notice ok" role="status">{state.message} It is in the list below.</p>}
      <div className="field">
        <label htmlFor="url" className={inline ? "visually-hidden" : undefined}>YouTube link</label>
        <input id="url" name="url" type="url" required inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder={inline ? "Paste a YouTube link to check a video" : "https://www.youtube.com/watch?v=…"} aria-describedby="url-help" />
        {!inline && <span id="url-help" className="meta">Public videos, at least 5 minutes long and not live.</span>}
      </div>
      {/* Only when the link really isn't a YouTube video link, and only after the person has stopped typing or pasting. */}
      {url.trim() && !valid && settled === url && <p className="notice err" role="status">That isn&apos;t a YouTube video link. Paste a link like youtube.com/watch?v=… or youtu.be/…</p>}
      {preview && (
        <div className="preview">
          <Thumb videoId={preview.videoId} title={preview.title ?? "YouTube video"} />
          <div>
            <p className="preview-title">{preview.title ?? "YouTube video"}</p>
            {preview.channel && <p className="meta">{preview.channel}</p>}
            {preview.alreadyChecked && <p><Link href={`/v/${preview.videoId}`}>Already checked: open its claims</Link></p>}
          </div>
        </div>
      )}
      {state && !state.ok && <p className="notice err">{state.message}</p>}
      <button className="btn" disabled={pending || !preview || preview.alreadyChecked}>
        {pending ? <><span className="spinner" aria-hidden="true" /> Queuing…</> : "Check this video"}
      </button>
    </form>
  );
}
