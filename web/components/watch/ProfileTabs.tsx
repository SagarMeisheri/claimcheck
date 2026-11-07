"use client";

import { useState } from "react";
import type { Cited, CreatorProfile, EpisodeSpeaker, ProfileV2, Section } from "@/lib/types";
import { IncentiveChips } from "@/components/Indicators";
import { clock, domain } from "@/lib/format";

type Tab = "summary" | "chapters" | "creator" | "speakers";

const PROFILE_NOTE = "Compiled with AI from public web search results; each fact links to the page it came from, and every view is attributed to who holds it. It describes who they are and what they have a stake in, not whether anything said is right.";

/**
 * Tabs under the video: the AI summary, the chapters (parts of the conversation), the show's profile, and who speaks.
 * Profiles show neutral facts only; the notes on known positions and criticisms that steer source searches are
 * never sent to the browser.
 */
export function ProfileTabs({ summary, sections, creator, speakers, onSeek, onSection }: {
  summary: string | null | undefined; sections: Section[]; creator: CreatorProfile | null; speakers: EpisodeSpeaker[];
  onSeek(s: number): void;
  onSection?(s: Section): void; // play this chapter and jump the statement list to it
}) {
  const tabs: { key: Tab; label: string }[] = [
    ...(summary ? [{ key: "summary" as Tab, label: "Summary" }] : []),
    ...(sections.length ? [{ key: "chapters" as Tab, label: `Chapters ${sections.length}` }] : []),
    ...(creator ? [{ key: "creator" as Tab, label: "Creator" }] : []),
    ...(speakers.length ? [{ key: "speakers" as Tab, label: `People ${speakers.length}` }] : []),
  ];
  const [picked, setTab] = useState<Tab | null>(null);
  const [more, setMore] = useState(false);
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

      {tab === "creator" && creator && (
        <div role="tabpanel" id="ppanel-creator" aria-labelledby="ptab-creator" className="ppanel profile">
          <CreatorPanel creator={creator} />
        </div>
      )}

      {tab === "speakers" && (
        <div role="tabpanel" id="ppanel-speakers" aria-labelledby="ptab-speakers" className="ppanel">
          <PeoplePanel people={speakers} creator={creator} />
        </div>
      )}
    </section>
  );
}


const BASIS: Record<string, string> = { declared: "holds or held party or government office", described: "as described by the sources", curated: "editorial note" };

/** The two profile sections found by the live search: political leaning (attributed, with its basis) and public opinion (praise and criticism, attributed). */
function LeaningAndOpinion({ p }: { p: { leaning?: string; leaning_basis?: string; public_opinion?: string } }) {
  if (!p.leaning && !p.public_opinion) return null;
  return (
    <>
      {p.leaning && <p><span className="profile-k">Political leaning</span> {p.leaning}{p.leaning_basis && BASIS[p.leaning_basis] ? <span className="meta"> ({BASIS[p.leaning_basis]})</span> : null}</p>}
      {p.public_opinion && <p><span className="profile-k">Public opinion</span> {p.public_opinion}</p>}
    </>
  );
}

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

/** The comprehensive (version 2) part of a profile: expertise, money, politics and how they are seen, each fact cited. */
function ProfileDetails({ p }: { p: ProfileV2 }) {
  const pol = p.political;
  return (
    <>
      {p.narrative && <p className="profile-narrative">{p.narrative}</p>}
      {!!p.expertise?.length && <p><span className="profile-k">Expertise</span> {p.expertise.join(", ")}{p.credentials ? <span className="meta"> · {p.credentials}</span> : null}</p>}
      <CitedList title="Businesses and roles" items={p.businesses} text={(b) => `${RELATION[b.relation] ?? "Tied to"}: ${b.name}${b.sector ? ` (${b.sector})` : ""}${b.current === false ? ", former" : ""}`} />
      <CitedList title="Financial interests" items={p.financial_interests} text={(f) => f.what} />
      {pol && (pol.leaning || pol.posts?.length) ? (
        <p><span className="profile-k">Politics</span> {[pol.leaning, ...(pol.posts ?? [])].filter(Boolean).join("; ")}<Src x={pol} /></p>
      ) : null}
      <CitedList title="Sponsors" items={p.sponsors} text={(x) => `${x.name}${x.category ? ` (${x.category})` : ""}`} />
      <CitedList title="Ownership and funding" items={p.ownership} text={(x) => x.text} />
      <CitedList title="Praise" items={p.praise} text={(x) => (x.by ? `${x.by}: ` : "") + x.text} />
      <CitedList title="Criticism" items={p.critiques} text={(x) => (x.by ? `${x.by}: ` : "") + x.text} />
      <CitedList title="Controversies" items={p.controversy_reports} text={(x) => x.what + (x.when ? ` (${x.when})` : "")} />
      <CitedList title="Claims of bias or conflicts of interest" items={p.bias_claims} text={(x) => (x.by ? `${x.by}: ` : "") + x.claim} />
    </>
  );
}

