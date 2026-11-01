"use client";

import { useEffect, useMemo, useState } from "react";
import { readFollows } from "@/lib/follows";
import type { Episode, Pestle } from "@/lib/types";
import { PESTLE } from "@/lib/verdicts";
import { TopicsView } from "./TopicsView";
import { VideoCard } from "./VideoCard";

type Tab = "latest" | "topics" | "following";
type Filter = { kind: "area"; area: Pestle } | { kind: "track"; track: Episode["channel_track"] } | null;

export function FeedView({ episodes }: { episodes: Episode[] }) {
  const [tab, setTab] = useState<Tab>("latest");
  const [filter, setFilter] = useState<Filter>(null);
  const [q, setQ] = useState("");
  const [follows, setFollows] = useState<string[]>([]);
  useEffect(() => setFollows(readFollows()), []);

  const areas = (Object.keys(PESTLE) as Pestle[]).filter((a) => episodes.some((e) => e.pestle_areas?.includes(a)));
  const shown = useMemo(() => {
    let list = episodes;
    if (tab === "following") list = list.filter((e) => e.channel_id && follows.includes(e.channel_id));
    if (filter?.kind === "area") {
      list = list.filter((e) => e.pestle_areas?.includes(filter.area))
        .map((e) => ({ ...e, published_claims: e.published_claims?.filter((c) => c.pestle_area === filter.area) }));
    }
    if (filter?.kind === "track") list = list.filter((e) => e.channel_track === filter.track);
    const needle = q.trim().toLowerCase();
    if (needle) {
      list = list.filter((e) => [e.title, e.channel_name, e.guest ?? "", ...(e.claim_texts ?? [])]
        .some((t) => t.toLowerCase().includes(needle)));
    }
    return list;
  }, [episodes, tab, filter, q, follows]);

  const tabBtn = (t: Tab, label: string) => (
    <button role="tab" aria-selected={tab === t} className="tab" onClick={() => setTab(t)}>{label}</button>
  );
  const chip = (f: Filter, label: string) => {
    const on = JSON.stringify(f) === JSON.stringify(filter);
    return <button key={label} className="chip" aria-pressed={on} onClick={() => setFilter(on ? null : f)}>{label}</button>;
  };

  return (
    <div className="feed-layout">
      <div className="feed-controls">
        <div className="tabs" role="tablist" aria-label="Feed">
          {tabBtn("latest", "Latest")}
          {tabBtn("topics", "Topics")}
          {tabBtn("following", "Following")}
        </div>
        <label className="search">
          <span className="visually-hidden">Search videos, channels and claims</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search videos, guests or claims" />
        </label>
        <div className="filters" role="group" aria-label="Filter by topic">
          {chip({ kind: "track", track: "politics" }, "Politics")}
          {chip({ kind: "track", track: "finance_health" }, "Money and health")}
          {areas.map((a) => chip({ kind: "area", area: a }, PESTLE[a]))}
        </div>
      </div>
      {shown.length === 0 ? (
        <div className="empty">
          {tab === "following" && follows.length === 0
            ? <p>Follow a channel from its page to see its checked videos here.</p>
            : <p>No checked videos match these filters yet.</p>}
          {(filter || q) && <button className="btn secondary" onClick={() => { setFilter(null); setQ(""); }}>Clear filters</button>}
        </div>
      ) : tab === "topics" ? (
        <TopicsView episodes={shown} />
      ) : (
        <div className="vgrid">
          {shown.map((e, i) => <VideoCard key={e.id} ep={e} eager={i < 3} />)}
        </div>
      )}
    </div>
  );
}
