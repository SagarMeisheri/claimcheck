"use client";

import { useState, type ReactNode } from "react";
import { CheckedAt } from "@/components/CheckedAt";
import { clock } from "@/lib/format";
import {
  ANSWER_UI, DYNAMIC_UI, GROUNDING_UI, INCENTIVE_UI, PATTERN_UI, QUESTION_UI, VERDICT_ORDER, interviewProfile, keyFindings, proofOf, verdictOf,
  type IndicatorUi, type TagFilter,
} from "@/lib/indicators";
import { STATEMENT_TYPES } from "@/lib/statements";
import type { AnswerType, Claim, CreatorProfile, EpisodeSpeaker, Incentive, IncentiveTag, Interaction, ProfileV2, QuestionType, StatementType, Tldr } from "@/lib/types";

export type Sort = "time" | "worst";

const Q_ORDER: QuestionType[] = ["factual", "explanatory", "experiential", "evaluative", "speculative", "challenging", "unclear"];
const A_ORDER: AnswerType[] = ["direct", "narrative", "structured", "pivot", "evasive", "unclear"];
const NOTE = "Tagged by AI from the questions, the answers, the speakers' profiles and web pages. It describes what was found and can be wrong.";

const sameFilter = (a: TagFilter | null, b: TagFilter) => !!a && a.dim === b.dim && a.key === b.key;

/**
 * One section of the profile: its label and a one-sentence TL;DR. The tags behind it (the chips, each a filter) open with "tags", or are
 * open from the start (`defaultOpen`). `after` sits at the end of the sentence.
 */
function TldrRow({ label, hint, text, children, defaultOpen = false, after }: {
  label: string; hint: string; text: ReactNode; children?: ReactNode; defaultOpen?: boolean; after?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="pp-row">
      <span className="pp-label" title={hint}>{label}</span>
      <div className="pp-cell">
        <p className="pp-text">
          {text}
          {children && <button type="button" className="linkish pp-tags" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "tags ▴" : "tags ▾"}</button>}
          {after}
        </p>
        {children && open && <div className="pp-chips">{children}</div>}
      </div>
    </div>
  );
}

/** One tag's chip: glyph, word and count. Clicking it shows only those answers; clicking it again clears. */
function Tag({ tone, glyph, word, n, on, hint, onClick, style }: {
  tone: string; glyph: string; word: string; n: number; on: boolean; hint: string; onClick(): void; style?: React.CSSProperties;
}) {
  return (
    <button type="button" className={`ind ip-tag ${tone}`} aria-pressed={on} title={`${hint} Click to show only these.`} onClick={onClick} style={style}>
      <span className="ind-glyph" aria-hidden="true">{glyph}</span><span className="ind-word">{word}</span> <b>{n}</b>
    </button>
  );
}

