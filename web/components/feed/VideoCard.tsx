"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Avatar, Thumb } from "@/components/Thumb";
import { CheckProgress } from "@/components/CheckProgress";
import { VerdictStrip } from "@/components/MiniBar";
import { YouTubePlayer, type PlayerHandle } from "@/components/watch/YouTubePlayer";
import type { Episode, PreviewClaim } from "@/lib/types";
import { totalStatements } from "@/lib/statements";
import { clock, timeAgo } from "@/lib/verdicts";
import { StatementCarousel } from "./StatementCarousel";

// Only one card plays at a time: starting a video closes whichever card was playing before.
let closeOther: (() => void) | null = null;

/** Compact video header, verdict strip, accuracy-first summary, then the video's claims as a carousel.
 *  Clicking the thumbnail or a claim plays the video in place, from the start or from that claim's timestamp. */
export function VideoCard({ ep, eager = false }: { ep: Episode; eager?: boolean }) {
  const checking = ep.status === "processing" || ep.status === "queued";
  const checked = ep.checked_count ?? 0;
  const supported = ep.tally.supported ?? 0;
  const flagged = (ep.tally.false ?? 0) + (ep.tally.misleading ?? 0) + (ep.tally.disputed ?? 0) + (ep.tally.outdated ?? 0);
  const base = `/v/${ep.youtube_video_id}`;

  const player = useRef<PlayerHandle>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [playerOn, setPlayerOn] = useState(false);
  const [start, setStart] = useState(0);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const play = (seconds: number, claimId: string | null) => {
    if (ep.video_pending) return;
    setActiveId(claimId);
    setFailed(false);
    if (playerOn && player.current?.ready()) {
      player.current.seekTo(seconds, true);
    } else {
      closeOther?.();
      closeOther = () => { setPlayerOn(false); setActiveId(null); };
      setStart(seconds);
      setPlayerOn(true);
    }
    // On phones the claim row can be below the fold of the player: bring the player into view.
    window.setTimeout(() => frame.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 80);
  };
  const close = () => { setPlayerOn(false); setActiveId(null); if (closeOther) closeOther = null; };

  return (
    <article className="vcard">
      <div className="vcard-head">
        <div ref={frame} className="vcard-media">
          {playerOn && !failed ? (
            <>
              <div className="vcard-player">
                <YouTubePlayer ref={player} videoId={ep.youtube_video_id} start={start} autoplay onError={() => setFailed(true)} />
              </div>
              <button type="button" className="vcard-close" onClick={close}>Close video</button>
            </>
          ) : (
            <button type="button" className="vcard-thumb vcard-thumb-btn" disabled={ep.video_pending || checking}
                    onClick={() => play(0, null)} aria-label={`Play ${ep.title}`}>
              <Thumb videoId={ep.video_pending ? "" : ep.youtube_video_id} title={ep.title}
                     duration={ep.duration_s ? clock(ep.duration_s) : undefined} eager={eager} />
              {!ep.video_pending && !checking && <span className="facade-play" aria-hidden="true">▶</span>}
            </button>
          )}
          {failed && <p className="meta">This video isn&apos;t available on YouTube any more.</p>}
        </div>
        <div className="vcard-meta">
          <Link href={base} className="vcard-title">{ep.title}</Link>
          <div className="vcard-channel">
            <Avatar src={ep.channel_avatar} name={ep.channel_name} size={20} />
            {ep.channel_id ? <Link href={`/c/${ep.channel_id}`}>{ep.channel_name}</Link> : <span>{ep.channel_name}</span>}
          </div>
          {ep.guest && <div className="vcard-guest">with {ep.guest}</div>}
          <div className="vcard-when">{ep.published_at ? timeAgo(ep.published_at) : ""}</div>
          {checking
            ? <p className="vcard-blurb"><span className="spinner" aria-hidden="true" /> Reading the video and tagging statements. The title, summary and statements appear as soon as they are ready.</p>
            : ep.summary && <p className="vcard-blurb">{ep.summary}</p>}
        </div>
      </div>
      {checking ? <CheckProgress videoId={ep.youtube_video_id} compact /> : <VerdictStrip tally={ep.tally} checking={false} />}
      <p className="vcard-summary">
        {checking
          ? <Link href="/review#videos">Stop or remove</Link>
          : checked
            ? <><strong>{supported} of {checked} verified claims supported</strong>{flagged ? `, ${flagged} flagged` : ""}</>
            : totalStatements(ep.statement_counts ?? {})
              ? "No claims verified yet. Open the video to verify one."
              : "No checked claims yet."}
        {!!ep.pending_count && <span className="meta">. {ep.pending_count} with a reviewer</span>}
      </p>
      {(!checking || (ep.preview_claims?.length ?? 0) > 0) && (
        <StatementCarousel videoId={ep.youtube_video_id} statements={ep.preview_claims ?? []} verifiedCount={checked}
                           counts={ep.statement_counts ?? {}} videoPending={ep.video_pending}
                           activeId={activeId} onPlay={(c: PreviewClaim) => play(c.start_s, c.id)} />
      )}
    </article>
  );
}
