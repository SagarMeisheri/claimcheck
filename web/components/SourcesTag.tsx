"use client";

import { useState } from "react";
import type { PreviewClaim } from "@/lib/types";
import { MATCH_MEANING, MATCH_WORD } from "@/components/SourceList";
import { domain } from "@/lib/format";

const MAX_ICONS = 3;

/** A website's own icon (through /api/icon), or its first letter when it has none. */
export function SiteIcon({ site }: { site: string }) {
  const [failed, setFailed] = useState(false);
  return failed ? (
    <span className="site-icon site-icon-letter" title={site}>{site.slice(0, 1).toUpperCase()}</span>
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img className="site-icon" src={`/api/icon/${encodeURIComponent(site)}`} alt="" title={site} width={16} height={16}
         loading="lazy" onError={() => setFailed(true)}
         // The error can fire before the page is interactive, and then onError never runs: check once mounted too.
         ref={(img) => { if (img?.complete && img.naturalWidth === 0) setFailed(true); }} />
  );
}

/**
 * The sources of a statement whose lookup is done: the icons of the first few websites (search order), then "+N" for
 * the rest. (The match shows as the colour of the statement text.) Opens the sources panel.
 */
export function SourcesTag({ c, onOpen, label = false }: {
  c: Pick<PreviewClaim, "sources" | "counter_sources" | "sources_route" | "sources_match">; onOpen(): void; label?: boolean;
}) {
  const all = [...c.sources, ...c.counter_sources];
  const sites = [...new Set(all.map((s) => domain(s.url)))].slice(0, MAX_ICONS);
  const shown = all.filter((s, i) => sites.includes(domain(s.url)) && all.findIndex((x) => domain(x.url) === domain(s.url)) === i).length;
  const more = all.length - shown;
  const match = c.sources_match;
  const what = `${all.length} ${all.length === 1 ? "source" : "sources"}${match ? `, ${MATCH_WORD[match].toLowerCase()} match` : ""}`;
  return (
    <button type="button" className={`tl-tag${match ? ` is-${match}` : ""}`} onClick={onOpen}
            title={match ? `${what}. ${MATCH_MEANING[match]}` : what} aria-label={`Sources: ${all.length ? what : "none found"}. Open`}>
      {label && <span className="tl-tag-label">Sources</span>}
      {all.length === 0 ? <span className="tl-tag-none">No sources found</span> : (
        <span className="site-icons" aria-hidden="true">
          {sites.map((s) => <SiteIcon key={s} site={s} />)}
          {more > 0 && <span className="site-more">+{more}</span>}
        </span>
      )}
    </button>
  );
}
