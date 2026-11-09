"use client";

import { useEffect, useState } from "react";
import type { Cited, CreatorProfile, EpisodeSpeaker, ProfileV2, Section, Step } from "@/lib/types";
import { IncentiveChips } from "@/components/Indicators";
import { INCENTIVE_UI } from "@/lib/indicators";
import { clock, domain } from "@/lib/format";

type Tab = "summary" | "chapters" | "profiles" | "steps";

const PROFILE_NOTE = "Compiled with AI from public web search results; each fact links to the page it came from, and every view is attributed to who holds it. It describes who they are and what they have a stake in, not whether anything said is right.";

/** The show's hosts and everyone else who speaks. Host details live in the Creator tab and the rest in the Guests tab, so nothing is shown twice. */
export function splitPeople(speakers: EpisodeSpeaker[]): { hosts: EpisodeSpeaker[]; guests: EpisodeSpeaker[] } {
  return { hosts: speakers.filter((x) => x.role === "host"), guests: speakers.filter((x) => x.role !== "host") };
}

/** The Creator tab: the show's profile, which names the hosts. A show without a profile falls back to the hosts' own profiles. */
export function CreatorTab({ creator, hosts }: { creator: CreatorProfile | null; hosts: EpisodeSpeaker[] }) {
  return creator ? <CreatorPanel creator={creator} /> : <PeoplePanel people={hosts} creator={null} />;
}

/**
 * Tabs under the video: the AI summary, the chapters (parts of the conversation), the show's profile, and who speaks.
 * Profiles show neutral facts only; the notes on known positions and criticisms that steer source searches are
 * never sent to the browser.
 */