function Tags<K extends string>({ order, counts, ui, dim, filter, onTag }: {
  order: K[]; counts: Record<K, number>; ui: Record<K, IndicatorUi>; dim: "q" | "a" | "g"; filter: TagFilter | null; onTag(f: TagFilter | null): void;
}) {
  return (
    <>
      {order.filter((k) => counts[k] > 0).map((k) => {
        const f = { dim, key: k } as TagFilter;
        return <Tag key={k} tone={`ipt-${dim}-${k}`} glyph={ui[k].glyph} word={ui[k].word} n={counts[k]} on={sameFilter(filter, f)} hint={ui[k].hint}
                    onClick={() => onTag(sameFilter(filter, f) ? null : f)} />;
      })}
    </>
  );
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const top = <K extends string>(counts: Record<K, number>, ui: Record<K, IndicatorUi>, n = 2) =>
  (Object.entries(counts) as [K, number][]).filter(([k, c]) => c > 0 && k !== "unclear").sort((a, b) => b[1] - a[1]).slice(0, n).map(([k]) => ui[k].word.toLowerCase());

/** What the sections say until the AI has written its own TL;DRs (older videos): the same facts, counted here. */
function fallbackTldr(p: NonNullable<ReturnType<typeof interviewProfile>> | null, typeCounts: Partial<Record<StatementType, number>>, verdicts: { g: string; n: number }[],
                      conflicts: number, stakes: number): Omit<Tldr, "people" | "headline"> {
  const types = (Object.entries(typeCounts) as [StatementType, number][]).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const q = p ? top(p.questions, QUESTION_UI) : [];
  const a = p ? p.answers : null;
  return {
    questions: !p || !p.asked ? "" : `Mostly ${q.join(" and ")} questions; ${p.questions.challenging ? plural(p.questions.challenging, "real pushback", "real pushbacks") : "no real pushback"}.`,
    answers: !a || !p?.answered ? "" : `${a.direct} of ${p.answered} answered directly${a.pivot + a.evasive ? `; ${[a.pivot && plural(a.pivot, "pivot", "pivots"), a.evasive && `${a.evasive} evasive`].filter(Boolean).join(", ")}` : ""}.`,
    statements: types.length ? `Mostly ${STATEMENT_TYPES[types[0][0]].plural} (${types[0][1]} of ${types.reduce((n, [, c]) => n + c, 0)}).` : "",
    evidence: verdicts.filter((x) => x.n).map((x) => `${x.n} ${GROUNDING_UI[x.g as keyof typeof GROUNDING_UI].word.toLowerCase()}`).join(", ") + (verdicts.length ? "." : ""),
    flags: conflicts || stakes || p?.patterns.length ? [conflicts && plural(conflicts, "conflict", "conflicts"), stakes && plural(stakes, "stake", "stakes"), p?.patterns.length && plural(p.patterns.length, "pattern", "patterns")].filter(Boolean).join(", ") + "." : "None found.",
  };
}

/** Whether answers have been checked since the TL;DRs were written. */
function isStale(t: Tldr | undefined, claims: Claim[]): boolean {
  if (!t?.counts) return false;
  const rows = claims.filter((c) => c.question && c.not_checked_reason !== "outside_policy");
  const now: Record<string, number> = { answers: rows.length };
  for (const g of VERDICT_ORDER) now[g] = rows.filter((c) => verdictOf(c) === g).length;
  return Object.entries(t.counts).some(([k, n]) => k in now && now[k] !== n);
}

type Fields = ProfileV2 & { role?: string; leaning?: string; known_for?: string; hosts?: string };
type Who = { key: string; role: string; name: string; about: string; fields: Fields; incentives: Partial<Record<IncentiveTag, Incentive>> | null | undefined };

const short = (t: string, n: number) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);

/** Everyone the profile covers, in the order of the Profiles tab: hosts, then guests by how much they said, then the show. */
function whoIs(speakers: EpisodeSpeaker[], creator: CreatorProfile | null): Who[] {
  const people = [...speakers].sort((a, b) => (a.role === "host" ? 0 : 1) - (b.role === "host" ? 0 : 1) || b.statements - a.statements).map((x): Who => {
    const f = (x.speaker?.public_profile ?? {}) as Fields;
    return { key: x.label, role: x.role === "host" ? "Host" : x.role === "guest" ? "Guest" : "Speaker", name: x.speaker?.name ?? x.label,
             about: f.role || x.speaker?.summary || "", fields: f, incentives: x.incentives };
  });
  const show: Who[] = creator ? [{ key: "__show", role: "Show", name: creator.podcast, about: creator.public_profile.known_for || creator.summary || "",
                                  fields: creator.public_profile as Fields, incentives: creator.public_profile.incentives }] : [];
  return [...people, ...show];
}

