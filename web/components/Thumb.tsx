"use client";

import { useState } from "react";

// YouTube's thumbnail sizes, sharpest first. Not every video has the HD ones: a missing size answers 404 (or a
// 120 px placeholder), and the next one is tried.
const HD_SIZES = ["maxresdefault", "sddefault", "hqdefault"];

/** YouTube's own thumbnail, shown as-is (nothing drawn over it, per YouTube API policy). `hd` for large displays. */
export function Thumb({ videoId, title, duration, eager = false, hd = false }: {
  videoId: string; title: string; duration?: string; eager?: boolean; hd?: boolean;
}) {
  const sizes = hd ? HD_SIZES : ["hqdefault"];
  const [at, setAt] = useState(0);
  const failed = at >= sizes.length;
  const next = () => setAt((i) => i + 1);
  return (
    <span className="thumb">
      {!videoId ? (
        <span className="thumb-fallback">YouTube link to be added</span>
      ) : failed ? (
        <span className="thumb-fallback">Video thumbnail unavailable</span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={sizes[at]} src={`https://i.ytimg.com/vi/${videoId}/${sizes[at]}.jpg`} alt={title} loading={eager ? "eager" : "lazy"}
             width={hd ? 1280 : 480} height={hd ? 720 : 270} onError={next}
             onLoad={(e) => { if (hd && e.currentTarget.naturalWidth <= 120) next(); }} />
      )}
      {duration && <span className="thumb-duration">{duration}</span>}
    </span>
  );
}

/** A channel's initial. Channel avatars come from the YouTube API and would have to be refreshed every 30 days; an initial doesn't. */
export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  return <span className="avatar avatar-initial" style={{ width: size, height: size }} aria-hidden="true">{name.slice(0, 1)}</span>;
}
