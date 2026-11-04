"use client";

import { useState } from "react";
import type { CreatorProfile, EpisodeSpeaker, Section } from "@/lib/types";
import { clock, domain } from "@/lib/format";

type Tab = "video" | "creator" | "speakers";

const PROFILE_NOTE = "Compiled with AI from public web sources. It describes who they are, not whether anything said is right.";

/**
 * Tabs under the video: the AI summary and the parts of the conversation, the show's profile, and who speaks.
 * Profiles show neutral facts only; the notes on known positions and criticisms that steer source searches are
 * never sent to the browser.
 */
export function ProfileTabs({ summary, sections, creator, speakers, onSeek }: {
  summary: string | null | undefined; sections: Section[]; creator: CreatorProfile | null; speakers: EpisodeSpeaker[];
  onSeek(s: number): void;
}) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "video", label: "Video" },
    ...(creator ? [{ key: "creator" as Tab, label: "Creator" }] : []),
    ...(speakers.length ? [{ key: "speakers" as Tab, label: `Speakers ${speakers.length}` }] : []),
  ];
  const [tab, setTab] = useState<Tab>("video");
  if (!summary && !sections.length && tabs.length === 1) return null;

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

      {tab === "video" && (
        <div role="tabpanel" id="ppanel-video" aria-labelledby="ptab-video" className="ppanel">
          {summary && (
            <div className="ai-summary">
              <p className="ai-note">AI summary</p>
              <p>{summary}</p>
            </div>
          )}
          {sections.length > 0 && (
            <>
              <p className="ai-note">Parts of the conversation (AI)</p>
              <ol className="sections">
                {sections.map((s) => (
                  <li key={s.idx}>
                    <button type="button" className="linkish cc-ts" onClick={() => onSeek(s.start_s)} aria-label={`Play from ${clock(s.start_s)}`}>
                      {clock(s.start_s)}
                    </button>
                    <span className="section-body"><strong>{s.title}</strong>{s.summary && <span className="meta"> {s.summary}</span>}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}

      {tab === "creator" && creator && (
        <div role="tabpanel" id="ppanel-creator" aria-labelledby="ptab-creator" className="ppanel profile">
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
          {!!creator.public_profile.topics?.length && (
            <p className="profile-topics">{creator.public_profile.topics.map((t) => <span key={t} className="chip static">{t}</span>)}</p>
          )}
          <p className="meta profile-note">{PROFILE_NOTE}</p>
        </div>
      )}

      {tab === "speakers" && (
        <div role="tabpanel" id="ppanel-speakers" aria-labelledby="ptab-speakers" className="ppanel">
          <ul className="speakers">
            {speakers.map((sp) => (
              <li key={sp.label} className="speaker">
                <p className="speaker-head">
                  <strong>{sp.speaker?.name ?? sp.label}</strong>
                  {sp.role && <span className="meta"> · {sp.role === "host" ? "Host" : "Guest"}</span>}
                  <span className="meta"> · {sp.statements} {sp.statements === 1 ? "statement" : "statements"}</span>
                </p>
                {sp.speaker ? (
                  <>
                    {sp.speaker.summary && <p>{sp.speaker.summary}</p>}
                    {sp.speaker.public_profile.role && <p><span className="profile-k">Role</span> {sp.speaker.public_profile.role}</p>}
                    {!!sp.speaker.public_profile.affiliations?.length && (
                      <p><span className="profile-k">Affiliations</span> {sp.speaker.public_profile.affiliations.join(", ")}</p>
                    )}
                    {!!sp.speaker.sources?.length && (
                      <p className="meta">From: {sp.speaker.sources.slice(0, 3).map((x, i) => (
                        <span key={x.url}>{i > 0 && ", "}<a href={x.url} target="_blank" rel="noopener noreferrer">{domain(x.url)}</a></span>
                      ))}</p>
                    )}
                  </>
                ) : (
                  <p className="meta">{/^(host|guest|panel|speaker|co-?host)/i.test(sp.label)
                    ? "Not named in the video, so no profile."
                    : "No public profile found for this name."}</p>
                )}
              </li>
            ))}
          </ul>
          <p className="meta profile-note">{PROFILE_NOTE} Speaker names are identified by AI from the video.</p>
        </div>
      )}
    </section>
  );
}