/** One person's TL;DR; their profile sections (About, Business, Politics, Reputation, Stakes) open with "tags". */
function Person({ w, tldr, onOpen }: { w: Who; tldr?: string; onOpen(): void }) {
  const f = w.fields;
  const business = [...(f.businesses ?? []).map((b) => b.name), ...(f.financial_interests ?? []).map((x) => x.what), ...(f.sponsors ?? []).map((x) => x.name), ...(f.ownership ?? []).map((x) => x.text)];
  const rep = { praise: f.praise?.length ?? 0, criticism: f.critiques?.length ?? 0, controversies: f.controversy_reports?.length ?? 0, bias: f.bias_claims?.length ?? 0 };
  const repN = rep.praise + rep.criticism + rep.controversies + rep.bias;
  const leaning = f.political?.leaning || f.leaning || "";
  const stakes = (Object.entries(w.incentives ?? {}) as [IncentiveTag, Incentive][]).filter(([k]) => k in INCENTIVE_UI);
  const fact = (label: string, value: string, title: string) => (
    <span className={`pp-fact${value ? "" : " is-none"}`} title={title}><b>{label}</b> {value || "none found"}</span>
  );
  return (
    <TldrRow label={w.role} hint={`${w.role}: every answer is compared with the profile of the person who gave it.`}
             text={<><b className="pp-who">{w.name}</b> {tldr || w.about || "No public profile was found."}</>}
             after={<button type="button" className="linkish pp-open" onClick={onOpen}>Full profile ›</button>}>
      {fact("About", short(w.about, 60), w.about)}
      {fact("Business", business.length ? String(business.length) : "", business.slice(0, 6).join("; "))}
      {fact("Politics", short(leaning, 28), [leaning, ...(f.political?.posts ?? [])].filter(Boolean).join("; "))}
      {fact("Reputation", repN ? String(repN) : "", `${rep.praise} praise, ${rep.criticism} criticism, ${rep.controversies} controversies, ${rep.bias} claims of bias`)}
      <span className="pp-fact" title="What this person has a stake in, for this video."><b>Stakes</b>{stakes.length === 0 && " none found"}</span>
      {stakes.map(([k, v]) => (
        <span key={k} className={`ind is-${INCENTIVE_UI[k].tone}`} title={`${INCENTIVE_UI[k].hint} ${v.reason}`}>
          <span className="ind-glyph" aria-hidden="true">{INCENTIVE_UI[k].glyph}</span><span className="ind-word">{INCENTIVE_UI[k].word}</span>
        </span>
      ))}
    </TldrRow>
  );
}

/**
 * The podcast profile, pinned at the top of the feed. It starts with a one-sentence TL;DR of the whole video, then one row per
 * section, each with its own one-sentence TL;DR written by AI (pipeline agents/tldr.py): Questions (how the host asked), Answers (how
 * they were answered), Statements (what kinds), Evidence (what the pages found), Flags (conflicts, stakes, patterns), then each speaker
 * and the show. The tags behind a sentence (every chip with its count, each a filter: click to show only those answers, again to clear)
 * open with "tags"; Evidence starts open as the main filter. Older videos show the same sentences counted here until the AI has written
 * its own. Under the rows: sort, Play in order and the lookup button. It can be folded to its title line.
 */
