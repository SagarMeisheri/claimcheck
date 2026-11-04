"use client";

import { useCallback, useMemo, useState } from "react";
import type { PreviewClaim, Section, SourcesMatch, StatementType } from "@/lib/types";
import { CheckSources, type SourcesResult } from "@/components/CheckSources";
import { SourcesTag } from "@/components/SourcesTag";
import { STATEMENT_TYPES, TYPE_ORDER, hasSources, totalStatements, typeOf } from "@/lib/statements";
import { clock } from "@/lib/format";
import { MatchFilter, matchCounts } from "@/components/MatchFilter";
import { MATCH_MEANING, MATCH_WORD } from "@/components/SourceList";
import { SourcesDrawer } from "./SourcesDrawer";

type Counts = Partial<Record<StatementType, number>>;
type Tab = "all" | StatementType;
const PAGE_SIZE = 10;
/** One statement in the timeline: time, type, text and a small sources tag. It never changes size: sources open in
 *  the drawer, and "Check sources" shows its progress in the same small space. */
export function TimelineItem({ c, active, selected = false, onPlay, onSelect, onOpen, onLookedUp }: {
  c: PreviewClaim; active: boolean; selected?: boolean; onPlay(c: PreviewClaim): void;
  onSelect?(c: PreviewClaim): void; // the video page: the text selects the statement (its detail opens); home: it plays
  onOpen(c: PreviewClaim): void; onLookedUp(c: PreviewClaim, r: SourcesResult): void;
}) {
  const [busy, setBusy] = useState(false);
  const onBusy = useCallback((b: boolean) => setBusy(b), []);
  const t = STATEMENT_TYPES[typeOf(c.statement_type)];
  const sourceable = c.sources_status !== "not_eligible" && hasSources(c.statement_type); // not questions or stories
  const done = c.sources_status === "done";
  const isQuestion = typeOf(c.statement_type) === "question";
  const match = sourceable && done ? c.sources_match : null; // colours the text: direct / partial / loose
  return (
    <li id={`card-${c.id}`} className={`tl-item${active ? " is-active" : ""}${selected ? " is-selected" : ""}${busy ? " is-verifying" : ""}`}
        style={{ ["--stype" as string]: t.cssVar }} aria-current={selected ? "true" : undefined}>
      <button type="button" className="tl-time" onClick={() => onPlay(c)} aria-label={`Play from ${clock(c.start_s)}`}>{clock(c.start_s)}</button>
      <span className="bd-dot tl-dot" style={{ background: t.cssVar }} title={t.label} aria-hidden="true" />
      <button type="button" className={`tl-text${isQuestion ? " is-question" : ""}${match ? ` m-${match}` : ""}`} onClick={() => (onSelect ?? onPlay)(c)}
              title={match ? `${MATCH_WORD[match]} match: ${MATCH_MEANING[match]}` : undefined}
              aria-label={`${t.label} at ${clock(c.start_s)}: ${c.claim_text}.${match ? ` ${MATCH_WORD[match]} source match.` : ""} ${onSelect ? "Show details" : "Play from here"}`}>
        {c.claim_text}
      </button>
      <div className="tl-action">
        {sourceable && done && <SourcesTag c={c} onOpen={() => onOpen(c)} />}
        {sourceable && !done && ["not_requested", "failed", "queued", "searching"].includes(c.sources_status) && (
          <span className={`tl-check${c.sources_route === "skip" ? " is-skip" : ""}`}>
            <CheckSources claimId={c.id} status={c.sources_status} error={null} route={null} compact onBusy={onBusy}
                          onDone={(r) => onLookedUp(c, r)} />
          </span>
        )}
      </div>
    </li>
  );
}

/** Tabs for the timeline: every statement type this video has, with counts. */
function TypeTabs({ counts, tab, onTab, withSources }: { counts: Counts; tab: Tab; onTab(t: Tab): void; withSources: number }) {
  const types = TYPE_ORDER.filter((t) => counts[t]);
  const total = totalStatements(counts);
  return (
    <div className="stmt-tabs" role="tablist" aria-label="Statement type">
      <button role="tab" aria-selected={tab === "all"} className="stmt-tab" onClick={() => onTab("all")}>
        All <span className="meta">{total}</span>
      </button>
      {types.map((t) => (
        <button key={t} role="tab" aria-selected={tab === t} className="stmt-tab" onClick={() => onTab(t)}
                style={{ ["--stype" as string]: STATEMENT_TYPES[t].cssVar }}>
          <span className="bd-dot" style={{ background: STATEMENT_TYPES[t].cssVar }} aria-hidden="true" />
          {STATEMENT_TYPES[t].label} <span className="meta">{counts[t]}</span>
        </button>
      ))}
      <span className="meta stmt-tabs-note">{withSources} with sources</span>
    </div>
  );
}

type Placed = { start_s: number; section_idx: number | null };
export type Group<T extends Placed> = { key: string; section: Section | null; items: T[] };

