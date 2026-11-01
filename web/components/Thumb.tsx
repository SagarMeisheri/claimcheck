"use client";

import { useState } from "react";

/** YouTube's own thumbnail, shown as-is (nothing drawn over it, per YouTube API policy). */
export function Thumb({ videoId, title, duration, eager = false }: { videoId: string; title: string; duration?: string; eager?: boolean }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="thumb">
      {!videoId ? (
        <span className="thumb-fallback">YouTube link to be added</span>
      ) : failed ? (
        <span className="thumb-fallback">Video thumbnail unavailable</span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`} alt={title} loading={eager ? "eager" : "lazy"}
             width={480} height={270} onError={() => setFailed(true)} />
      )}
      {duration && <span className="thumb-duration">{duration}</span>}
    </span>
  );
}

export function Avatar({ src, name, size = 28 }: { src: string | null; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (src && !failed) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="avatar" src={src} alt="" width={size} height={size} onError={() => setFailed(true)} />;
  }
  return <span className="avatar avatar-initial" style={{ width: size, height: size }} aria-hidden="true">{name.slice(0, 1)}</span>;
}
