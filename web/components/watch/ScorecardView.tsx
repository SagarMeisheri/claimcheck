"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Avatar, Thumb } from "@/components/Thumb";
import type { Claim, EpisodeDetail, Section, SourcesMatch, StatementType } from "@/lib/types";
import { STATEMENT_TYPES, SEARCHING, TYPE_ORDER, breakdownParts, canCheckSources, hasSources, typeOf } from "@/lib/statements";
import { clock } from "@/lib/format";
import { CheckProgress } from "@/components/CheckProgress";
import { CheckAllSources } from "@/components/CheckAllSources";
import { CheckedAt } from "@/components/CheckedAt";
import { type CardPhase } from "./ClaimCard";
import { StatementDetail } from "./StatementDetail";
import { groupBySection } from "@/components/feed/StatementCarousel";
import { applyTagFilter, severity, type TagFilter } from "@/lib/indicators";
import { QaCard } from "./QaCard";
import { groupByQuestion, type QaGroup } from "@/lib/qa";
import { KeyFindings, PodcastProfile, type Sort } from "./PodcastProfile";
import { Drawer, PaneNav } from "@/components/Drawer";
import { ClaimTrack } from "./ClaimTrack";
import { ProfileTabs } from "./ProfileTabs";
import type { SourcesResult } from "@/components/CheckSources";
import { YouTubePlayer, type PlayerHandle } from "./YouTubePlayer";

/** Filter chips: every statement, one statement type, or claims that have sources. */
export type View = "all" | "with_sources" | StatementType;
const CLIP_S = 20;
const LEAD_S = 3;
const CUE_LEAD_S = 5;
const AUTO_NEXT_S = 4;
const DOCK_QUERY = "(min-width: 1600px)"; // wide screens (sidebar + three panes): the selected statement's detail is docked beside the list

/** The nearest ancestor that scrolls on its own, or null when the page itself scrolls. */
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

/** True while a media query matches (false on the server and the first render). */
function useMedia(query: string): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query);
    const update = () => setOn(m.matches);
    update();
    m.addEventListener("change", update);
    return () => m.removeEventListener("change", update);
  }, [query]);
  return on;
}

