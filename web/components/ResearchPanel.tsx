import type { Assessment, BiasKind, Camp, CampStance, Grounding, Opinion, PointStatus, Research, ResearchFinding } from "@/lib/types";

/** Plain-words status of one point of an answer. Neutral: describes what independent pages say, never who is right. */
export const POINT_STATUS: Record<PointStatus, string> = {
  same: "An independent source says the same",
  different: "An independent source gives a different figure",
  different_scope: "Differs in period or definition",
  other_position: "Another position found",
  mixed: "Independent sources differ",
  own_organisation_only: "Only the speaker's own organisation",
  no_independent_source: "No independent source found",
};

const RELATION: Record<ResearchFinding["relation"], string> = {
  same: "Says the same", different: "Gives a different figure", different_scope: "Different period or definition", other_position: "Another position",
};

export const RESEARCH_NOTE =
  "The AI split the answer into points that can be checked, searched for each one (including searches for other views), and read the pages. Pages from the speaker's own organisation and from this episode's own write-ups are not counted as independent. Each quote is the page's exact words, checked against the page. None of this says who is right.";

/** A short chip per point, for the card. */
export function PointChips({ research }: { research: Research | null | undefined }) {
  const points = research?.points ?? [];
  if (!points.length) return null;
  return (
    <ul className="rs-chips" aria-label="What was checked">
      {points.map((p, i) => <li key={i} className={`rs-chip is-${p.status}`} title={p.text}><b>{POINT_STATUS[p.status]}.</b> {p.text}</li>)}
    </ul>
  );
}

function Finding({ f }: { f: ResearchFinding }) {
  return (
    <li className="rs-finding">
      <p className="rs-f-head">
        <a href={f.url} target="_blank" rel="noopener noreferrer nofollow">{f.site || f.title}</a>
        <span className="rs-rel">{RELATION[f.relation]}</span>
        {f.independence === "own_organisation" && <span className="rs-own" title="Published by the organisation the speaker works for or leads">speaker&apos;s own organisation</span>}
      </p>
      <p className="rs-f-text">{f.finding}</p>
      {f.quote && <blockquote className="rs-quote">“{f.quote}”</blockquote>}
    </li>
  );
}

/** Per point: what independent pages say, with the page's own words. Then other positions, grouped by stance. */
export function ResearchPanel({ research }: { research: Research }) {
  const answering = research.points;
  const positions = new Map<string, ResearchFinding[]>();
  for (const p of research.points) for (const f of p.findings) {
    if (f.relation === "other_position") positions.set(f.position || "Other", [...(positions.get(f.position || "Other") ?? []), f]);
  }
  const dropped = Object.values(research.dropped ?? {}).reduce((a, b) => a + b, 0);
  return (
    <section className="rs" aria-label="How this answer was checked">
      <h4 className="rs-title">What was checked</h4>
      {answering.map((p, i) => {
        const direct = p.findings.filter((f) => f.relation !== "other_position");
        return (
          <div key={i} className={`rs-point is-${p.status}`}>
            <p className="rs-point-text">{p.text}</p>
            <p className="rs-status">{POINT_STATUS[p.status]}</p>
            {direct.length > 0 && <ul className="rs-findings">{direct.map((f, j) => <Finding key={j} f={f} />)}</ul>}
          </div>
        );
      })}
      {positions.size > 0 && (
        <div className="rs-positions">
          <h5>Other positions found</h5>
          {[...positions].map(([label, fs]) => (
            <div key={label} className="rs-position">
              <p className="rs-pos-label">{label}</p>
              <ul className="rs-findings">{fs.map((f, j) => <Finding key={j} f={f} />)}</ul>
            </div>
          ))}
        </div>
      )}
      <p className="meta rs-foot">
        Read {research.pages?.length ?? 0} pages from {research.queries.length} searches{dropped ? `; ${dropped} set aside (the speaker's own organisation, this episode's write-ups, or quotes that could not be checked)` : ""}. {RESEARCH_NOTE}
      </p>
    </section>
  );
}

// --- Opinion assessment: how an opinion is backed, what the two sides say, quoted bias signals -------------------------------

