"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import type { PreviewClaim, StatementType } from "@/lib/types";
import { TopicTags } from "@/components/TopicTags";
import { InlineVerify, type InlineResult } from "./InlineVerify";
import { STATEMENT_TYPES, TYPE_ORDER, totalStatements, typeOf } from "@/lib/statements";
import { VERDICTS, clock, domain, scoreLabel, topicHue, topicLabel } from "@/lib/verdicts";

type Counts = Partial<Record<StatementType, number>>;
type Tab = "all" | StatementType;

function Card({ videoId, c, videoPending, active, topic, onTopic, onPlay }: {
  videoId: string; c: PreviewClaim; videoPending: boolean; active: boolean; topic: string | null; onTopic(t: string): void;
  onPlay(c: PreviewClaim): void;
}) {
  // A verdict can arrive while the page is open (the Verify button below), so the card keeps its own copy.
  const [result, setResult] = useState<InlineResult | null>(null);
  const [busy, setBusy] = useState(false);
  const onBusy = useCallback((b: boolean) => setBusy(b), []);
  const onDone = useCallback((r: InlineResult) => setResult(r), []);

  const verdict = c.verdict ?? result?.outcome?.verdict ?? null;
  const v = verdict ? VERDICTS[verdict] : null;
  const score = scoreLabel(result?.outcome?.score);
  const src = result?.outcome?.sources[0];
  const sourceLine = c.source_line ?? (src ? `${src.title ?? domain(src.url)}: ${src.quote}` : null);
  const awaiting = c.awaiting_review || result?.status === "awaiting_review";
  const t = STATEMENT_TYPES[typeOf(c.statement_type)];
  const factual = typeOf(c.statement_type) === "factual_claim";
  const verifiable = factual && !v && !awaiting;
  const cls = `ccard${active ? " is-active" : ""}${v ? " is-verdict" : " ccard-statement"}${busy ? " is-verifying" : ""}`;
  return (
    <article className={cls} role="listitem"
             style={{ ["--stype" as string]: t.cssVar, ["--vc" as string]: v ? v.cssVar : undefined }}>
      {/* Clicking a statement plays the video from its timestamp, right here on the home page. */}
      <button type="button" className="ccard-main ccard-playbtn" disabled={videoPending} onClick={() => onPlay(c)}
              aria-label={`Play the video from ${clock(c.start_s)}: ${c.claim_text}`}>
        <span className="ccard-head">
          <span className="ts">▶ {clock(c.start_s)}</span>
          <span className="stype-tag"><span className="bd-dot" style={{ background: t.cssVar }} aria-hidden="true" />{t.label}</span>
          {active && <span className="cc-playing">Playing</span>}
        </span>
        {v && (
          <span className="ccard-verdict">
            <span className="vbadge" style={{ background: v.cssVar }}>{v.label.toUpperCase()}</span>
            {score && <span className="vscore">{score}</span>}
          </span>
        )}
        <span className="ccard-text">{c.claim_text}</span>
        {v && sourceLine && <span className="ccard-src" style={{ borderColor: v.cssVar }}>{sourceLine}</span>}
        {awaiting && <span className="meta">Verified, with a reviewer</span>}
      </button>
      <TopicTags topics={c.topics} active={topic} onPick={onTopic} />
      {verifiable && !videoPending ? (
        <div className="ccard-foot">
          <InlineVerify claimId={c.id} status={c.verification_status} onBusy={onBusy} onDone={onDone} />
        </div>
      ) : (v || factual) && (
        <Link href={`/v/${videoId}#claim-${c.id}`} className="ccard-play">
          {v ? "Sources and details" : "Open in the video page"}
        </Link>
      )}
    </article>
  );
}

/** Tabs for the carousel: every statement type this video has, with counts. */
function TypeTabs({ counts, tab, onTab, verified }: { counts: Counts; tab: Tab; onTab(t: Tab): void; verified: number }) {
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
      <span className="meta stmt-tabs-note">{verified} verified</span>
    </div>
  );
}

/** Row under a video: tabs by statement type, then that type's statements (verified claims first). */
export function StatementCarousel({ videoId, statements, verifiedCount, counts, videoPending = false, activeId = null, onPlay }: {
  videoId: string; statements: PreviewClaim[]; verifiedCount: number; counts: Counts;
  videoPending?: boolean; activeId?: string | null; onPlay(c: PreviewClaim): void;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const [topic, setTopic] = useState<string | null>(null);
  const total = totalStatements(counts);
  if (!total && !statements.length) return null;
  const inTab = tab === "all" ? statements : statements.filter((c) => typeOf(c.statement_type) === tab);
  const topicCounts = new Map<string, number>();
  for (const c of inTab) for (const t of c.topics ?? []) topicCounts.set(t, (topicCounts.get(t) ?? 0) + 1);
  const chips = [...topicCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  // With a subject chosen, show every match; otherwise the first 14 of "All".
  const list = topic ? inTab.filter((c) => c.topics?.includes(topic)) : tab === "all" ? inTab.slice(0, 14) : inTab;
  const hidden = topic ? 0 : (tab === "all" ? total : counts[tab] ?? 0) - list.length;
  const pick = (t: string) => setTopic((cur) => (cur === t ? null : t));
  return (
    <div className="stmt-carousel">
      <TypeTabs counts={counts} tab={tab} onTab={setTab} verified={verifiedCount} />
      {chips.length > 1 && (
        <div className="topic-filters stmt-topics" role="group" aria-label="Filter by subject">
          {chips.map(([t, n]) => (
            <button key={t} type="button" className="topic-tag" aria-pressed={topic === t} onClick={() => pick(t)}
                      style={{ ["--th" as string]: topicHue(t) }}>
              {topicLabel(t)} <span className="tag-n">{n}</span>
            </button>
          ))}
          {topic && <button type="button" className="topic-tag topic-clear" onClick={() => setTopic(null)}>Clear ×</button>}
        </div>
      )}
      <div className="carousel" role="list" aria-label="Statements in this video">
        {list.map((c) => <Card key={c.id} videoId={videoId} c={c} videoPending={videoPending} active={activeId === c.id} topic={topic} onTopic={pick} onPlay={onPlay} />)}
        <Link href={`/v/${videoId}`} className="ccard ccard-more" role="listitem">
          {hidden > 0 ? `See ${hidden} more` : "Open the video page"}
        </Link>
      </div>
    </div>
  );
}