export function ScorecardView({ ep, initialT, autoplay, momentId, initialView, initialMatch }: {
  ep: EpisodeDetail; initialT: number | null; autoplay: boolean; momentId: string | null; initialView: View | null; initialMatch?: SourcesMatch | null;
}) {
  const router = useRouter();
  const player = useRef<PlayerHandle>(null);
  // Lookups finished on this page since it loaded: their results, so the tag and the drawer show them at once.
  const [looked, setLooked] = useState<Record<string, Claim>>({});
  const everything = useMemo(() => ep.claims.map((c) => looked[c.id] ?? c).sort((a, b) => a.start_s - b.start_s), [ep.claims, looked]);
  // The statement whose detail is shown: docked beside the list on wide screens, in a drawer otherwise.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const wide = useMedia(DOCK_QUERY);
  // The docked panel opens when a statement is picked (or a link points at one), so the video leads on arrival; ✕ closes it.
  const [dockOpen, setDockOpen] = useState(false);
  const docked = wide && dockOpen;
  const visible = useMemo(() => everything.filter((c) => c.not_checked_reason !== "outside_policy"), [everything]);
  const withSources = useMemo(() => visible.filter((c) => c.sources.length > 0), [visible]);
  const typeCounts = useMemo(() => {
    const t: Partial<Record<StatementType, number>> = {};
    for (const c of ep.claims) { const k = typeOf(c.statement_type); t[k] = (t[k] ?? 0) + 1; }
    return t;
  }, [ep.claims]);
  const searchingCount = ep.claims.filter((c) => SEARCHING.includes(c.sources_status)).length;
  const checking = ep.status === "processing" || ep.status === "queued";
  // Sources are looked up by themselves for this video: no buttons, progress instead. "running" while the video is still
  // being read or the follow-up batch is working, so an answer that hasn't been reached yet already shows a spinner.
  const auto = !!ep.auto_sources;
  const lookingUp = checking || ep.sources_batch === "running";
  // Videos analysed as questions and answers say so; older ones are lists of statements.
  const qa = ep.claims.some((c) => !!c.question);
  const nouns = qa ? { one: "answer", many: "answers" } : { one: "statement", many: "statements" };

  const [view, setView] = useState<View>(initialView ?? "all")
  const [match, setMatch] = useState<SourcesMatch | null>(null);
  const chipTypes = TYPE_ORDER.filter((t) => t === "factual_claim" || typeCounts[t]);
  const [tag, setTag] = useState<TagFilter | null>(null); // a question, answer or evidence tag picked in the interview profile
  const [playerOn, setPlayerOn] = useState(false);
  const [startPlaying, setStartPlaying] = useState(false);
  const [cue, setCue] = useState(initialT ?? 0);
  const [time, setTime] = useState(initialT ?? 0);
  const [playing, setPlaying] = useState(false);
  const [playerError, setPlayerError] = useState<number | null>(null);
  const [clip, setClip] = useState<{ id: string; end: number; phase: CardPhase } | null>(null);
  const [following, setFollowing] = useState(false); // "Keep watching": highlight statements as the video passes them
  const [scrollFollow, setScrollFollow] = useState(true);
  const [autoAll, setAutoAll] = useState(false); // "Play in order"
  const [countdown, setCountdown] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [profilesAsk, setProfilesAsk] = useState(0); // "Full profile" clicked in the podcast profile: open the Profiles tab
  const [sort, setSort] = useState<Sort>("time"); // the feed in video order, or worst verdict first
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set()); // chapters folded to their heading

  const byView = view === "all" ? everything : view === "with_sources" ? withSources : everything.filter((c) => typeOf(c.statement_type) === view);
  const viewList = applyTagFilter(match ? byView.filter((c) => c.sources_match === match) : byView, tag);
  const playable = viewList.filter((c) => c.not_checked_reason !== "outside_policy");
  const current = useMemo(() => {
    let cur: Claim | null = null;
    for (const c of visible) if (c.start_s <= time + 0.5) cur = c;
    return cur;
  }, [visible, time]);
  const activeId = clip?.id ?? (following && playing ? current?.id ?? null : null);

  const flash = (msg: string) => { setToast(msg); window.setTimeout(() => setToast(null), 2500); };
  // Scroll a card into view, below whatever is pinned at the top (the player and track on phones).
  // Runs after layout settles, because switching the player on changes the page height above the cards.
  const scrollToCard = (id: string) => scrollToEl(`card-${id}`);
  const scrollToEl = (elId: string) => {
    setCollapsed((c) => (c.size ? new Set() : c)); // a card inside a folded chapter: unfold first
    const go = () => {
      const el = document.getElementById(elId);
      if (!el) return;
      const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      // Wide screens: each column scrolls on its own.
      const box = scrollParent(el);
      if (box) {
        const bar = box.querySelector<HTMLElement>(".pp"); // the pinned scoreboard covers the top of the feed
        const pinnedBar = bar && getComputedStyle(bar).position === "sticky" ? bar.offsetHeight : 0;
        const top = box.scrollTop + el.getBoundingClientRect().top - box.getBoundingClientRect().top - 12 - pinnedBar;
        box.scrollTo({ top: Math.max(0, top), behavior });
        return;
      }
      // Phones: the page scrolls, under the pinned player.
      const dock = document.querySelector(".player-dock") as HTMLElement | null;
      const cs = dock ? getComputedStyle(dock) : null;
      const pinned = dock && cs?.position === "sticky" ? (parseFloat(cs.top) || 0) + dock.offsetHeight : 0;
      const top = window.scrollY + el.getBoundingClientRect().top - pinned - 12;
      window.scrollTo({ top: Math.max(0, top), behavior });
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
    setClip(null);
    setCountdown(null);
    setAutoAll(false);
    seek(s, true);
  }, [seek]);

  // A click on a card's time or ▶: play from just before its answer with no stop at 20 s, and follow along (the
  // card that is playing is highlighted and the list scrolls with the video). "Watch 20 s" and "Play in order" still use clips.
  const playCard = useCallback((c: Claim) => {
    setSelectedId(c.id);
    setClip(null);
    setCountdown(null);
    setAutoAll(false);
    setFollowing(true);
    setScrollFollow(true);
    seek(Math.max(0, c.start_s - LEAD_S), true);
  }, [seek]);

  const playMoment = useCallback((c: Claim) => {
    setSelectedId(c.id); // the detail follows what is playing
    setFollowing(false);
    setCountdown(null);
    setClip({ id: c.id, end: c.start_s + CLIP_S, phase: "playing" });
    seek(Math.max(0, c.start_s - LEAD_S), true);
  }, [seek]);

  const nextIn = (c: Claim) => {
    const i = playable.findIndex((x) => x.id === c.id);
    return i >= 0 ? playable[i + 1] ?? null : null;
  };

  // --- Deep links: #claim-ID cues that statement; ?moment=ID plays it; ?play=1 plays from the cue.
  useEffect(() => {
    const id = window.location.hash.match(/^#claim-(.+)$/)?.[1];
    const target = id ? ep.claims.find((c) => c.id === id) : null;
    if (target) {
      setView("all");
      setSelectedId(target.id);
      setDockOpen(true);
      setCue(Math.max(0, target.start_s - CUE_LEAD_S));
      setTime(target.start_s);
      window.setTimeout(() => scrollToCard(target.id), 60);
    }
    const m = momentId ? ep.claims.find((c) => c.id === momentId) : null;
    if (m) {
      setView("all");
      playMoment(m);
      window.setTimeout(() => scrollToCard(m.id), 60);
    } else if (autoplay) {
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

  // End of a 20 s clip: pause and offer Keep watching / Next.
  useEffect(() => {
    if (clip?.phase === "playing" && time >= clip.end) {
      player.current?.pause();
      setClip({ ...clip, phase: "ended" });
      if (autoAll) setCountdown(AUTO_NEXT_S);
    }
  }, [time, clip, autoAll]);

  // "Play in order": count down, then play the next statement in the current view.
  useEffect(() => {
    if (countdown === null || !clip) return;
    if (countdown <= 0) {
      const c = ep.claims.find((x) => x.id === clip.id);
      const n = c ? nextIn(c) : null;
      setCountdown(null);
      if (n) { playMoment(n); scrollToCard(n.id); } else { setAutoAll(false); flash("That was the last one."); }
      return;
    }
    const id = window.setTimeout(() => setCountdown((x) => (x === null ? null : x - 1)), 1000);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown]);

  // Keep watching: follow the current statement; manual scrolling pauses the auto-scroll.
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

  // While the analysis runs, or a source lookup is in flight, keep the page fresh.
  useEffect(() => {
    if (!checking && !searchingCount) return;
    const id = window.setInterval(() => router.refresh(), 20000);
    return () => window.clearInterval(id);
  }, [checking, searchingCount, router]);

  // Keyboard: J / K previous / next statement in the current view.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.key !== "j" && e.key !== "k") return;
      const ref = clip ? ep.claims.find((c) => c.id === clip.id)?.start_s ?? time : time;
      const t = e.key === "k" ? playable.find((c) => c.start_s > ref + 0.5) : [...playable].reverse().find((c) => c.start_s < ref - 0.5);
      if (t) { playMoment(t); scrollToCard(t.id); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // --- Share ----------------------------------------------------------------------------------
  const share = async (url: string, text: string) => {
    try {
      if (navigator.share) { await navigator.share({ title: ep.title, text, url }); return; }
      await navigator.clipboard.writeText(`${text} ${url}`);
      flash("Link copied");
    } catch { /* cancelled */ }
  };
  // A link to the moment only: the text is the video title, never a characterisation of what was said.
  const shareClaim = (c: Claim) => share(`${window.location.origin}/v/${ep.youtube_video_id}#claim-${c.id}`, `${ep.title} at ${clock(c.start_s)}`);

  // --- Selection and detail --------------------------------------------------------------------
  const lookedUp = (c: Claim, r: SourcesResult) => setLooked((m) => ({ ...m, [c.id]: { ...c, sources_status: "done", sources: r.sources ?? [],
    sources_summary: r.summary ?? null, sources_match: r.match ?? null, counter_sources: r.counter ?? [],
    counter_summary: r.counter_summary ?? null, research: r.research ?? null, qa_tags: r.qa_tags ?? c.qa_tags ?? null, sources_route: r.route ?? c.sources_route } }));
  const select = (c: Claim) => { setSelectedId(c.id); if (wide) setDockOpen(true); else setDrawerOpen(true); };
  const selected = visible.find((c) => c.id === selectedId) ?? (docked ? playable[0] ?? null : null);
  const selAt = selected ? playable.findIndex((c) => c.id === selected.id) : -1;
  const selectAt = (i: number) => { const c = playable[i]; if (c) { setSelectedId(c.id); scrollToCard(c.id); } };
  const detail = (c: Claim, titleId: string) => {
    const isActive = activeId === c.id;
    return (
      <StatementDetail claim={c} videoId={ep.youtube_video_id} titleId={titleId} canLookUp={!checking && !(auto && c.sources_status === "not_requested")}
        phase={isActive && clip?.id === c.id ? clip.phase : isActive ? "playing" : "idle"} hasNext={!!nextIn(c)}
        countdown={isActive && autoAll ? countdown : null}
        onSeek={() => playFrom(c.start_s)} onWatch={() => { playMoment(c); scrollToCard(c.id); }}
        onKeepWatching={() => { setClip(null); setCountdown(null); setAutoAll(false); setFollowing(true); setScrollFollow(true); player.current?.play(); }}
        onNext={() => { const n = nextIn(c); if (n) { setCountdown(null); playMoment(n); scrollToCard(n.id); } }}
        onShare={() => shareClaim(c)} onLookedUp={(r) => lookedUp(c, r)} />
    );
  };
  const nav = <PaneNav hasPrev={selAt > 0} hasNext={selAt >= 0 && selAt < playable.length - 1} onPrev={() => selectAt(selAt - 1)} onNext={() => selectAt(selAt + 1)} />;
  const groups = groupBySection(playable, ep.sections ?? []);
  // A chapter clicked in the Chapters tab: show every statement (a filter may hide that part), then
  // play the video from its start, scroll the list to its heading and select its first statement.
  const goToSection = (sec: Section) => {
    const first = visible.find((c) => (c.section_idx ?? -1) === sec.idx) ?? visible.find((c) => c.start_s >= sec.start_s);
    if (!groups.some((g) => g.section?.idx === sec.idx)) { setView("all"); setMatch(null); setTag(null); }
    if (first && wide) setSelectedId(first.id);
    playFrom(sec.start_s);
    window.setTimeout(() => scrollToEl(`sec-${sec.idx}`), 60);
  };

  // Sources already checked for this video ("last checked" shown): no button to check them all again.
  const lookupEligible = !ep.sources_checked_at && ep.claims.some((c) => canCheckSources(c));

  // A key finding clicked: show the card (a filter may hide it), mark it and scroll to it.
  const jumpTo = (c: Claim) => {
    if (!viewList.includes(c)) { setView("all"); setMatch(null); setTag(null); }
    setSelectedId(c.id);
    window.setTimeout(() => scrollToCard(c.id), 60);
  };
    const worstFirst = (gs: QaGroup[]) => gs.map((g, i) => ({ g, i, s: Math.min(...g.answers.map(severity)) })).sort((a, b) => a.s - b.s || a.i - b.i).map((x) => x.g);
  const card = (grp: QaGroup) => (
    <QaCard key={grp.answers[0].id} group={grp} auto={auto} running={lookingUp} activeId={activeId} selectedId={selected?.id ?? null}
            onPlay={playCard} onSelect={select} onLookedUp={lookedUp} />
  );
  const foldToggle = (key: string) => setCollapsed((c) => { const n = new Set(c); if (!n.delete(key)) n.add(key); return n; });
  // "Check sources for all" (or "Re-check all"): a small button at the foot of the podcast profile.
  const checkAll = !checking && (
    <CheckAllSources videoId={ep.youtube_video_id} running={ep.sources_batch === "running"} eligible={lookupEligible && !auto}
                     canRecheck={ep.claims.some((c) => c.sources_status === "done" || c.sources_route === "skip")} onRecheck={() => setLooked({})} />
  );
  const head = (cls: string) => (
    <header className={`score-head ${cls}`}>
      <h1>{ep.title}</h1>
      <div className="watch-channel">
        <Avatar name={ep.channel_name} size={20} />
        {ep.channel_id ? <Link href={`/c/${ep.channel_id}`}>{ep.channel_name}</Link> : <span>{ep.channel_name}</span>}
        <button className="btn secondary small share-ep" onClick={() => share(window.location.href.split("#")[0], ep.title)}>Share</button>
      </div>
    </header>
  );

  return (
    <div className={`score${docked ? " has-dock" : ""}`}>
      <div className="score-main">
        {/* The player and the statement track stay pinned while everything else scrolls. */}
        <div className="player-dock">
          <div className={`player-band${playerOn ? " is-on" : ""}`}>
            <div className="player-frame">
              {playerError !== null ? (
                <div className="player-error">
                  <p>This video isn&apos;t available on YouTube any more.</p>
                </div>
              ) : playerOn ? (
                <YouTubePlayer ref={player} videoId={ep.youtube_video_id} start={cue} autoplay={startPlaying}
                               onPlayingChange={setPlaying} onError={setPlayerError} />
              ) : (
                <button className="facade" onClick={() => { setStartPlaying(true); setPlayerOn(true); }} aria-label={`Play video from ${clock(cue)}`}>
                  <Thumb videoId={ep.youtube_video_id} title={ep.title} eager hd duration={ep.duration_s ? clock(ep.duration_s) : undefined} />
                  <span className="facade-play" aria-hidden="true">▶</span>
                  {cue > 0 && <span className="facade-cue">Starts at {clock(cue)}</span>}
                </button>
              )}
            </div>
          </div>
          {ep.claims.length > 0 && (
            <div className={`track-holder${playerOn ? " is-on" : ""}`}>
              <ClaimTrack claims={ep.claims} duration={ep.duration_s} time={time} currentId={activeId}
                          onSeekClaim={(c) => { if (!viewList.includes(c)) { setView("all"); setTag(null); } window.setTimeout(() => scrollToCard(c.id), 60); playFrom(c.start_s); }} />
            </div>
          )}
        </div>
        <div className="score-info">
        {playerOn && (
          <p className="vcard-under">
            <a className="vcard-yt" href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}`} target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a>
          </p>
        )}

        {head("score-head-rail")}

        {checking && <CheckProgress videoId={ep.youtube_video_id} initialSteps={ep.progress?.steps ?? []} />}

        <ProfileTabs summary={ep.summary} sections={ep.sections ?? []} creator={ep.creator} speakers={ep.speakers} notes={ep.interaction?.description_notes ?? []}
                     steps={(ep.steps ?? ep.progress?.steps ?? []).filter((x) => x.status === "done" || x.status === "skipped")}
                     onSeek={(s) => playFrom(s)} onSection={goToSection} showProfiles={profilesAsk} />
        </div>
      </div>

      <div className="score-side">
        {head("score-head-feed")}
        {ep.claims.length > 0 && (
          <PodcastProfile claims={everything} interaction={ep.interaction} total={ep.claims.length} noun={ep.claims.length === 1 ? nouns.one : nouns.many}
                          withSources={withSources.length} searching={searchingCount} checkedAt={ep.sources_checked_at ?? null}
                          typeCounts={typeCounts} chipTypes={chipTypes} view={view} onView={setView} tag={tag} onTag={setTag}
                          onAll={() => { setView("all"); setTag(null); }} sort={sort} onSort={setSort}
                          playAll={playable.length > 1 ? (autoAll ? "running" : "idle") : "hidden"}
                          onPlayAll={() => { const first = playable[0]; setAutoAll(true); playMoment(first); scrollToCard(first.id); }}
                          onStop={() => { setAutoAll(false); setCountdown(null); }}
                          checkAll={checkAll} onJump={jumpTo} speakers={ep.speakers} creator={ep.creator}
                          onOpenProfiles={() => { setProfilesAsk((n) => n + 1); if (!wide) window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }} />
        )}

        {sort === "time" && !tag && view === "all" && <KeyFindings claims={visible} onJump={jumpTo} />}

        <div className="score-timeline">
          {playable.length === 0
            ? <p className="meta pad">{tag ? "Nothing matches this tag with the filters above. Click the tag again to clear it." : view === "with_sources" ? "No sources looked up yet. Press Check sources on any claim."
                : view !== "all" ? `No ${STATEMENT_TYPES[view].plural} in this video.`
                : checking ? `${qa || ep.claims.length === 0 ? "Questions and answers" : "Statements"} appear here as they are found.` : "No questions or statements for this video."}</p>
            : sort === "worst" ? (
              <ol className="qa-list">{worstFirst(groupByQuestion(playable)).map(card)}</ol>
            ) : groups.map((g, gi) => {
              const key = `${g.key}-${gi}`;
              const folded = collapsed.has(key);
              const flagged = g.items.filter((c) => severity(c) <= 1).length;
              return (
                <section key={key} className="tl-group" id={g.section ? `sec-${g.section.idx}` : undefined}>
                  {g.section && (
                    <header className="tl-head">
                      <button type="button" className="tl-head-time" onClick={() => playFrom(g.section!.start_s)}
                              aria-label={`Play this part from ${clock(g.section.start_s)}`}>{clock(g.section.start_s)}</button>
                      <h3 className="tl-title">
                        <button type="button" className="tl-fold" aria-expanded={!folded} onClick={() => foldToggle(key)} title={folded ? "Show this part's answers" : "Fold this part"}>
                          <span aria-hidden="true">{folded ? "▸" : "▾"}</span> {g.section.title}
                        </button>
                        <span className="tl-roll">
                          {g.items.length} {g.items.length === 1 ? "answer" : "answers"}
                          {flagged > 0 && <span className="tl-flag" title="Contradicted, or backed only by the speaker's own word">✕ {flagged} to check</span>}
                        </span>
                      </h3>
                      {g.section.summary && !folded && <p className="tl-summary">{g.section.summary}</p>}
                    </header>
                  )}
                  {!folded && <ol className="qa-list">{groupByQuestion(g.items).map(card)}</ol>}
                </section>
              );
            })}
        </div>

        <details className="fold">
          <summary>How this video was analysed</summary>
          <ul className="nclist">
            <li>{qa
              ? <>An AI watched the video and listed {ep.claims.length} questions with their answers, with timestamps and who answered, and tagged each answer as mostly a claim, opinion, forecast, advice, story or other.</>
              : <>An AI watched the video, listed {ep.claims.length} statements with their timestamps and what was being discussed, and tagged each one as a claim, opinion, forecast, advice, story, question or other.</>}</li>
            <li>The questions, the wording of each answer, the transcript, the speaker names and the tags are AI output and can be wrong. Use &quot;Watch 20 s&quot; to hear the original, and &quot;Report a problem&quot; if something is off.</li>
            <li>Nothing is judged true or false. On any statement except questions and stories, &quot;Check sources&quot; runs a web search and shows the top results with an AI summary of their excerpts. Statements with figures or on disputed subjects also get a second search for official data, other figures or other viewpoints, aimed using public profiles of the speaker and the show.</li>
            <li><Link href="/method">How it works</Link></li>
            <li><a href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}&t=${Math.floor(time)}s`} target="_blank" rel="noopener noreferrer">Watch on YouTube from {clock(time)}</a></li>
          </ul>
        </details>
      </div>

      {docked && (
        <aside className="score-detail" aria-label="Selected statement">
          {selected ? (
            <>
              <div className="score-detail-bar">
                {nav}
                <button type="button" className="iconbtn" onClick={() => setDockOpen(false)} aria-label="Close the statement panel"
                        title="Close (pick a statement to open it again)">✕</button>
              </div>
              {detail(selected, "sdetail-title")}
            </>
          ) : <p className="meta pad">Select a statement to see its details and sources.</p>}
        </aside>
      )}

      {following && playing && !scrollFollow && (
        <button className="back-to-now" onClick={() => { setScrollFollow(true); if (current) scrollToCard(current.id); }}>Back to now</button>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
      {!wide && drawerOpen && selected && (
        <Drawer onClose={() => setDrawerOpen(false)} labelledBy="sdetail-title-drawer" accent={STATEMENT_TYPES[typeOf(selected.statement_type)].cssVar}
                nav={nav} onPrev={() => selectAt(selAt - 1)} onNext={() => selectAt(selAt + 1)}>
          {detail(selected, "sdetail-title-drawer")}
        </Drawer>
      )}
    </div>
  );
}