export function PodcastProfile({ claims, interaction, total, noun, withSources, searching, checkedAt, typeCounts, chipTypes, view, onView, tag, onTag, onAll,
  sort, onSort, playAll, onPlayAll, onStop, checkAll, onJump, speakers, creator, onOpenProfiles }: {
  claims: Claim[]; interaction?: Interaction | null; total: number; noun: string; withSources: number; searching: number; checkedAt: string | null;
  typeCounts: Partial<Record<StatementType, number>>; chipTypes: StatementType[];
  view: string; onView(v: "all" | "with_sources" | StatementType): void; tag: TagFilter | null; onTag(f: TagFilter | null): void; onAll(): void;
  sort: Sort; onSort(s: Sort): void; playAll: "idle" | "running" | "hidden"; onPlayAll(): void; onStop(): void;
  checkAll: ReactNode; onJump(c: Claim): void;
  speakers: EpisodeSpeaker[]; creator: CreatorProfile | null; onOpenProfiles(): void; // the people's profile sections, shown as rows
}) {
  const [folded, setFolded] = useState(false);
  const p = interviewProfile(claims);
  const dyn = interaction?.dynamic ? DYNAMIC_UI[interaction.dynamic] : null;
  const verdicts = VERDICT_ORDER.map((g) => ({ g, n: claims.filter((c) => verdictOf(c) === g).length })).filter((x) => x.n > 0);
  const conflicts = claims.filter((c) => c.qa_tags?.conflict).length;
  const stakes = claims.filter((c) => c.qa_tags?.stake).length;
  const nothingPicked = !tag && view === "all";
  const who = whoIs(speakers, creator);
  const ai = interaction?.tldr;
  const fb = fallbackTldr(p, typeCounts, verdicts, conflicts, stakes);
  const say = (k: "questions" | "answers" | "statements" | "evidence" | "flags") => ai?.[k] || fb[k];
  const stale = isStale(ai, claims);
  const flagTag = (key: "conflict" | "stake"): TagFilter => ({ dim: "f", key });
  return (
    <section className="pp" aria-label="Podcast profile">
      <div className="pp-head">
        <h3 className="pp-title">Podcast profile <span className="op-ai" title={NOTE}>AI-tagged</span></h3>
        {dyn && <span className={`ind is-${dyn.tone}`} title={`Dynamic: ${dyn.word}. ${dyn.hint}`}><span className="ind-cat">Dynamic</span><span className="ind-glyph" aria-hidden="true">{dyn.glyph}</span><span className="ind-word">{dyn.word}</span></span>}
        <span className="meta pp-meta">
          {total} {noun} · {withSources} with sources{searching > 0 && ` · searching ${searching} now`}
          {checkedAt && <> · <CheckedAt iso={checkedAt} prefix="last checked" /></>}
        </span>
        <button type="button" className="linkish pp-fold" aria-expanded={!folded} onClick={() => setFolded((f) => !f)}>{folded ? "Show summary ▾" : "Hide summary ▴"}</button>
      </div>
      {ai?.headline && (
        <p className="pp-headline">
          {ai.headline}
          {stale && <span className="meta pp-stale" title="Answers were checked again after this summary was written. It is rewritten the next time a check finishes."> · out of date</span>}
        </p>
      )}
      {verdicts.length > 0 && (
        <p className="ip-bar pp-bar" role="img" aria-label={`Evidence: ${verdicts.map((x) => `${x.n} ${GROUNDING_UI[x.g].word.toLowerCase()}`).join(", ")}`}>
          {verdicts.map((x) => <span key={x.g} className={`ipt-g-${x.g}`} style={{ flexGrow: x.n }} />)}
        </p>
      )}

      <div className="pp-body" hidden={folded}>
        <div className="pp-rows">
          {p && p.asked > 0 && (
            <TldrRow label="Questions" hint="How the host asked each question, tagged without seeing the answer." text={say("questions")}>
              <Tags order={Q_ORDER} counts={p.questions} ui={QUESTION_UI} dim="q" filter={tag} onTag={onTag} />
            </TldrRow>
          )}
          {p && p.answered > 0 && (
            <TldrRow label="Answers" hint="How each question was answered." text={say("answers")}>
              <Tags order={A_ORDER} counts={p.answers} ui={ANSWER_UI} dim="a" filter={tag} onTag={onTag} />
            </TldrRow>
          )}
          <TldrRow label="Statements" hint="What kind of statement each answer is, as tagged when the video was read." text={say("statements")}>
            {chipTypes.map((t) => (
              <Tag key={t} tone="" glyph="●" word={STATEMENT_TYPES[t].label} n={typeCounts[t] ?? 0} on={view === t} hint={STATEMENT_TYPES[t].meaning}
                   style={{ ["--tone" as string]: STATEMENT_TYPES[t].cssVar }} onClick={() => (view === t ? onView("all") : onView(t))} />
            ))}
            <button type="button" className="ind ip-tag" aria-pressed={view === "with_sources"} onClick={() => onView(view === "with_sources" ? "all" : "with_sources")}
                    title="Answers that have web sources. Click to show only these.">
              <span className="ind-glyph" aria-hidden="true">↗</span><span className="ind-word">With sources</span> <b>{withSources}</b>
            </button>
          </TldrRow>
          {verdicts.length > 0 && (
            <TldrRow label="Evidence" hint="Whether the pages found back the answer." text={say("evidence")} defaultOpen>
              <Tags order={VERDICT_ORDER} counts={Object.fromEntries(verdicts.map((x) => [x.g, x.n])) as Record<(typeof VERDICT_ORDER)[number], number>}
                    ui={GROUNDING_UI} dim="g" filter={tag} onTag={onTag} />
            </TldrRow>
          )}
          {p && (conflicts > 0 || stakes > 0 || p.patterns.length > 0) && (
            <TldrRow label="Flags" hint="What was found about the speakers' own interests, and patterns across the interview." text={say("flags")}>
              {conflicts > 0 && (
                <Tag tone="is-amber" glyph="◆" word="Conflict" n={conflicts} on={sameFilter(tag, flagTag("conflict"))}
                     hint="Answers that favour something in the speaker's own profile." onClick={() => onTag(sameFilter(tag, flagTag("conflict")) ? null : flagTag("conflict"))} />
              )}
              {stakes > 0 && (
                <Tag tone="is-amber" glyph="◇" word="Stake" n={stakes} on={sameFilter(tag, flagTag("stake"))}
                     hint="Answers that tie to something in the speaker's profile." onClick={() => onTag(sameFilter(tag, flagTag("stake")) ? null : flagTag("stake"))} />
              )}
              {p.patterns.map((x, i) => (
                <button key={i} type="button" className="ind is-amber" title={`${PATTERN_UI[x.kind].hint} Click to go to it.`} onClick={() => onJump(x.claim)}>
                  <span className="ind-glyph" aria-hidden="true">⚑</span><span className="ind-word">{PATTERN_UI[x.kind].word}</span> <span className="meta">{clock(x.claim.start_s)}</span>
                </button>
              ))}
            </TldrRow>
          )}
        </div>

        {who.length > 0 && (
          <div className="pp-rows pp-people">
            {who.map((w) => <Person key={w.key} w={w} tldr={ai?.people?.[w.key]} onOpen={onOpenProfiles} />)}
          </div>
        )}
      </div>

      <div className="pp-tools">
        <button type="button" className="chip" aria-pressed={nothingPicked} onClick={onAll}>All {total}</button>
        <span className="pp-sort" role="group" aria-label="Sort the answers">
          <span className="stmt-filter-label">Sort</span>
          <button type="button" className="chip" aria-pressed={sort === "time"} onClick={() => onSort("time")}>Timeline</button>
          <button type="button" className="chip" aria-pressed={sort === "worst"} onClick={() => onSort("worst")} title="Contradicted first, then the rest by how much they need a look">Worst first</button>
        </span>
        {playAll !== "hidden" && (
          <span className="pp-play">
            <button type="button" className="btn secondary small" onClick={onPlayAll}>▶ Play in order</button>
            {playAll === "running" && <button type="button" className="btn secondary small" onClick={onStop}>Stop</button>}
          </span>
        )}
        {checkAll}
      </div>
    </section>
  );
}

