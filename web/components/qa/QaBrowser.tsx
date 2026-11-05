"use client";

import { useEffect, useRef, useState } from "react";
import { Thumb } from "@/components/Thumb";
import { YouTubePlayer, type PlayerHandle } from "@/components/watch/YouTubePlayer";
import { clock, domain, shortDate, ytLink } from "@/lib/format";
import { dedupeSources, trim } from "@/lib/notes";
import type { QaItem } from "@/lib/qa";
import { STATEMENT_TYPES, speakerName } from "@/lib/statements";
import type { Claim, SourcesMatch } from "@/lib/types";
import s from "./qa-browser.module.css";

const MATCH_WORD: Record<SourcesMatch, string> = { high: "High", medium: "Medium", low: "Low" };

/**
 * The video on top, then `children` (the title and intro, written by the page); below them the questions on the left and the selected answer on the right. An answer is split in two:
 * the answer (as extracted from the video) next to what the web pages found for it say. Every answer is in the page
 * (the others are hidden), so the questions and answers can be found and linked (#q-3); a timestamp plays the video.
 */
export function QaBrowser({ videoId, title, durationS, items, children }:
  { videoId: string; title: string; durationS: number; items: QaItem[]; children?: React.ReactNode }) {
  const [sel, setSel] = useState(0);
  const [playerOn, setPlayerOn] = useState(false);
  const [startPlaying, setStartPlaying] = useState(false);
  const [cue, setCue] = useState(0);
  const [playerError, setPlayerError] = useState<number | null>(null);
  const player = useRef<PlayerHandle>(null);
  const pager = useRef<HTMLDivElement>(null);

  // A link to #q-3 opens that question.
  useEffect(() => {
    const m = /^#q-(\d+)$/.exec(window.location.hash);
    const n = m ? Number.parseInt(m[1], 10) - 1 : -1;
    if (n >= 0 && n < items.length) setSel(n);
  }, [items.length]);

  const choose = (n: number, focus = false) => {
    const i = Math.max(0, Math.min(items.length - 1, n));
    setSel(i);
    window.history.replaceState(null, "", `#q-${i + 1}`);
    if (focus) pager.current?.querySelectorAll<HTMLButtonElement>("button[data-page]")[i]?.focus();
  };

  const playFrom = (seconds: number) => {
    setCue(seconds);
    if (playerOn && player.current?.ready()) player.current.seekTo(seconds, true);
    else { setStartPlaying(true); setPlayerOn(true); }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const onPagerKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") { e.preventDefault(); choose(sel + 1, true); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); choose(sel - 1, true); }
  };

  return (
    <div>
      <div className={s.hero}>
        <div className={s.video}>
        <div className={`player-band${playerOn ? " is-on" : ""}`}>
          <div className="player-frame">
            {playerError !== null ? (
              <div className="player-error"><p>This video isn&apos;t available on YouTube any more.</p></div>
            ) : playerOn ? (
              <YouTubePlayer ref={player} videoId={videoId} start={cue} autoplay={startPlaying} onError={setPlayerError} />
            ) : (
              <button className="facade" onClick={() => { setStartPlaying(true); setPlayerOn(true); }} aria-label="Play the video">
                <Thumb videoId={videoId} title={title} eager hd duration={durationS ? clock(durationS) : undefined} />
                <span className="facade-play" aria-hidden="true">▶</span>
              </button>
            )}
          </div>
        </div>
        <p className={s.under}>
          <a href={`https://www.youtube.com/watch?v=${videoId}`} target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a>
        </p>
        </div>
        <div className={s.intro}>{children}</div>
      </div>

      <div className={s.pager} ref={pager} onKeyDown={onPagerKey} role="navigation" aria-label="Questions">
        <button type="button" className={s.pagerStep} onClick={() => choose(sel - 1, false)} disabled={sel === 0}>← Previous</button>
        <ol className={s.pages}>
          {items.map((it, n) => (
            <li key={n}>
              <button type="button" data-page className={s.page} aria-current={n === sel ? "page" : undefined}
                      aria-label={`Question ${n + 1}: ${it.q}`} title={it.q} onClick={() => choose(n)}>{n + 1}</button>
            </li>
          ))}
        </ol>
        <button type="button" className={s.pagerStep} onClick={() => choose(sel + 1, false)} disabled={sel === items.length - 1}>Next →</button>
      </div>

      <div className={s.pane}>
          {items.map((it, n) => (
            <section key={n} id={`q-${n + 1}`} hidden={n !== sel} aria-labelledby={`q-${n + 1}-h`}>
              <h2 className={s.h2} id={`q-${n + 1}-h`}>{it.q}</h2>
              {(it.askedBy || it.implied) && (
                <p className={s.asked}>
                  {it.implied ? "Question written by AI to fit what was said" : `Asked by ${speakerName(it.askedBy) ?? it.askedBy}`}
                </p>
              )}
              {it.claims.map((c) => <AnswerRow key={c.id} c={c} videoId={videoId} onPlay={playFrom} />)}
              <div className={s.step}>
                <button type="button" onClick={() => choose(n - 1, false)} disabled={n === 0}>← Previous</button>
                <span>{n + 1} of {items.length}</span>
                <button type="button" onClick={() => choose(n + 1, false)} disabled={n === items.length - 1}>Next →</button>
              </div>
            </section>
          ))}
      </div>
    </div>
  );
}

function AnswerRow({ c, videoId, onPlay }: { c: Claim; videoId: string; onPlay: (seconds: number) => void }) {
  const type = STATEMENT_TYPES[c.statement_type];
  const who = speakerName(c.speaker);
  const srcs = dedupeSources(c.sources);
  return (
    <div className={s.row}>
      <div className={s.said}>
        <p className={s.label}>The answer</p>
        <p className={s.who}>
          {who ? `${who} (identified by AI) · ` : ""}
          <a href={ytLink(videoId, c.start_s)} onClick={(e) => { e.preventDefault(); onPlay(c.start_s); }}>▶ {clock(c.start_s)}</a>
          {" · "}<span className={s.type} style={{ ["--t" as string]: type.cssVar }}>{type.label}</span>
        </p>
        <p className={s.text}>{c.claim_text}</p>
      </div>
      <div className={s.found}>
        <p className={s.label}>What web pages say</p>
        {c.sources_summary ? <p className={s.summary}>{c.sources_summary}</p>
          : srcs.length === 0 ? <p className={s.none}>No web sources have been looked up for this statement yet.</p> : null}
        {c.counter_summary && <p className={s.other}><b>Other figures and views found.</b> {c.counter_summary}</p>}
        {srcs.length > 0 && (
          <ul className={s.srcs}>
            {srcs.map((x) => {
              const date = shortDate(x.publish_date);
              return (
                <li key={x.url}>
                  <a href={x.url} rel="noopener nofollow">{x.title ?? domain(x.url)}</a>{" "}
                  <span className={s.site}>{domain(x.url)}{date ? ` · ${date}` : ""}</span>
                  {!c.sources_summary && x.excerpt && <span className={s.excerpt}>“{trim(x.excerpt, 200)}”</span>}
                </li>
              );
            })}
          </ul>
        )}
        {c.sources_match && (
          <p className={`${s.match} ${s[c.sources_match]}`}>Source match: <b>{MATCH_WORD[c.sources_match]}</b> · relevance of the excerpts, not agreement</p>
        )}
      </div>
    </div>
  );
}
