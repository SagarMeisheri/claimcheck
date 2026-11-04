"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import type { PreviewClaim, SourcesMatch, StatementType } from "@/lib/types";
import { CheckSources } from "@/components/CheckSources";
import { SourceList } from "@/components/SourceList";
import { STATEMENT_TYPES, TYPE_ORDER, hasSources, totalStatements, typeOf } from "@/lib/statements";
import { clock } from "@/lib/format";
import { MatchFilter, matchCounts } from "@/components/MatchFilter";

type Counts = Partial<Record<StatementType, number>>;
type Tab = "all" | StatementType;

function Card({ videoId, c, active, onPlay }: {
  videoId: string; c: PreviewClaim; active: boolean; onPlay(c: PreviewClaim): void;
}) {
  const [busy, setBusy] = useState(false);
  const onBusy = useCallback((b: boolean) => setBusy(b), []);
  const t = STATEMENT_TYPES[typeOf(c.statement_type)];
  const sourceable = c.sources_status !== "not_eligible" && hasSources(c.statement_type); // not questions or stories
  const cls = `ccard ccard-statement${active ? " is-active" : ""}${busy ? " is-verifying" : ""}`;
  return (
    <article className={cls} role="listitem" style={{ ["--stype" as string]: t.cssVar }}>
      {/* Clicking a statement plays the video from its timestamp, right here on the home page. */}
      <button type="button" className="ccard-main ccard-playbtn" onClick={() => onPlay(c)}
              aria-label={`Play the video from ${clock(c.start_s)}: ${c.claim_text}`}>
        <span className="ccard-head">
          <span className="ts">▶ {clock(c.start_s)}</span>
          <span className="stype-tag"><span className="bd-dot" style={{ background: t.cssVar }} aria-hidden="true" />{t.label}</span>
          {active && <span className="cc-playing">Playing</span>}
        </span>
        <span className="ccard-text">{c.claim_text}</span>
      </button>
      {sourceable && (
        <div className="ccard-foot">
          {c.sources_status === "done"
            ? <SourceList sources={c.sources} summary={c.sources_summary} match={c.sources_match} counter={c.counter_sources}
                          counterSummary={c.counter_summary} route={c.sources_route} compact />
            : (c.sources_status === "not_requested" || c.sources_status === "failed" || c.sources_status === "queued" || c.sources_status === "searching")
              && <CheckSources claimId={c.id} status={c.sources_status} error={null} route={c.sources_route} compact onBusy={onBusy} />}
          <Link href={`/v/${videoId}#claim-${c.id}`} className="ccard-play">Open in the video page</Link>
        </div>
      )}
    </article>
  );
}

/** Tabs for the carousel: every statement type this video has, with counts. */
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

const PAGE_SIZE = 8;

/** Page numbers with gaps: 1 … 4 5 6 … 12 */
function pageList(page: number, pages: number): (number | "gap")[] {
  const keep = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const out: (number | "gap")[] = [];
  let last = 0;
  for (const n of [...keep].sort((x, y) => x - y)) { if (n - last > 1) out.push("gap"); out.push(n); last = n; }
  return out;
}

/** Row under a video: tabs by statement type, source match chips, then that selection's statements, a page at a time. */
export function StatementCarousel({ videoId, statements, withSources, counts, activeId = null, onPlay }: {
  videoId: string; statements: PreviewClaim[]; withSources: number; counts: Counts; activeId?: string | null; onPlay(c: PreviewClaim): void;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const [match, setMatch] = useState<SourcesMatch | null>(null);
  const [page, setPage] = useState(1);
  const total = totalStatements(counts);
  if (!total && !statements.length) return null;
  const inTab = tab === "all" ? statements : statements.filter((c) => typeOf(c.statement_type) === tab);
  const list = match ? inTab.filter((c) => c.sources_match === match) : inTab;
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  const cur = Math.min(page, pages);
  const shown = list.slice((cur - 1) * PAGE_SIZE, cur * PAGE_SIZE);
  const changeTab = (t: Tab) => { setTab(t); setMatch(null); setPage(1); };
  return (
    <div className="stmt-carousel">
      <TypeTabs counts={counts} tab={tab} onTab={changeTab} withSources={withSources} />
      <MatchFilter counts={matchCounts(inTab)} value={match} onChange={(m) => { setMatch(m); setPage(1); }} />
      <div className="carousel" role="list" aria-label="Statements in this video">
        {shown.map((c) => <Card key={c.id} videoId={videoId} c={c} active={activeId === c.id} onPlay={onPlay} />)}
        {shown.length === 0 && <p className="meta ccard-empty">No statements match.</p>}
      </div>
      {pages > 1 && (
        <nav className="pager" aria-label="Statement pages">
          <button type="button" className="pager-btn" disabled={cur === 1} onClick={() => setPage(cur - 1)} aria-label="Previous page">‹</button>
          {pageList(cur, pages).map((n, i) => n === "gap"
            ? <span key={`g${i}`} className="pager-gap" aria-hidden="true">…</span>
            : <button key={n} type="button" className="pager-btn" aria-current={n === cur ? "page" : undefined} onClick={() => setPage(n)}>{n}</button>)}
          <button type="button" className="pager-btn" disabled={cur === pages} onClick={() => setPage(cur + 1)} aria-label="Next page">›</button>
          <span className="meta pager-count">{(cur - 1) * PAGE_SIZE + 1}–{Math.min(cur * PAGE_SIZE, list.length)} of {list.length}</span>
        </nav>
      )}
    </div>
  );
}