/** The few answers that most need a look, above the feed: click one to jump to its card. */
export function KeyFindings({ claims, onJump }: { claims: Claim[]; onJump(c: Claim): void }) {
  const [all, setAll] = useState(false);
  const items = keyFindings(claims);
  if (items.length === 0) return null;
  const shown = all ? items : items.slice(0, 3);
  return (
    <section className="kf" aria-label="Key findings">
      <h3 className="kf-title"><span aria-hidden="true">⚑</span> Key findings <span className="op-ai" title={NOTE}>AI-tagged</span></h3>
      <ol className="kf-list">
        {shown.map((c) => {
          const g = verdictOf(c);
          const flagged = g === "contradicted" || g === "ungrounded";
          const proof = flagged ? proofOf(c) : null;
          const said = c.qa_tags?.grounding?.contradiction;
          const notes = [c.qa_tags?.conflict && "Conflict", c.qa_tags?.stake && "Stake", c.qa_tags?.answer && ["pivot", "evasive"].includes(c.qa_tags.answer.type) && (c.qa_tags.answer.type === "pivot" ? "Pivot" : "Evasive")]
            .filter(Boolean).join(" · ");
          return (
            <li key={c.id}>
              <button type="button" className={`kf-item${g ? ` ipt-g-${g}` : " is-amber"}`} onClick={() => onJump(c)}>
                <span className="kf-glyph" aria-hidden="true">{flagged && g ? GROUNDING_UI[g].glyph : "◆"}</span>
                <span className="kf-time">{clock(c.start_s)}</span>
                <span className="kf-body">
                  <span className="kf-q">{c.question ?? c.claim_text}</span>
                  <span className="kf-why">
                    {flagged && g && <b>{GROUNDING_UI[g].word}</b>}{notes && <>{flagged ? " · " : ""}{notes}</>}
                    {said ? <> — {said.difference}</> : proof && <> — {proof.text}</>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {items.length > 3 && (
        <button type="button" className="linkish kf-all" onClick={() => setAll((a) => !a)}>{all ? "Show fewer" : `Show all ${items.length}`}</button>
      )}
    </section>
  );
}