/** The show's profile: neutral facts only. */
export function CreatorPanel({ creator }: { creator: CreatorProfile }) {
  return (
    <>
      <h2 className="profile-name">{creator.podcast}</h2>
      <p className="meta">
        {[creator.youtube_channel_name, creator.country].filter(Boolean).join(" · ")}
        {creator.youtube_handles.map((h) => (
          <span key={h}> · <a href={`https://www.youtube.com/${h}`} target="_blank" rel="noopener noreferrer">{h}</a></span>
        ))}
      </p>
      {creator.public_profile.hosts && <p><span className="profile-k">Hosts</span> {creator.public_profile.hosts}</p>}
      {creator.public_profile.host_bio && <p><span className="profile-k">Background</span> {creator.public_profile.host_bio}</p>}
      {creator.public_profile.known_for && <p><span className="profile-k">Known for</span> {creator.public_profile.known_for}</p>}
      {creator.public_profile.narrative ? <ProfileDetails p={creator.public_profile} /> : <LeaningAndOpinion p={creator.public_profile} />}
      {creator.public_profile.incentives && <div className="profile-sec"><p className="profile-k">What the show has a stake in</p><IncentiveChips incentives={creator.public_profile.incentives} detail /></div>}
      {!!creator.public_profile.topics?.length && (
        <p className="profile-topics">{creator.public_profile.topics.map((t) => <span key={t} className="chip static">{t}</span>)}</p>
      )}
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
      <div className="people-tabs" role="tablist" aria-label="People in this video">
        {order.map((x) => (
          <button key={x.label} type="button" role="tab" aria-selected={x.label === p.label} className="person-tab" onClick={() => setSel(x.label)}>
            <span className="person-tab-name">{name(x)}</span>
            <span className="person-tab-role">{x.role ? ROLE_LINE[x.role] : "Speaker"}</span>
          </button>
        ))}
      </div>
      <div className="person" role="tabpanel">
        <h3 className="profile-name">{name(p)}</h3>
        <p className="meta person-role">{role}{creator && p.role === "host" ? ` · ${creator.podcast}` : ""}{p.statements ? ` · ${p.statements} ${p.statements === 1 ? "statement" : "statements"}` : ""}</p>
        {p.speaker ? (
          <>
            {p.speaker.summary && <p>{p.speaker.summary}</p>}
            {p.speaker.public_profile.role && <p><span className="profile-k">Role</span> {p.speaker.public_profile.role}</p>}
            {!!p.speaker.public_profile.affiliations?.length && (
              <p><span className="profile-k">Affiliations</span> {p.speaker.public_profile.affiliations.join(", ")}</p>
            )}
            {p.incentives && Object.keys(p.incentives).length > 0 && (
              <div className="profile-sec"><p className="profile-k">In this video, a stake in</p><IncentiveChips incentives={p.incentives} detail /></div>
            )}
            {p.speaker.public_profile.narrative ? <ProfileDetails p={p.speaker.public_profile} /> : <LeaningAndOpinion p={p.speaker.public_profile} />}
            {!!p.speaker.sources?.length && (
              <p className="meta">From: {p.speaker.sources.slice(0, 3).map((x, i) => (
                <span key={x.url}>{i > 0 && ", "}<a href={x.url} target="_blank" rel="noopener noreferrer">{domain(x.url)}</a></span>
              ))}</p>
            )}
          </>
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
