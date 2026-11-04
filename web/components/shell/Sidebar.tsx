"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { SidebarVideo } from "@/lib/types";

const RUNNING = ["queued", "processing"];
const SEARCH_FROM = 8; // show the search box once the list is this long

/**
 * The app's left column: brand, "New video" and every analysed video, newest first. On phones it is a drawer
 * opened from the top bar. Refreshes itself while any video is still being analysed.
 */
export function Sidebar({ videos }: { videos: SidebarVideo[] }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const activeId = pathname.match(/^\/v\/([^/]+)/)?.[1] ?? null;

  // Close the phone drawer after navigating, and on Escape.
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const running = videos.some((v) => RUNNING.includes(v.status));
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => router.refresh(), 15000);
    return () => window.clearInterval(id);
  }, [running, router]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? videos.filter((v) => `${v.title} ${v.channel}`.toLowerCase().includes(needle)) : videos;
  }, [videos, q]);

  return (
    <>
      <div className="topbar">
        <button type="button" className="iconbtn topbar-menu" aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen(true)}
                aria-label="Show your videos">
          <span aria-hidden="true">☰</span>
        </button>
        <Link href="/" className="brand">ClaimCheck</Link>
        <Link href="/" className="btn small topbar-new">New video</Link>
      </div>

      {open && <div className="sidebar-scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <aside id="sidebar" className={`sidebar${open ? " is-open" : ""}`} aria-label="Videos">
        <div className="sidebar-top">
          <Link href="/" className="brand">ClaimCheck</Link>
          <button type="button" className="iconbtn sidebar-close" onClick={() => setOpen(false)} aria-label="Close">✕</button>
        </div>
        <Link href="/" className="sidebar-new" aria-current={pathname === "/" ? "page" : undefined}>
          <span aria-hidden="true">+</span> New video
        </Link>

        {videos.length >= SEARCH_FROM && (
          <label className="sidebar-search">
            <span className="visually-hidden">Find a video</span>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a video" />
          </label>
        )}

        <nav className="sidebar-list" aria-label="Analysed videos">
          {videos.length === 0 ? (
            <p className="sidebar-empty">Videos you analyse appear here.</p>
          ) : shown.length === 0 ? (
            <p className="sidebar-empty">No video matches “{q.trim()}”.</p>
          ) : (
            <ul>
              {shown.map((v) => {
                const busy = RUNNING.includes(v.status);
                return (
                  <li key={v.id}>
                    <Link href={`/v/${v.videoId}`} className="sv" aria-current={v.videoId === activeId ? "page" : undefined}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img className="sv-thumb" src={`https://i.ytimg.com/vi/${v.videoId}/mqdefault.jpg`} alt="" loading="lazy" width={320} height={180} />
                      <span className="sv-text">
                        <span className="sv-title">{v.title}</span>
                        <span className="sv-meta">
                          {busy
                            ? <><span className="spinner" aria-hidden="true" /> {v.status === "queued" ? "Waiting to start" : "Analysing"}</>
                            : <><span className="sv-channel">{v.channel}</span>{v.statements > 0 && <span className="sv-count" title={`${v.statements} statements`}>{v.statements}<span className="visually-hidden"> statements</span></span>}</>}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </nav>

        <nav className="sidebar-foot" aria-label="About">
          <Link href="/method">How it works</Link>
          <Link href="/privacy">Privacy</Link>
        </nav>
      </aside>
    </>
  );
}
