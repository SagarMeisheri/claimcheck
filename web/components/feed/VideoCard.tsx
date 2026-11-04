"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Avatar, Thumb } from "@/components/Thumb";
import { CheckProgress } from "@/components/CheckProgress";
import { CheckAllSources } from "@/components/CheckAllSources";
import { CheckedAt } from "@/components/CheckedAt";
import { YouTubePlayer, type PlayerHandle } from "@/components/watch/YouTubePlayer";
import type { Episode, PreviewClaim } from "@/lib/types";
import { breakdownParts, canCheckSources, totalStatements } from "@/lib/statements";
import { clock, timeAgo } from "@/lib/format";
import { CreatorPanel, PeoplePanel } from "@/components/watch/ProfileTabs";
import { StatementCarousel } from "./StatementCarousel";

type CardTab = "summary" | "creator" | "speakers";

// Only one card plays at a time: starting a video closes whichever card was playing before.
let closeOther: (() => void) | null = null;

/** Compact video header, AI summary, the breakdown by type, then the video's statements as a carousel.
 *  Clicking the thumbnail or a statement plays the video in place, from the start or from that timestamp. */
export function VideoCard({ ep, eager = false }: { ep: Episode; eager?: boolean }) {
  const checking = ep.status === "processing" || ep.status === "queued";
  const base = `/v/${ep.youtube_video_id}`;
  const total = totalStatements(ep.statement_counts ?? {});

  const player = useRef<PlayerHandle>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [playerOn, setPlayerOn] = useState(false);
  const [start, setStart] = useState(0);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<CardTab>("summary");
  const speakers = ep.speakers ?? [];
  const tabs: { key: CardTab; label: string }[] = [
    { key: "summary", label: checking ? "Progress" : "AI summary" },
    ...(ep.creator ? [{ key: "creator" as CardTab, label: "Creator" }] : []),
    ...(speakers.length ? [{ key: "speakers" as CardTab, label: `People ${speakers.length}` }] : []),
  ];

  const play = (seconds: number, claimId: string | null) => {
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
    // On phones the statement row can be below the fold of the player: bring the player into view.
    window.setTimeout(() => frame.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 80);
  };
  const close = () => { setPlayerOn(false); setActiveId(null); if (closeOther) closeOther = null; };

  return (
    <article className="vcard">
      <div className={`vcard-head${playerOn && !failed ? " is-playing" : ""}`}>
        <div ref={frame} className="vcard-media">
          {playerOn && !failed ? (
            <>
              <div className="vcard-player">
                <YouTubePlayer ref={player} videoId={ep.youtube_video_id} start={start} autoplay onError={() => setFailed(true)} />
              </div>
              <p className="vcard-under">
                <a className="vcard-yt" href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}`} target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a>
                <button type="button" className="vcard-close" onClick={close}>Close video</button>
              </p>
            </>
          ) : (
            <button type="button" className="vcard-thumb vcard-thumb-btn" disabled={checking}
                    onClick={() => play(0, null)} aria-label={`Play ${ep.title}`}>
              <Thumb videoId={ep.youtube_video_id} title={ep.title} duration={ep.duration_s ? clock(ep.duration_s) : undefined} eager={eager} />
              {!checking && <span className="facade-play" aria-hidden="true">▶</span>}
            </button>
          )}
          {failed && <p className="meta">This video isn&apos;t available on YouTube any more.</p>}
        </div>
        <div className="vcard-meta">
          <Link href={base} className="vcard-title">{ep.title}</Link>
          <div className="vcard-channel">
            <Avatar name={ep.channel_name} size={20} />
            {ep.channel_id ? <Link href={`/c/${ep.channel_id}`} className="vcard-channel-name">{ep.channel_name}</Link> : <span>{ep.channel_name}</span>}
          </div>
          <div className="vcard-when">{ep.published_at ? timeAgo(ep.published_at) : ""}</div>
          <div className="vcard-about">
            {tabs.length > 1 && (
              <div className="tabs vcard-tabs" role="tablist" aria-label="About this video">
                {tabs.map((t) => (
                  <button key={t.key} role="tab" className="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
                ))}
              </div>
            )}
            {tab === "summary" && (checking
              ? <CheckProgress videoId={ep.youtube_video_id} compact showSteps initialSteps={ep.progress?.steps ?? []} />
              : ep.summary && <p className="vcard-blurb"><span className="ai-note">AI summary: </span>{ep.summary}</p>)}
            {tab === "creator" && ep.creator && <div className="vcard-panel profile" role="tabpanel"><CreatorPanel creator={ep.creator} /></div>}
            {tab === "speakers" && <div className="vcard-panel" role="tabpanel"><PeoplePanel people={speakers} creator={ep.creator ?? null} /></div>}
          </div>
        </div>
      </div>
      {!checking && (
        <p className="vcard-summary">
          {total ? <><strong>{total} statements</strong>: {breakdownParts(ep.statement_counts).join(", ")}</> : "No statements found."}
          {!!ep.with_sources && <span className="meta">. {ep.with_sources} with sources</span>}
          {ep.sources_checked_at && <span className="meta"> · <CheckedAt iso={ep.sources_checked_at} /></span>}
        </p>
      )}
      {!checking && (
        <CheckAllSources videoId={ep.youtube_video_id} running={ep.sources_batch === "running"} compact
                         eligible={(ep.preview_claims ?? []).some((c) => canCheckSources({ ...c, not_checked_reason: null }))} />
      )}
      {(!checking || (ep.preview_claims?.length ?? 0) > 0) && (
        <StatementCarousel videoId={ep.youtube_video_id} statements={ep.preview_claims ?? []} sections={ep.sections ?? []} withSources={ep.with_sources ?? 0}
                           counts={ep.statement_counts ?? {}} activeId={activeId} onPlay={(c: PreviewClaim) => play(c.start_s, c.id)} />
      )}
    </article>
  );
}