export function ProfileTabs({ summary, sections, creator, speakers, notes = [], steps = [], onSeek, onSection, showProfiles = 0 }: {
  summary: string | null | undefined; sections: Section[]; creator: CreatorProfile | null; speakers: EpisodeSpeaker[];
  notes?: string[]; // how the description introduces people, and its sponsor lines
  steps?: Step[]; // the steps already finished (done or skipped)
  onSeek(s: number): void;
  onSection?(s: Section): void; // play this chapter and jump the statement list to it
  showProfiles?: number; // a counter: each time it goes up, the Profiles tab opens (the podcast profile's "Full profile")
}) {
  const tabs: { key: Tab; label: string }[] = [
    ...(summary ? [{ key: "summary" as Tab, label: "Summary" }] : []),
    ...(sections.length ? [{ key: "chapters" as Tab, label: `Chapters ${sections.length}` }] : []),
    ...(speakers.length || creator ? [{ key: "profiles" as Tab, label: `Profiles ${speakers.length + (creator ? 1 : 0)}` }] : []),
    ...(steps.length ? [{ key: "steps" as Tab, label: `Steps ${steps.length}` }] : []),
  ];
  const [picked, setTab] = useState<Tab | null>(null);
  const [more, setMore] = useState(false);
  useEffect(() => { if (showProfiles) setTab("profiles"); }, [showProfiles]);
  if (!tabs.length) return null;
  // The first tab until one is picked (the summary or chapters can arrive later, while the video is analysed).
  const tab = picked && tabs.some((t) => t.key === picked) ? picked : tabs[0].key;

  return (
    <section className="ptabs" aria-label="About this video">
      {tabs.length > 1 && (
        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <button key={t.key} role="tab" id={`ptab-${t.key}`} aria-controls={`ppanel-${t.key}`} aria-selected={tab === t.key}
                    className="tab" onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </div>
      )}

      {tab === "summary" && summary && (
        <div role="tabpanel" id="ppanel-summary" aria-labelledby="ptab-summary" className="ppanel">
          <div className="ai-summary">
            <p className="ai-note">AI summary</p>
            <p className={more ? "" : "clamp-3"}>{summary}</p>
            {summary.length > 220 && (
              <button type="button" className="linkish" onClick={() => setMore(!more)}>{more ? "Show less" : "Show more"}</button>
            )}
          </div>
        </div>
      )}

      {tab === "chapters" && (
        <div role="tabpanel" id="ppanel-chapters" aria-labelledby="ptab-chapters" className="ppanel">
          <ol className="sections">
            {sections.map((s) => (
              <li key={s.idx}>
                <button type="button" className="linkish cc-ts" onClick={() => onSeek(s.start_s)} aria-label={`Play from ${clock(s.start_s)}`}>
                  {clock(s.start_s)}
                </button>
                {onSection ? (
                  <button type="button" className="section-body section-go" onClick={() => onSection(s)} title={s.summary || undefined}
                          aria-label={`Play "${s.title}" from ${clock(s.start_s)} and show its statements`}>
                    {s.title}
                  </button>
                ) : (
                  <span className="section-body"><strong>{s.title}</strong>{s.summary && <span className="meta"> {s.summary}</span>}</span>
                )}
              </li>
            ))}
          </ol>
          <p className="meta chapters-note">Chapters are written by AI. Click one to play it and see its statements.</p>
        </div>
      )}

      {tab === "profiles" && (
        <div role="tabpanel" id="ppanel-profiles" aria-labelledby="ptab-profiles" className="ppanel">
          <ProfilesPanel speakers={speakers} creator={creator} notes={notes} />
        </div>
      )}

      {tab === "steps" && (
        <div role="tabpanel" id="ppanel-steps" aria-labelledby="ptab-steps" className="ppanel">
          <ol className="done-steps">
            {steps.map((st) => (
              <li key={st.key} className={`done-step is-${st.status}`}>
                <span className="done-step-icon" aria-hidden="true">{st.status === "skipped" ? "–" : "✓"}</span>
                <span className="done-step-body">
                  <span className="done-step-label">{st.label}{st.status === "skipped" && <span className="meta"> (skipped)</span>}</span>
                  {st.detail && <span className="meta done-step-detail">{st.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}


/**
 * The output of the "Profiling the show, hosts and guests" step, one tab per person (and one for the show), each with the same five
 * sections: About, Business, Politics, Reputation, Stakes. Every answer is compared with the profile of the person who gave it.
 */
export function ProfilesPanel({ speakers, creator, notes }: { speakers: EpisodeSpeaker[]; creator: CreatorProfile | null; notes: string[] }) {
  const people = [...speakers].sort((a, b) => (a.role === "host" ? 0 : 1) - (b.role === "host" ? 0 : 1) || b.statements - a.statements);
  const entries = [
    ...people.map((x) => ({ key: x.label, name: x.speaker?.name ?? x.label, kind: "person" as const, person: x })),
    ...(creator ? [{ key: "__show", name: creator.podcast, kind: "show" as const, person: null }] : []),
  ];
  const [sel, setSel] = useState(entries[0]?.key ?? "");
  const cur = entries.find((e) => e.key === sel) ?? entries[0];
  if (!cur) return null;
  return (
    <>
      <p className="meta">Every answer is compared with the profile of the person who gave it. Pick a person to see theirs.</p>
      {entries.length > 1 && (
        <div className="people-tabs" role="tablist" aria-label="Profiles in this video">
          {entries.map((e) => (
            <button key={e.key} type="button" role="tab" aria-selected={e.key === cur.key} className="person-tab" onClick={() => setSel(e.key)}>
              <span className="person-tab-name">{e.name}</span>
              {e.kind === "show" && <span className="meta">The show</span>}
            </button>
          ))}
        </div>
      )}
      <section className="pf-card" role="tabpanel" aria-label={cur.name}>
        {cur.kind === "show" && creator ? <ShowProfile creator={creator} /> : cur.person ? <PersonProfile key={cur.key} person={cur.person} /> : null}
      </section>
      {notes.length > 0 && (
        <div className="profile-sec">
          <p className="profile-k">What the description says</p>
          <ul className="profile-list">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
      <p className="meta profile-note">{PROFILE_NOTE}</p>
    </>
  );
}

function ShowProfile({ creator }: { creator: CreatorProfile }) {
  const pp = creator.public_profile;
  const lead = (
    <>
      {pp.hosts && <p><span className="profile-k">Hosts</span> {pp.hosts}</p>}
      {pp.known_for && <p><span className="profile-k">Known for</span> {pp.known_for}</p>}
    </>
  );
  return (
    <>
      <h3 className="profile-name">{creator.podcast} <span className="meta">· The show{creator.country ? ` · ${creator.country}` : ""}</span></h3>
      <SectionTabs idp={`pf-show-${creator.id}`} sections={profileSections(pp, lead, { title: "What the show has a stake in", incentives: pp.incentives }, true)} />
    </>
  );
}

function PersonProfile({ person: p }: { person: EpisodeSpeaker }) {
  const sp = p.speaker;
  const pp = (sp?.public_profile ?? {}) as Fields & { role?: string; affiliations?: string[] };
  const name = sp?.name ?? p.label;
  const lead = sp ? (
    <>
      {sp.summary && <p>{sp.summary}</p>}
      {pp.role && <p><span className="profile-k">Role</span> {pp.role}</p>}
      {!!pp.affiliations?.length && <p><span className="profile-k">Affiliations</span> {pp.affiliations.join(", ")}</p>}
    </>
  ) : <p className="meta">No public profile was found for this name, so their answers have nothing to be compared with.</p>;
  const from = sp?.sources?.slice(0, 3) ?? [];
  return (
    <>
      <h3 className="profile-name">{name} <span className="meta">· {p.role === "host" ? "Host" : p.role === "guest" ? "Guest" : "Speaker"}{p.statements ? ` · ${p.statements} ${p.statements === 1 ? "answer" : "answers"}` : ""}</span></h3>
      <SectionTabs idp={`pf-${p.label}`} sections={profileSections(pp, lead, { title: "In this video, a stake in", incentives: p.incentives ?? undefined }, true)} />
      {from.length > 0 && (
        <p className="meta">From: {from.map((x, i) => (
          <span key={x.url}>{i > 0 && ", "}<a href={x.url} target="_blank" rel="noopener noreferrer">{domain(x.url)}</a></span>
        ))}</p>
      )}
    </>
  );
}

const BASIS: Record<string, string> = { declared: "holds or held party or government office", described: "as described by the sources", curated: "editorial note" };

function Src({ x }: { x: Cited }) {
  return x.url ? <> <a className="meta" href={x.url} target="_blank" rel="noopener noreferrer nofollow">{x.site || domain(x.url)}</a></> : null;
}

function CitedList<T extends Cited>({ title, items, text }: { title: string; items?: T[]; text(x: T): string }) {
  if (!items?.length) return null;
  return (
    <div className="profile-sec">
      <p className="profile-k">{title}</p>
      <ul className="profile-list">{items.map((x, i) => <li key={i}>{text(x)}<Src x={x} /></li>)}</ul>
    </div>
  );
}

const RELATION: Record<string, string> = { founder: "Founder", executive: "Executive", investor: "Investor", board: "Board member", advisor: "Advisor", employee: "Works at", owner: "Owner", other: "Tied to" };

/** The profile fields a creator or a person can have: the comprehensive (version 2) ones, and the two older ones (leaning, public opinion). */
type Fields = ProfileV2 & { leaning?: string; leaning_basis?: string; public_opinion?: string; topics?: string[] };
type Sec = { key: string; label: string; body: React.ReactNode };

/**
 * A profile split into short horizontal tabs, so nothing needs scrolling to be found: About, Business (businesses, money,
 * sponsors, ownership), Politics, Reputation (praise, criticism, controversies, bias claims) and, when there are some, Stakes.
 * Tabs with nothing in them are left out, and a profile with one section shows no tab bar.
 */
function profileSections(p: Fields, lead: React.ReactNode, stakes?: { title: string; incentives: Fields["incentives"] }, all = false): Sec[] {
  const none = (text: string) => <p className="meta">{text}</p>;
  const pol = p.political;
  const leaning = pol?.leaning || p.leaning;
  const hasPolitics = !!(leaning || pol?.posts?.length);
  const about = (
    <>
      {lead}
      {p.narrative && <p className="profile-narrative">{p.narrative}</p>}
      {!!p.expertise?.length && <p><span className="profile-k">Expertise</span> {p.expertise.join(", ")}{p.credentials ? <span className="meta"> · {p.credentials}</span> : null}</p>}
      {!!p.topics?.length && <p className="profile-topics">{p.topics.map((t) => <span key={t} className="chip static">{t}</span>)}</p>}
    </>
  );
  const business = (p.businesses?.length || p.financial_interests?.length || p.sponsors?.length || p.ownership?.length) ? (
    <>
      <CitedList title="Businesses and roles" items={p.businesses} text={(b) => `${RELATION[b.relation] ?? "Tied to"}: ${b.name}${b.sector ? ` (${b.sector})` : ""}${b.current === false ? ", former" : ""}`} />
      <CitedList title="Financial interests" items={p.financial_interests} text={(f) => f.what} />
      <CitedList title="Sponsors" items={p.sponsors} text={(x) => `${x.name}${x.category ? ` (${x.category})` : ""}`} />
      <CitedList title="Ownership and funding" items={p.ownership} text={(x) => x.text} />
    </>
  ) : null;
  const politics = hasPolitics ? (
    <p><span className="profile-k">{pol ? "Politics" : "Political leaning"}</span> {[leaning, ...(pol?.posts ?? [])].filter(Boolean).join("; ")}
      {pol ? <Src x={pol} /> : null}
      {!pol && p.leaning_basis && BASIS[p.leaning_basis] ? <span className="meta"> ({BASIS[p.leaning_basis]})</span> : null}</p>
  ) : null;
  const reputation = (p.praise?.length || p.critiques?.length || p.controversy_reports?.length || p.bias_claims?.length || p.public_opinion) ? (
    <>
      {p.public_opinion && <p><span className="profile-k">Public opinion</span> {p.public_opinion}</p>}
      <CitedList title="Praise" items={p.praise} text={(x) => (x.by ? `${x.by}: ` : "") + x.text} />
      <CitedList title="Criticism" items={p.critiques} text={(x) => (x.by ? `${x.by}: ` : "") + x.text} />
      <CitedList title="Controversies" items={p.controversy_reports} text={(x) => x.what + (x.when ? ` (${x.when})` : "")} />
      <CitedList title="Claims of bias or conflicts of interest" items={p.bias_claims} text={(x) => (x.by ? `${x.by}: ` : "") + x.claim} />
    </>
  ) : null;
  const hasStakes = !!stakes?.incentives && Object.keys(stakes.incentives).length > 0;
  const stakesBody = hasStakes
    ? <div className="profile-sec"><p className="profile-k">{stakes!.title}</p><IncentiveChips incentives={stakes!.incentives} detail /></div>
    : null;
  if (all) {  // the same five sections for everyone, so profiles can be compared side by side
    return [
      { key: "about", label: "About", body: about },
      { key: "business", label: "Business", body: business ?? none("No businesses, investments, sponsors or ownership found.") },
      { key: "politics", label: "Politics", body: politics ?? none("No political leaning or post found.") },
      { key: "reputation", label: "Reputation", body: reputation ?? none("No praise, criticism or controversy found.") },
      { key: "stakes", label: "Stakes", body: stakesBody ?? none("No stake was found.") },
    ];
  }
  return [
    { key: "about", label: "About", body: about },
    ...(business ? [{ key: "business", label: "Business", body: business }] : []),
    ...(politics ? [{ key: "politics", label: "Politics", body: politics }] : []),
    ...(reputation ? [{ key: "reputation", label: "Reputation", body: reputation }] : []),
    ...(stakesBody ? [{ key: "stakes", label: "Stakes", body: stakesBody }] : []),
  ];
}

/** Horizontal tabs for the sections of one profile. */
function SectionTabs({ sections, idp }: { sections: Sec[]; idp: string }) {
  const [picked, setPicked] = useState<string | null>(null);
  const cur = sections.find((x) => x.key === picked) ?? sections[0];
  return (
    <>
      {sections.length > 1 && (
        <div className="subtabs" role="tablist" aria-label="Profile sections">
          {sections.map((x) => (
            <button key={x.key} type="button" role="tab" id={`${idp}-${x.key}`} aria-selected={x === cur} className="subtab" onClick={() => setPicked(x.key)}>{x.label}</button>
          ))}
        </div>
      )}
      <div role="tabpanel" aria-labelledby={`${idp}-${cur.key}`} className="subpanel">{cur.body}</div>
    </>
  );
}

/** The show's profile: neutral facts only, in sections. */
export function CreatorPanel({ creator }: { creator: CreatorProfile }) {
  const pp = creator.public_profile;
  const lead = (
    <>
      {pp.hosts && <p><span className="profile-k">Hosts</span> {pp.hosts}</p>}
      {pp.host_bio && <p><span className="profile-k">Background</span> {pp.host_bio}</p>}
      {pp.known_for && <p><span className="profile-k">Known for</span> {pp.known_for}</p>}
    </>
  );
  return (
    <>
      <h2 className="profile-name">{creator.podcast}</h2>
      <p className="meta">
        {[creator.youtube_channel_name, creator.country].filter(Boolean).join(" · ")}
        {creator.youtube_handles.map((h) => (
          <span key={h}> · <a href={`https://www.youtube.com/${h}`} target="_blank" rel="noopener noreferrer">{h}</a></span>
        ))}
      </p>
      <SectionTabs idp={`cr-${creator.id}`} sections={profileSections(pp, lead, { title: "What the show has a stake in", incentives: pp.incentives })} />
      <p className="meta profile-note">{PROFILE_NOTE}</p>
    </>
  );
}

const ROLE_LINE = { host: "Podcast host", guest: "Podcast guest" } as const;
const UNNAMED = /^(the\s+)?(co-?host|host|guest|panel+ist|speaker|narrator|moderator|interviewer|caller|participant)\b/i;

/** The show's hosts from the creator profile: 'Krystal Ball & Saagar Enjeti' -> ["Krystal Ball", "Saagar Enjeti"]. */
function hostNames(creator: CreatorProfile | null): string[] {
  return (creator?.public_profile.hosts ?? "").split(/,|&|\band\b/).map((x) => x.replace(/"[^"]*"|\([^)]*\)/g, "").replace(/\s+/g, " ").trim())
    .filter((x) => x && !/\b(cast|crew|ensemble)\b/i.test(x));
}

/** One person's profile in horizontal tabs: what they do, their businesses and money, politics, reputation, and their stake in this video. */
function PersonSections({ person: p }: { person: EpisodeSpeaker }) {
  const pp = p.speaker!.public_profile;
  const lead = (
    <>
      {p.speaker!.summary && <p>{p.speaker!.summary}</p>}
      {pp.role && <p><span className="profile-k">Role</span> {pp.role}</p>}
      {!!pp.affiliations?.length && <p><span className="profile-k">Affiliations</span> {pp.affiliations.join(", ")}</p>}
    </>
  );
  const from = p.speaker!.sources?.slice(0, 3) ?? [];
  return (
    <>
      <SectionTabs idp={`pp-${p.label}`} sections={profileSections(pp, lead, { title: "In this video, a stake in", incentives: p.incentives ?? undefined })} />
      {from.length > 0 && (
        <p className="meta">From: {from.map((x, i) => (
          <span key={x.url}>{i > 0 && ", "}<a href={x.url} target="_blank" rel="noopener noreferrer">{domain(x.url)}</a></span>
        ))}</p>
      )}
    </>
  );
}

/** Everyone who speaks in the video, one tab each: name, role (podcast host / guest), profile when one was found.
 *  Shows can have one host or several, any number of guests, or a narrator; the roles come from the video. */
export function PeoplePanel({ people, creator }: { people: EpisodeSpeaker[]; creator: CreatorProfile | null }) {
  const order = [...people].sort((a, b) => (a.role === "host" ? 0 : a.role === "guest" ? 1 : 2) - (b.role === "host" ? 0 : b.role === "guest" ? 1 : 2)
    || b.statements - a.statements);
  const [sel, setSel] = useState(order[0]?.label ?? "");
  if (!order.length) return <p className="meta">People appear once the host and guests have been profiled.</p>;
  const p = order.find((x) => x.label === sel) ?? order[0];
  const name = (x: EpisodeSpeaker) => x.speaker?.name ?? x.label;
  const role = p.role ? ROLE_LINE[p.role] : "Speaker";
  const hosts = hostNames(creator);
  return (
    <>
      {order.length > 1 && (
        <div className="people-tabs" role="tablist" aria-label="People in this video">
          {order.map((x) => (
            <button key={x.label} type="button" role="tab" aria-selected={x.label === p.label} className="person-tab" onClick={() => setSel(x.label)}>
              <span className="person-tab-name">{name(x)}</span>
            </button>
          ))}
        </div>
      )}
      <div className="person" role="tabpanel">
        <h3 className="profile-name">{name(p)}</h3>
        <p className="meta person-role">{role}{creator && p.role === "host" ? ` · ${creator.podcast}` : ""}{p.statements ? ` · ${p.statements} ${p.statements === 1 ? "statement" : "statements"}` : ""}</p>
        {p.speaker ? (
          <PersonSections key={p.label} person={p} />
        ) : p.role === "host" && hosts.length > 1 ? (
          <p>Not named in the video. One of the show&apos;s hosts: {hosts.join(" or ")}.</p>
        ) : UNNAMED.test(p.label) ? (
          <p className="meta">Not named in the video, so there is no profile.</p>
        ) : (
          <p className="meta">No public profile found for this name.</p>
        )}
      </div>
      <p className="meta profile-note">{PROFILE_NOTE} Names and roles are identified by AI from the video.</p>
    </>
  );
}