export const GROUNDING_LABEL: Record<Grounding, string> = {
  backed: "Backed by independent sources", partly_backed: "Partly backed by independent sources", unverified: "No independent source found for it",
  not_backed: "Independent sources give a different account", value_judgement: "A value judgement: nothing to check",
};
const SIDE: Record<Camp, string> = { ruling: "the governing side", opposition: "the opposition" };
export function biasLabel(a: Assessment): string {
  if (a.bias === "balanced") return "Balanced";
  if (a.bias === "cant_tell") return "Can't tell";
  const to = a.toward !== "none" ? ` ${SIDE[a.toward]}'s position` : "";
  return a.bias === "leans" ? `Leans toward${to || " one side"}` : `One-sided, toward${to || " one side"}`;
}
const KIND_LABEL: Record<BiasKind, string> = {
  stake: "Stake", prior_stance: "Earlier position", camp_match: "Matches a stated position", one_sided: "Presented as settled", loaded_language: "Loaded wording",
  selective_use: "Selective facts", leading_question: "Leading question", other_view_acknowledged: "Weighs another view",
};
export const OPINION_NOTE =
  "Written by AI from the answer, the speaker's and the show's public profiles, and web pages. Every quote was checked against its source. It describes evidence and is not a verdict on the speaker.";

/** The card's summary: the bottom line and two short labels. */
export function OpinionChips({ research }: { research: Research | null | undefined }) {
  const o = research?.opinion;
  if (!o) return null;
  const a = o.assessment;
  return (
    <div className="op-card" aria-label="Assessment of this opinion">
      {a.bottom_line && <p className="op-line"><b>In short.</b> {a.bottom_line}</p>}
      <p className="op-chips">
        <span className={`op-chip is-${a.grounding}`}>{GROUNDING_LABEL[a.grounding]}</span>
        <span className={`op-chip is-bias-${a.bias}`}>{biasLabel(a)}</span>
        <span className="op-ai" title={OPINION_NOTE}>AI-assessed</span>
      </p>
    </div>
  );
}

function Stance({ camp, label, items }: { camp: Camp; label: string; items: CampStance[] }) {
  return (
    <div className={`op-side is-${camp}`}>
      <p className="op-side-name">{camp === "ruling" ? "Governing side" : "Opposition"} <span className="meta">{label}</span></p>
      {items.length === 0 ? <p className="meta">No recent public statement found on this issue.</p> : (
        <ul className="rs-findings">
          {items.map((s, i) => (
            <li key={i} className="rs-finding">
              <p className="rs-f-head"><a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.who || s.site}</a><span className="rs-rel">{s.site}{s.date ? `, ${s.date.slice(0, 10)}` : ""}</span></p>
              <p className="rs-f-text">{s.stance}</p>
              <blockquote className="rs-quote">“{s.quote}”</blockquote>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The detail panel: grounding, the two sides on the issue, then the bias read with every signal and its quote. */
export function OpinionPanel({ opinion }: { opinion: Opinion }) {
  const a = opinion.assessment;
  const used = a.signals.map((n) => opinion.signals[n - 1]).filter(Boolean);
  return (
    <section className="op" aria-label="Assessment of this opinion">
      <h4 className="rs-title">Assessment <span className="op-ai" title={OPINION_NOTE}>AI-assessed</span></h4>
      {a.bottom_line && <p className="op-line">{a.bottom_line}</p>}
      <div className="op-block">
        <p className="op-label">Is it backed by sources or data?</p>
        <p className="op-value">{GROUNDING_LABEL[a.grounding]}</p>
        {a.grounding_reason && <p className="meta">{a.grounding_reason}</p>}
      </div>
      <div className="op-block">
        <p className="op-label">What each side says{opinion.issue ? ` on: ${opinion.issue}` : ""}</p>
        <Stance camp="ruling" label={opinion.camps.ruling} items={opinion.stances.ruling} />
        <Stance camp="opposition" label={opinion.camps.opposition} items={opinion.stances.opposition} />
      </div>
      <div className="op-block">
        <p className="op-label">Does the answer show slant?</p>
        <p className="op-value">{biasLabel(a)}</p>
        {a.bias_reason && <p className="meta">{a.bias_reason}</p>}
        {(used.length > 0 ? used : opinion.signals).length > 0 && (
          <ul className="rs-findings">
            {(used.length > 0 ? used : opinion.signals).map((s, i) => (
              <li key={i} className="rs-finding">
                <p className="rs-f-head"><span className="rs-rel">{KIND_LABEL[s.kind]}</span></p>
                <p className="rs-f-text">{s.text}</p>
                <blockquote className="rs-quote">“{s.quote}”</blockquote>
              </li>
            ))}
          </ul>
        )}
      </div>
      {(a.objection || a.speaker_record || a.stake) && (
        <div className="op-block">
          {a.objection && <p className="rs-f-text"><b>Strongest other view.</b> {a.objection}</p>}
          {a.speaker_record && <p className="rs-f-text"><b>Speaker&apos;s record.</b> {a.speaker_record}</p>}
          {a.stake && <p className="rs-f-text"><b>Stake.</b> {a.stake}</p>}
        </div>
      )}
      <p className="meta rs-foot">Evidence: {a.evidence}. {OPINION_NOTE}</p>
    </section>
  );
}
