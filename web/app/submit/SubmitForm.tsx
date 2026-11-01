"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";
import { previewVideo, submitVideo, type ActionResult, type Preview } from "@/app/actions";
import { CheckProgress } from "@/components/CheckProgress";
import { Thumb } from "@/components/Thumb";

export function SubmitForm() {
  const [state, action, pending] = useActionState<ActionResult | null, FormData>(submitVideo, null);
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [looking, setLooking] = useState(false);

  // Show the video as soon as a valid link is pasted, so people confirm it's the right one.
  useEffect(() => {
    if (!url.trim()) { setPreview(null); return; }
    const id = window.setTimeout(async () => {
      setLooking(true);
      setPreview(await previewVideo(url).catch(() => null));
      setLooking(false);
    }, 350);
    return () => window.clearTimeout(id);
  }, [url]);

  if (state?.ok && state.videoId) {
    return (
      <div className="notice ok">
        <p>{state.message}</p>
        <CheckProgress videoId={state.videoId} />
        <p><Link href={`/v/${state.videoId}`}>Open the video and its claims</Link></p>
      </div>
    );
  }

  return (
    <form action={action} className="submit-form">
      <div className="field">
        <label htmlFor="url">YouTube link</label>
        <input id="url" name="url" type="url" required inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://www.youtube.com/watch?v=…" aria-describedby="url-help" />
        <span id="url-help" className="meta">Public videos, at least 5 minutes long and not live.</span>
      </div>
      {url && !looking && !preview && <p className="notice err">That isn&apos;t a YouTube video link. Paste a link like youtube.com/watch?v=… or youtu.be/…</p>}
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
        {pending ? "Queuing…" : "Check this video"}
      </button>
    </form>
  );
}
