"use client";

import { useEffect, useRef, useState } from "react";
import { domain, shortDate } from "@/lib/format";
import type { Research, Source } from "@/lib/types";

const ORIGIN: Record<string, string> = {
  own_organisation: "Published by an organisation the speaker works for or leads",
  same_episode: "This episode's own page or a write-up of it",
};

/**
 * What each search returned. One block per search: the search term at the top, the pages that search returned below it, in the order
 * the search gave them. A page that two searches returned appears under both. Every page counts alike; a note says where a page comes
 * from when it is the speaker's own organisation or this episode's own page. Each page is one short line (title, site, date); the
 * search excerpt opens in a popup when the title is clicked, with a link to the page itself.
 */
export function SearchResults({ research, sources }: { research: Research; sources: Source[] }) {
  const searches = research.searches ?? [];
  if (!searches.length) return null;
  const byUrl = new Map(sources.map((s) => [s.url, s]));
  const [open, setOpen] = useState<Source | null>(null);
  return (
    <section className="sr" aria-label="What each search returned">
      <h4 className="rs-title">Searches and what they returned</h4>
      {searches.map((q, i) => {
        const pages = q.urls.map((u) => byUrl.get(u) ?? ({ url: u, title: null, excerpt: "", publish_date: null, rank: 0 } as Source));
        return (
          <div key={i} className="sr-search">
            <p className="sr-head">
              <span className="sr-n">Search {i + 1}</span>
              <span className="sr-term">“{q.query}”</span>
              <span className="sr-count">{q.failed ? "search failed" : `${pages.length} ${pages.length === 1 ? "page" : "pages"}`}</span>
            </p>
            {pages.length > 0 ? (
              <ol className="sr-items">
                {pages.map((s) => (
                  <li key={s.url}>
                    <button type="button" className="sr-link" onClick={() => setOpen(s)} title="Show the excerpt the search returned">{s.title || domain(s.url)}</button>
                    <span className="meta sr-site">
                      {[domain(s.url), shortDate(s.publish_date)].filter(Boolean).join(" · ")}
                      {s.independence && ORIGIN[s.independence] && <span className="rs-own" title={ORIGIN[s.independence]}>{s.independence === "same_episode" ? "this episode" : "speaker's own organisation"}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            ) : <p className="meta source-none">{q.failed ? "This search failed, so it returned nothing." : "This search returned no pages."}</p>}
          </div>
        );
      })}
      <p className="meta rs-foot">Pages are shown as each search returned them, all treated alike. Click a title to read the excerpt the search gave. Nothing here says who is right.</p>
      <ExcerptPopup page={open} onClose={() => setOpen(null)} />
    </section>
  );
}

/** The excerpt of one page in a popup, with the link to the page. Closes with Escape, the Close button or a click outside. */
function ExcerptPopup({ page, onClose }: { page: Source | null; onClose(): void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (page && !d.open) d.showModal();
    if (!page && d.open) d.close();
  }, [page]);
  return (
    <dialog ref={ref} className="sr-popup" onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }} aria-label="Search excerpt">
      {page && (
        <>
          <h5 className="sr-popup-title">{page.title || domain(page.url)}</h5>
          <p className="meta">{[domain(page.url), shortDate(page.publish_date)].filter(Boolean).join(" · ")}</p>
          <p className="sr-popup-text">{page.excerpt || "The search gave no excerpt for this page."}</p>
          <p className="sr-popup-actions">
            <a className="btn small" href={page.url} target="_blank" rel="noopener noreferrer nofollow">Open the page ↗</a>
            <button type="button" className="btn secondary small" onClick={onClose}>Close</button>
          </p>
        </>
      )}
    </dialog>
  );
}