/** Statements under their section headings, in order. A section split across pages is headed on both. */
export function groupBySection<T extends Placed>(items: T[], sections: Section[]): Group<T>[] {
  const byIdx = new Map(sections.map((s) => [s.idx, s]));
  const at = (c: T) => (c.section_idx != null ? byIdx.get(c.section_idx) : undefined)
    ?? [...sections].reverse().find((s) => s.start_s <= c.start_s) ?? null;
  const out: Group<T>[] = [];
  for (const c of items) {
    const s = at(c);
    const key = s ? `s${s.idx}` : "none";
    if (out.length && out[out.length - 1].key === key) out[out.length - 1].items.push(c);
    else out.push({ key, section: s, items: [c] });
  }
  return out;
}

/** Under a video: tabs by statement type, source match chips, the page numbers, then that page's statements as a
 *  timeline grouped by the parts of the conversation. Sources open in a drawer, so the page never shifts. */
export function StatementCarousel({ videoId, statements, sections = [], withSources, counts, activeId = null, onPlay }: {
  videoId: string; statements: PreviewClaim[]; sections?: Section[]; withSources: number; counts: Counts;
  activeId?: string | null; onPlay(c: PreviewClaim): void;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const [match, setMatch] = useState<SourcesMatch | null>(null);
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);
  // Lookups finished on this page since it loaded: their results, so the tag and the drawer show them at once.
  const [looked, setLooked] = useState<Record<string, PreviewClaim>>({});
  const all = useMemo(() => statements.map((c) => looked[c.id] ?? c), [statements, looked]);

  const total = totalStatements(counts);
  if (!total && !all.length) return null;
  const inTab = tab === "all" ? all : all.filter((c) => typeOf(c.statement_type) === tab);
  const list = match ? inTab.filter((c) => c.sources_match === match) : inTab;
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  const cur = Math.min(page, pages);
  const shown = list.slice((cur - 1) * PAGE_SIZE, cur * PAGE_SIZE);
  const groups = groupBySection(shown, sections);
  const changeTab = (t: Tab) => { setTab(t); setMatch(null); setPage(1); };

  // The drawer steps through the statements in the current tab that have sources.
  const withSrc = list.filter((c) => c.sources_status === "done");
  const openAt = withSrc.findIndex((c) => c.id === openId);
  const opened = openAt >= 0 ? withSrc[openAt] : null;
  const goTo = (i: number) => {
    const c = withSrc[i];
    if (!c) return;
    setOpenId(c.id);
    const p = Math.floor(list.indexOf(c) / PAGE_SIZE) + 1;
    if (p !== cur) setPage(p);
  };
  const lookedUp = (c: PreviewClaim, r: SourcesResult) => {
    setLooked((m) => ({ ...m, [c.id]: { ...c, sources_status: "done", sources: r.sources ?? [], sources_summary: r.summary ?? null,
      sources_match: r.match ?? null, counter_sources: r.counter ?? [], counter_summary: r.counter_summary ?? null,
      sources_route: r.route ?? c.sources_route } }));
  };

  return (
    <div className="stmt-carousel">
      <TypeTabs counts={counts} tab={tab} onTab={changeTab} withSources={withSources} />
      <MatchFilter counts={matchCounts(inTab)} value={match} onChange={(m) => { setMatch(m); setPage(1); }} />
      {pages > 1 && (
        <nav className="pager" aria-label="Statement pages">
          <button type="button" className="pager-btn" disabled={cur === 1} onClick={() => setPage(cur - 1)} aria-label="Previous page">‹</button>
          {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
            <button key={n} type="button" className="pager-btn" aria-current={n === cur ? "page" : undefined} onClick={() => setPage(n)}>{n}</button>
          ))}
          <button type="button" className="pager-btn" disabled={cur === pages} onClick={() => setPage(cur + 1)} aria-label="Next page">›</button>
          <span className="meta pager-count">{(cur - 1) * PAGE_SIZE + 1}–{Math.min(cur * PAGE_SIZE, list.length)} of {list.length}</span>
        </nav>
      )}
      {shown.length === 0 ? <p className="meta ccard-empty">No statements match.</p> : (
        <div className="timeline" aria-label="Statements in this video, by part of the conversation">
          {groups.map((g, gi) => (
            <section key={`${g.key}-${gi}`} className="tl-group">
              {g.section && (
                <header className="tl-head">
                  <button type="button" className="tl-head-time" onClick={() => onPlay({ ...g.items[0], id: "", start_s: g.section!.start_s })}
                          aria-label={`Play this part from ${clock(g.section.start_s)}`}>{clock(g.section.start_s)}</button>
                  <h3 className="tl-title">{g.section.title}</h3>
                  {g.section.summary && <p className="tl-summary">{g.section.summary}</p>}
                </header>
              )}
              <ol className="tl-list">
                {g.items.map((c) => (
                  <TimelineItem key={c.id} c={c} active={activeId === c.id} onPlay={onPlay} onOpen={(x) => setOpenId(x.id)} onLookedUp={lookedUp} />
                ))}
              </ol>
            </section>
          ))}
        </div>
      )}
      {opened && (
        <SourcesDrawer videoId={videoId} claim={opened} hasPrev={openAt > 0} hasNext={openAt < withSrc.length - 1}
                       onPrev={() => goTo(openAt - 1)} onNext={() => goTo(openAt + 1)} onClose={() => setOpenId(null)}
                       onPlay={(c) => { setOpenId(null); onPlay(c); }} />
      )}
    </div>
  );
}
