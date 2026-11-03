"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { VerdictStrip } from "@/components/MiniBar";
import { Avatar, Thumb } from "@/components/Thumb";
import type { Claim, EpisodeDetail, StatementType, VerdictName } from "@/lib/types";
import { CORE_TYPES, STATEMENT_TYPES, TYPE_ORDER, VERIFYING, breakdownParts, typeOf } from "@/lib/statements";
import { VERDICTS, clock, topicHue, topicLabel } from "@/lib/verdicts";
import { CheckProgress } from "@/components/CheckProgress";
import { ClaimCard, StatementCard, type CardPhase } from "./ClaimCard";
import { ClaimTrack } from "./ClaimTrack";
import { YouTubePlayer, type PlayerHandle } from "./YouTubePlayer";

/** Filter chips: every statement, one statement type, or verified claims only. */
export type View = "all" | "verified" | StatementType;
const FLAGGED: VerdictName[] = ["false", "misleading", "disputed", "outdated"];
const CLIP_S = 20;
const LEAD_S = 3;
const CUE_LEAD_S = 5;
const AUTO_NEXT_S = 4;

export function ScorecardView({ ep, initialT, autoplay, momentId, initialView, initialTopic }: {
  ep: EpisodeDetail; initialT: number | null; autoplay: boolean; momentId: string | null; initialView: View | null; initialTopic?: string | null;
}) {
  const router = useRouter();
  const player = useRef<PlayerHandle>(null);
  // "listed" = verified claims (public verdict or with a reviewer); everything else is a tagged statement.
  const listed = useMemo(() => ep.claims.filter((c) => c.verdict || c.awaiting_review).sort((a, b) => a.start_s - b.start_s), [ep.claims]);
  const everything = useMemo(() => [...ep.claims].sort((a, b) => a.start_s - b.start_s), [ep.claims]);
  const typeCounts = useMemo(() => {
    const t: Partial<Record<StatementType, number>> = {};
    for (const c of ep.claims) { const k = typeOf(c.statement_type); t[k] = (t[k] ?? 0) + 1; }
    return t;
  }, [ep.claims]);
  const verifyingCount = ep.claims.filter((c) => VERIFYING.includes(c.verification_status)).length;
  const checking = ep.status === "processing" || ep.status === "queued";

  const [view, setView] = useState<View>(initialView ?? "all");
  const [topic, setTopic] = useState<string | null>(initialTopic ?? null);
  const [playerOn, setPlayerOn] = useState(false);
  const [startPlaying, setStartPlaying] = useState(false);
  const [cue, setCue] = useState(initialT ?? 0);
  const [time, setTime] = useState(initialT ?? 0);
  const [playing, setPlaying] = useState(false);
  const [playerError, setPlayerError] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [clip, setClip] = useState<{ id: string; end: number; phase: CardPhase } | null>(null);
  const [following, setFollowing] = useState(false); // "Keep watching": highlight claims as the video passes them
  const [scrollFollow, setScrollFollow] = useState(true);
  const [autoAll, setAutoAll] = useState(false); // "Play flagged in order"
  const [countdown, setCountdown] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const byView = view === "all" ? everything : view === "verified" ? listed : everything.filter((c) => typeOf(c.statement_type) === view);
  // Subject chips: tags in the current type view, most common first. A chosen tag stays visible even at zero.
  const topicCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of byView) for (const t of c.topics ?? []) m.set(t, (m.get(t) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [byView]);
  const allTopicCount = useMemo(() => new Set(ep.claims.flatMap((c) => c.topics ?? [])).size, [ep.claims]);
  const viewList = topic ? byView.filter((c) => c.topics?.includes(topic)) : byView;
  const current = useMemo(() => {
    let cur: Claim | null = null;
    for (const c of listed) if (c.start_s <= time + 0.5) cur = c;
    return cur;
  }, [listed, time]);
  const activeId = clip?.id ?? (following && playing ? current?.id ?? null : null);

  const flash = (msg: string) => { setToast(msg); window.setTimeout(() => setToast(null), 2500); };
  // Scroll a card to just below whatever is pinned at the top (the player and track on phones).
  // Runs after layout settles, because switching the player on changes the page height above the cards.
  const scrollToCard = (id: string) => {
    const go = () => {
      const el = document.getElementById(`card-${id}`);
      if (!el) return;
      let pinned = 0;
      for (const sel of [".player-band.is-on", ".track-holder.is-on"]) {
        const n = document.querySelector(sel);
        const cs = n ? getComputedStyle(n) : null;
        // Where it will sit once stuck: its sticky offset plus its height.
        if (n && cs && cs.position === "sticky") pinned = Math.max(pinned, (parseFloat(cs.top) || 0) + (n as HTMLElement).offsetHeight);
      }
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const top = window.scrollY + el.getBoundingClientRect().top - pinned - 12;
      window.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
    };
    requestAnimationFrame(() => requestAnimationFrame(go));
  };

  // --- Player control -------------------------------------------------------------------------
  const seek = useCallback((s: number, play: boolean) => {
    setTime(s);
    if (playerOn && player.current?.ready()) player.current.seekTo(s, play);
    else { setCue(s); if (play) { setStartPlaying(true); setPlayerOn(true); } }
  }, [playerOn]);

  // A timestamp click: leave any 20 s clip mode and play from exactly that second.
  const playFrom = useCallback((s: number) => {
    if (ep.video_pending) { flash("The YouTube link for this video hasn't been added yet."); return; }
    setClip(null);
    setCountdown(null);
    setAutoAll(false);
    seek(s, true);
  }, [ep.video_pending, seek]);

  const playMoment = useCallback((c: Claim) => {
    if (ep.video_pending) { flash("The YouTube link for this video hasn't been added yet."); return; }
    setFollowing(false);
    setCountdown(null);
    setClip({ id: c.id, end: c.start_s + CLIP_S, phase: "playing" });
    seek(Math.max(0, c.start_s - LEAD_S), true);
  }, [ep.video_pending, seek]);

  const nextIn = (c: Claim) => {
    const i = viewList.findIndex((x) => x.id === c.id);
    return i >= 0 ? viewList.slice(i + 1).find((x) => x.verdict) ?? null : null;
  };

  // --- Deep links: #claim-ID opens and cues that claim; ?moment=ID plays it; ?play=1 plays from the cue.
  useEffect(() => {
    const id = window.location.hash.match(/^#claim-(.+)$/)?.[1];
    const target = id ? ep.claims.find((c) => c.id === id) : null;
    if (target) {
      setView("all");
      setExpanded(new Set([target.id]));
      setCue(Math.max(0, target.start_s - CUE_LEAD_S));
      setTime(target.start_s);
      window.setTimeout(() => scrollToCard(target.id), 60);
    }
    const m = momentId ? ep.claims.find((c) => c.id === momentId) : null;
    if (m) {
      setView("all");
      playMoment(m);
      window.setTimeout(() => scrollToCard(m.id), 60);
    } else if (autoplay && !ep.video_pending) {
      setStartPlaying(true);
      setPlayerOn(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Clock polling --------------------------------------------------------------------------
  useEffect(() => {
    if (!playerOn) return;
    const id = window.setInterval(() => {
      const p = player.current;
      if (!p?.ready()) return;
      const t = p.time();
      setTime((prev) => (Math.abs(prev - t) > 0.2 ? t : prev));
    }, playing ? 250 : 1000);
    return () => window.clearInterval(id);
  }, [playing, playerOn]);

  // End of a 20 s clip: pause and offer Keep watching / Next claim.
  useEffect(() => {
    if (clip?.phase === "playing" && time >= clip.end) {
      player.current?.pause();
      setClip({ ...clip, phase: "ended" });
      if (autoAll) setCountdown(AUTO_NEXT_S);
    }
  }, [time, clip, autoAll]);

  // "Play flagged in order": count down, then play the next claim.
  useEffect(() => {
    if (countdown === null || !clip) return;
    if (countdown <= 0) {
      const c = listed.find((x) => x.id === clip.id);
      const n = c ? nextIn(c) : null;
      setCountdown(null);
      if (n) { playMoment(n); scrollToCard(n.id); } else { setAutoAll(false); flash("That was the last claim."); }
      return;
    }
    const id = window.setTimeout(() => setCountdown((x) => (x === null ? null : x - 1)), 1000);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown]);

  // Keep watching: follow the current claim; manual scrolling pauses the auto-scroll.
  useEffect(() => {
    const stop = () => { if (following && playing) setScrollFollow(false); };
    window.addEventListener("wheel", stop, { passive: true });
    window.addEventListener("touchmove", stop, { passive: true });
    return () => { window.removeEventListener("wheel", stop); window.removeEventListener("touchmove", stop); };
  }, [following, playing]);
  useEffect(() => {
    if (following && playing && scrollFollow && current && viewList.some((c) => c.id === current.id)) scrollToCard(current.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, following, playing, scrollFollow]);

  // While the first pass runs, or someone's Verify request is in flight, keep the page fresh.
  useEffect(() => {
    if (!checking && !verifyingCount) return;
    const id = window.setInterval(() => router.refresh(), 20000);
    return () => window.clearInterval(id);
  }, [checking, verifyingCount, router]);

  // Keyboard: J / K previous / next claim in the current view.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.key !== "j" && e.key !== "k") return;
      const ref = clip ? listed.find((c) => c.id === clip.id)?.start_s ?? time : time;
      const list = viewList.filter((c) => c.verdict);
      const t = e.key === "k" ? list.find((c) => c.start_s > ref + 0.5) : [...list].reverse().find((c) => c.start_s < ref - 0.5);
      if (t) { playMoment(t); scrollToCard(t.id); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // --- Share and copy -------------------------------------------------------------------------
  const share = async (url: string, text: string) => {
    try {
      if (navigator.share) { await navigator.share({ title: ep.title, text, url }); return; }
      await navigator.clipboard.writeText(`${text} ${url}`);
      flash("Link copied");
    } catch { /* cancelled */ }
  };
  const shareClaim = (c: Claim) => share(`${window.location.origin}/v/${ep.youtube_video_id}#claim-${c.id}`,
    c.verdict ? `${VERDICTS[c.verdict.verdict].label}: “${c.claim_text}”` : c.claim_text);
  const copySource = async (c: Claim) => {
    const s = c.verdict?.citations[0];
    if (!s) return;
    try {
      await navigator.clipboard.writeText(`${s.summary ? s.quote : `“${s.quote}”`} (${s.title ?? s.url})${s.url ? ` ${s.url}` : ""}`);
      flash("Source copied");
    } catch { flash("Couldn't copy. Select the text and copy it instead."); }
  };

  // --- Rendering helpers ----------------------------------------------------------------------
  const pickTopic = (t: string) => setTopic((cur) => (cur === t ? null : t));
  const toggle = (id: string) => setExpanded((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const card = (c: Claim) => {
    const isActive = activeId === c.id;
    const n = nextIn(c);
    if (!c.verdict && !c.awaiting_review) {
      return (
        <StatementCard key={c.id} claim={c} videoId={ep.youtube_video_id} active={isActive}
          phase={isActive && clip?.id === c.id ? clip.phase : isActive ? "playing" : "idle"} canWatch={!ep.video_pending}
          canVerify={!checking} activeTopic={topic} onTopic={pickTopic} onSeek={() => playFrom(c.start_s)} onWatch={() => { playMoment(c); scrollToCard(c.id); }}
          onKeepWatching={() => { setClip(null); setCountdown(null); setAutoAll(false); setFollowing(true); setScrollFollow(true); player.current?.play(); }} />
      );
    }
    return (
      <ClaimCard key={c.id} claim={c} videoId={ep.youtube_video_id} activeTopic={topic} onTopic={pickTopic} expanded={expanded.has(c.id)} active={isActive}
        phase={isActive && clip?.id === c.id ? clip.phase : isActive ? "playing" : "idle"}
        countdown={isActive && autoAll ? countdown : null} hasNext={!!n} canWatch={!ep.video_pending}
        onToggle={() => toggle(c.id)} onWatch={() => { playMoment(c); scrollToCard(c.id); }}
        onKeepWatching={() => { setClip(null); setCountdown(null); setAutoAll(false); setFollowing(true); setScrollFollow(true); player.current?.play(); }}
        onNext={() => { if (n) { setCountdown(null); playMoment(n); scrollToCard(n.id); } }}
        onSeek={() => playFrom(c.start_s)}
        onShare={() => shareClaim(c)} onCopySource={() => copySource(c)} />
    );
  };

  const supported = ep.tally.supported ?? 0;
  const checkedCount = listed.filter((c) => c.verdict).length;
  const reviewingCount = listed.filter((c) => c.awaiting_review).length;
  const flagParts = FLAGGED.filter((v) => ep.tally[v]).map((v) => `${ep.tally[v]} ${VERDICTS[v].label.toLowerCase()}`);
  const chipTypes = TYPE_ORDER.filter((t) => CORE_TYPES.includes(t) || typeCounts[t]);

  return (
    <div className="score">
      <div className="score-main">
        <div className={`player-band${playerOn ? " is-on" : ""}`}>
          <div className="player-frame">
            {playerError !== null ? (
              <div className="player-error">
                <p>This video isn&apos;t available on YouTube any more.</p>
                <p className="meta">The claims and sources are still readable.</p>
              </div>
            ) : playerOn ? (
              <YouTubePlayer ref={player} videoId={ep.youtube_video_id} start={cue} autoplay={startPlaying}
                             onPlayingChange={setPlaying} onError={setPlayerError} />
            ) : (
              <button className="facade" onClick={() => { if (ep.video_pending) return; setStartPlaying(true); setPlayerOn(true); }}
                      aria-label={ep.video_pending ? "YouTube link not added yet" : `Play video from ${clock(cue)}`} disabled={ep.video_pending}>
                <Thumb videoId={ep.video_pending ? "" : ep.youtube_video_id} title={ep.title} eager
                       duration={ep.duration_s ? clock(ep.duration_s) : undefined} />
                {!ep.video_pending && <span className="facade-play" aria-hidden="true">▶</span>}
                {!ep.video_pending && cue > 0 && <span className="facade-cue">Starts at {clock(cue)}</span>}
              </button>
            )}
          </div>
        </div>
        {!ep.video_pending && playerOn && (
          <p className="vcard-under">
            <a className="vcard-yt" href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}`} target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a>
          </p>
        )}

        {ep.claims.length > 0 && (
          <div className={`track-holder${playerOn ? " is-on" : ""}`}>
            <ClaimTrack claims={ep.claims} duration={ep.duration_s} time={time} currentId={activeId}
                        onSeekClaim={(c) => { setExpanded((s) => new Set(s).add(c.id)); if (!viewList.includes(c)) setView("all"); window.setTimeout(() => scrollToCard(c.id), 60); playFrom(c.start_s); }} />
          </div>
        )}

        <header className="score-head">
          <h1>{ep.title}</h1>
          <div className="watch-channel">
            <Avatar src={ep.channel_avatar} name={ep.channel_name} />
            {ep.channel_id ? <Link href={`/c/${ep.channel_id}`}>{ep.channel_name}</Link> : <span>{ep.channel_name}</span>}
            <button className="btn secondary small share-ep" onClick={() => share(window.location.href.split("#")[0], ep.title)}>Share</button>
          </div>
          {ep.guest && <p className="meta">Guest: {ep.guest}</p>}
        </header>

        {ep.import_note && <p className="notice import-note">{ep.import_note}</p>}
        {checking && <CheckProgress videoId={ep.youtube_video_id} />}

        {ep.claims.length > 0 && (
          <section className="score-summary" aria-label="Summary">
            <p className="score-big">{ep.claims.length} statements</p>
            <p className="type-bar" aria-hidden="true">
              {TYPE_ORDER.filter((t) => typeCounts[t]).map((t) => (
                <span key={t} style={{ flexGrow: typeCounts[t], background: STATEMENT_TYPES[t].cssVar }} />
              ))}
            </p>
            <p className="meta">{breakdownParts(typeCounts).join(", ")}</p>
            <p className="meta">
              {checkedCount} verified{checkedCount ? `, ${supported} supported` : ""}{flagParts.length ? `, ${flagParts.join(", ")}` : ""}
              {reviewingCount > 0 && `. ${reviewingCount} with a reviewer`}
              {verifyingCount > 0 && `. ${verifyingCount} being verified now`}
            </p>
            {checkedCount > 0 && <VerdictStrip tally={ep.tally} />}
          </section>
        )}
      </div>

      <div className="score-side">
        {ep.claims.length > 0 && (
          <>
            <div className="filters stmt-filters" role="group" aria-label="Show statements by type">
              <button className="chip" aria-pressed={view === "all"} onClick={() => setView("all")}>All {everything.length}</button>
              {chipTypes.map((t) => (
                <button key={t} className="chip chip-type" aria-pressed={view === t} onClick={() => setView(t)}
                        style={{ ["--stype" as string]: STATEMENT_TYPES[t].cssVar }} title={STATEMENT_TYPES[t].meaning}>
                  {STATEMENT_TYPES[t].label} {typeCounts[t] ?? 0}
                </button>
              ))}
              <button className="chip" aria-pressed={view === "verified"} onClick={() => setView("verified")}>Verified {listed.length}</button>
            </div>
            {allTopicCount > 1 && (
              <div className="filters topic-filters" role="group" aria-label="Show statements by subject">
                <button className="chip" aria-pressed={topic === null} onClick={() => setTopic(null)}>All subjects</button>
                {(topic && !topicCounts.some(([t]) => t === topic) ? [...topicCounts, [topic, 0] as [string, number]] : topicCounts).map(([t, n]) => (
                  <button key={t} className="chip topic-tag topic-chip" aria-pressed={topic === t} onClick={() => setTopic(topic === t ? null : t)}
                          style={{ ["--th" as string]: topicHue(t) }}>
                    {topicLabel(t)} <span className="tag-n">{n}</span>
                  </button>
                ))}
              </div>
            )}
            {view !== "all" && view !== "verified" && <p className="meta stmt-legend">{STATEMENT_TYPES[view].meaning}{view === "factual_claim" ? " Press Verify on any of them to check it against official sources." : ""}</p>}
            {viewList.some((c) => c.verdict) && !ep.video_pending && (
              <p className="play-all">
                <button className="btn secondary small" onClick={() => { const first = viewList.find((c) => c.verdict); if (first) { setAutoAll(true); playMoment(first); scrollToCard(first.id); } }}>
                  ▶ Play verified claims in order
                </button>
                {autoAll && <button className="btn secondary small" onClick={() => { setAutoAll(false); setCountdown(null); }}>Stop</button>}
              </p>
            )}
          </>
        )}

        <div className="cards">
          {viewList.length === 0
            ? <p className="meta pad">{view === "verified" ? "No claims verified yet. Pick a claim and press Verify."
                : view !== "all" ? `No ${STATEMENT_TYPES[view].plural} in this video.`
                : checking ? "Statements appear here as they are found." : "No statements for this video."}</p>
            : viewList.map(card)}
        </div>

        <details className="fold">
          <summary>How this video was checked</summary>
          <ul className="nclist">
            <li>{ep.claims.length} statements found and tagged by type. Nothing is verified automatically: press Verify on any claim to check it against sources, and the result is shown to everyone.</li>
            <li>{listed.filter((c) => c.verdict?.review_status === "approved" || c.verdict?.review_status === "changed").length} verdicts reviewed by a person; {listed.filter((c) => c.awaiting_review).length} still with a reviewer.</li>
            <li><Link href="/method">How we check</Link></li>
            {!ep.video_pending && <li><a href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}&t=${Math.floor(time)}s`} target="_blank" rel="noopener noreferrer">Watch on YouTube from {clock(time)}</a></li>}
          </ul>
        </details>
      </div>

      {following && playing && !scrollFollow && (
        <button className="back-to-now" onClick={() => { setScrollFollow(true); if (current) scrollToCard(current.id); }}>Back to now</button>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
