"use client";

import { useEffect, useRef, useState } from "react";
import { clock } from "@/lib/format";
import { GROUNDING_UI, severity, verdictOf } from "@/lib/indicators";
import { playFromS, type QaGroup } from "@/lib/qa";
import type { Claim, Section } from "@/lib/types";

/**
 * The video's questions as a strip at the top of the feed, positioned by time and coloured by verdict (the worst answer's),
 * with the chapters marked underneath. A click goes to that question's card, which carries the same Q number. The question
 * playing now is outlined, a click on a bar or a chapter name plays the video from there, and a thin line follows the video. Contradicted and ungrounded ones stand taller, so a scan of
 * the strip shows where to look. Hover or focus a bar for its question.
 */
export function QaIndex({ groups, sections, duration, time, noun, activeId, selectedId, onJump, onSection }: {
  groups: QaGroup[]; sections: Section[]; duration: number; time: number; noun: string;
  activeId: string | null; selectedId: string | null; onJump(c: Claim): void; onSection(s: Section): void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(780); // the strip's width in px, to see which chapter names fit under their chapter
  const strip = useRef<HTMLDivElement>(null);
  const shown = groups.length >= 2;
  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth || 780);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [shown]);
  if (!shown) return null;
  const total = Math.max(duration, ...groups.map((g) => g.answers[0].start_s + 20), 60);
  const pct = (s: number) => `${Math.min(100, (s / total) * 100)}%`;
  const info = (g: QaGroup, i: number) => {
    const worst = g.answers.reduce((w, a) => (severity(a) < severity(w) ? a : w), g.answers[0]);
    const v = verdictOf(worst);
    return { first: g.answers[0], v, word: v ? GROUNDING_UI[v].word : "Not checked", text: g.q ?? g.answers[0].claim_text, n: i + 1, flagged: severity(worst) <= 1 };
  };
  const h = hover !== null ? info(groups[hover], hover) : null;
  const chapters = [...sections].sort((a, b) => a.start_s - b.start_s);
  // Chapter names are written under their chapter on up to two lines. One too long for its stretch of the strip goes on the
  // second row, so it can run on under the next chapter, which takes the first row.
  const labelRows = (() => {
    const end = [-1, -1]; // where the last label in each row stops, in px
    return chapters.map((s, i) => {
      const x = (s.start_s / total) * width;
      const own = (((chapters[i + 1]?.start_s ?? total) - s.start_s) / total) * width - 4;
      const need = Math.ceil(s.title.length / 2) * 5.4 + 8; // two lines of small text
      const w = Math.min(Math.max(own, need), width - x);
      const row = end[0] <= x ? 0 : end[1] <= x ? 1 : end[0] <= end[1] ? 0 : 1;
      const fits = end[row] <= x;
      end[row] = x + (fits ? w : own);
      return { s, x, w: fits ? w : own, row };
    });
  })();
  const rows = labelRows.some((l) => l.row === 1) ? 2 : 1;  return (
    <nav className="qa-index" aria-label={`Jump to a ${noun}`}>
      <div ref={strip} className="qi-strip" onMouseLeave={() => setHover(null)}>
        {chapters.map((s) => <span key={s.idx} className="qi-chap" style={{ left: pct(s.start_s) }} aria-hidden="true" />)}
        {groups.map((g, i) => {
          const x = info(g, i);
          const on = g.answers.some((a) => a.id === activeId) ? "playing" : g.answers.some((a) => a.id === selectedId) ? "picked" : "";
          return (
            <button key={x.first.id} type="button" onClick={() => onJump(x.first)} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
                    className={`qi-bar${x.v ? ` ipt-g-${x.v}` : ""}${x.flagged ? " is-tall" : ""}${on ? ` is-${on}` : ""}`} style={{ left: pct(playFromS(x.first)) }}
                    aria-label={`${noun} ${x.n}, ${clock(playFromS(x.first))}, ${x.word}: ${x.text}`} />
          );
        })}
        <span className="qi-head" style={{ left: pct(time) }} aria-hidden="true" />
        {h && (
          <span className="qi-tip" style={{ left: pct(playFromS(h.first)) }} role="tooltip">
            <b>Q{h.n}</b> · {clock(playFromS(h.first))} · {h.word}
            <span className="qi-tip-text">{h.text}</span>
          </span>
        )}
      </div>
      {chapters.length > 0 && (
        <div className="qi-labels" style={{ height: `${rows * 1.7}rem` }}>
          {labelRows.map(({ s, x, w, row }) => (
            <button key={s.idx} type="button" className="qi-label" style={{ left: x, width: w, top: `${row * 1.7}rem` }} title={`${s.title} · play from ${clock(s.start_s)}`}
                    onClick={() => onSection(s)}>{s.title}</button>
          ))}
        </div>
      )}
    </nav>
  );
}
