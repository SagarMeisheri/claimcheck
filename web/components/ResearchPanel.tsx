import type { Research } from "@/lib/types";

export const RESEARCH_NOTE =
  "The AI picked the points of the answer that can be checked and searched the web for each one, including searches for other views. Every page the searches returned is listed under Sources, all treated alike; only the search excerpts were read. None of this says who is right.";

/** What was searched: the points of the answer that can be checked, and the queries. The pages themselves are under Sources. */
export function ResearchPanel({ research }: { research: Research }) {
  const points = research.points ?? [];
  if (!points.length) return null;
  return (
    <section className="rs" aria-label="How this answer was researched">
      <h4 className="rs-title">What was checked</h4>
      {points.map((p, i) => (
        <div key={i} className="rs-point">
          <p className="rs-point-text">{p.text}</p>
        </div>
      ))}
      {research.positions?.length > 0 && <p className="meta">Positions looked for: {research.positions.join("; ")}.</p>}
      {!research.searches?.length && (
        <details className="fold">
          <summary>{research.queries?.length ?? 0} searches, {research.pages?.length ?? 0} pages found</summary>
          <ul className="nclist">{(research.queries ?? []).map((q, i) => <li key={i}>{q}</li>)}</ul>
        </details>
      )}
      <p className="meta rs-foot">{RESEARCH_NOTE}</p>
    </section>
  );
}
