import { domain, shortDate } from "@/lib/format";
import type { Research, Source } from "@/lib/types";

const ORIGIN: Record<string, string> = {
  own_organisation: "Published by an organisation the speaker works for or leads",
  same_episode: "This episode's own page or a write-up of it",
};

/**
 * What each search returned. One block per search: the search term at the top, the pages that search returned below it, in the order
 * the search gave them. A page that two searches returned appears under both. Every page counts alike; a note says where a page comes
 * from when it is the speaker's own organisation or this episode's own page. The pages' text is the search excerpt.
 */
export function SearchResults({ research, sources }: { research: Research; sources: Source[] }) {
  const searches = research.searches ?? [];
  if (!searches.length) return null;
  const byUrl = new Map(sources.map((s) => [s.url, s]));
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
                    <a className="source-title" href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title || domain(s.url)}</a>
                    <p className="meta source-site">
                      {[domain(s.url), shortDate(s.publish_date)].filter(Boolean).join(" · ")}
                      {s.independence && ORIGIN[s.independence] && <span className="rs-own" title={ORIGIN[s.independence]}>{s.independence === "same_episode" ? "this episode" : "speaker's own organisation"}</span>}
                    </p>
                    {s.excerpt && <p className="source-excerpt">{s.excerpt}</p>}
                  </li>
                ))}
              </ol>
            ) : <p className="meta source-none">{q.failed ? "This search failed, so it returned nothing." : "This search returned no pages."}</p>}
          </div>
        );
      })}
      <p className="meta rs-foot">Pages are shown as each search returned them, all treated alike, with the excerpt the search gave. Nothing here says who is right.</p>
    </section>
  );
}
