import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ViewSwitch } from "@/components/ViewSwitch";
import { getEpisodeByVideo } from "@/lib/data";
import { clock, domain, shortDate, ytLink } from "@/lib/format";
import { dedupeSources, groupByTopic, isoDuration, trim, visibleClaims } from "@/lib/notes";
import { STATEMENT_TYPES, speakerName } from "@/lib/statements";
import type { Claim, EpisodeDetail, SourcesMatch } from "@/lib/types";
import s from "./notes.module.css";

export const revalidate = 60;

type Props = { params: Promise<{ videoId: string }> };

const MATCH_WORD: Record<SourcesMatch, string> = { high: "High", medium: "Medium", low: "Low" };
const INLINE_SOURCES = 2;
const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

/** Only finished videos get a notes page. */
async function load(videoId: string): Promise<EpisodeDetail | null> {
  const ep = await getEpisodeByVideo(videoId);
  return ep && ep.status === "done" ? ep : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const ep = await load((await params).videoId);
  if (!ep) return { title: "Notes not found", robots: { index: false } };
  const claims = visibleClaims(ep.claims);
  const withSources = claims.filter((c) => c.sources.length).length;
  const title = `${ep.title}: statements and sources`;
  const description = ep.summary
    ? trim(`${ep.summary} ${withSources} statements with web sources.`, 300)
    : `${claims.length} statements from this video, ${withSources} with web sources.`;
  return {
    title, description,
    alternates: { canonical: `/notes/${ep.youtube_video_id}` },
    openGraph: { title, description, type: "article", images: [`https://i.ytimg.com/vi/${ep.youtube_video_id}/hqdefault.jpg`] },
  };
}

export default async function NotesPage({ params }: Props) {
  const ep = await load((await params).videoId);
  if (!ep) notFound();
  const claims = visibleClaims(ep.claims);
  const groups = groupByTopic(claims);
  const withSources = claims.filter((c) => c.sources.length).length;
  const checked = ep.sources_checked_at ? shortDate(ep.sources_checked_at) : null;
  const channel = ep.channel_id ? ep.channel_name : ep.creator?.podcast ?? null;
  const tableRows = [...claims].sort((a, b) => a.start_s - b.start_s);

  // Only people with a profile go into structured data: a name the AI guessed is not published as an entity.
  const people = ep.speakers.filter((p) => p.speaker).map((p) => ({ "@type": "Person", name: p.speaker!.name, description: p.speaker!.summary ?? undefined }));
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    name: ep.title,
    description: ep.summary ?? undefined,
    thumbnailUrl: `https://i.ytimg.com/vi/${ep.youtube_video_id}/hqdefault.jpg`,
    uploadDate: ep.published_at ?? undefined,
    duration: ep.duration_s ? isoDuration(ep.duration_s) : undefined,
    embedUrl: `https://www.youtube.com/embed/${ep.youtube_video_id}`,
    url: `${SITE}/notes/${ep.youtube_video_id}`,
    publisher: channel ? { "@type": "Organization", name: channel } : undefined,
    actor: people.length ? people : undefined,
    hasPart: (ep.sections ?? []).map((sec) => ({ "@type": "Clip", name: sec.title, startOffset: sec.start_s, endOffset: sec.end_s,
      url: ytLink(ep.youtube_video_id, sec.start_s) })),
  };

  return (
    <article className={s.page}>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <p className={s.crumbs}><Link href="/">ClaimCheck</Link></p>
      <ViewSwitch videoId={ep.youtube_video_id} current="notes" status={ep.status} />
      <h1 className={s.title}>{ep.title}</h1>
      {channel && <p className={s.channel}>{channel}</p>}
      {ep.summary && <p className={s.lead}>{ep.summary}</p>}
      <p className={s.meta}>
        AI-generated summary · {claims.length} statements, {withSources} with web sources
        {checked ? ` · sources looked up ${checked}` : ""}
      </p>
      <a className={s.watch} href={`https://www.youtube.com/watch?v=${ep.youtube_video_id}`} rel="noopener">▶ Watch the episode on YouTube</a>

      {groups.map((g) => (
        <section key={g.key} aria-labelledby={`t-${g.key}`}>
          <h2 className={s.h2} id={`t-${g.key}`}>{g.label}</h2>
          {g.claims.map((c) => <Statement key={c.id} c={c} videoId={ep.youtube_video_id} />)}
        </section>
      ))}

      <h2 className={s.h2} id="all">All statements</h2>
      <p className={s.note}>
        Statements are AI paraphrases of what was said, with the speaker as identified by AI. “Source match” shows how
        directly the search excerpts address the statement; it is not agreement and not a judgement of whether it is true.
      </p>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead><tr><th>Time</th><th>Statement</th><th>Type</th><th>Top source</th><th>Match</th></tr></thead>
          <tbody>
            {tableRows.map((c) => {
              const top = dedupeSources(c.sources)[0];
              const type = STATEMENT_TYPES[c.statement_type];
              return (
                <tr key={c.id}>
                  <td className={s.nowrap}><a href={ytLink(ep.youtube_video_id, c.start_s)} rel="noopener">{clock(c.start_s)}</a></td>
                  <td>{c.claim_text}</td>
                  <td><span className={s.type} style={{ ["--t" as string]: type.cssVar }}>{type.label}</span></td>
                  <td>{top ? <a href={top.url} rel="noopener nofollow">{trim(top.title ?? domain(top.url), 70)}</a> : "—"}</td>
                  <td>{c.sources_match ? MATCH_WORD[c.sources_match] : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function Statement({ c, videoId }: { c: Claim; videoId: string }) {
  const srcs = dedupeSources(c.sources);
  const shown = srcs.slice(0, INLINE_SOURCES);
  const rest = srcs.slice(INLINE_SOURCES);
  const who = speakerName(c.speaker);
  return (
    <div className={s.stmt} id={`claim-${c.id}`}>
      <p className={s.who}>
        {who ? `${who} (identified by AI) · ` : ""}
        <a href={ytLink(videoId, c.start_s)} rel="noopener">{clock(c.start_s)}</a> · {STATEMENT_TYPES[c.statement_type].label}
      </p>
      <p className={s.text}>{c.claim_text}</p>
      {c.sources_summary && <p className={s.summary}><b>What the sources say.</b> {c.sources_summary}</p>}
      <ul className={s.srcs}>
        {shown.map((x) => <SourceItem key={x.url} x={x} withExcerpt={!c.sources_summary} />)}
      </ul>
      {rest.length > 0 && (
        <details className={s.more}>
          <summary>{rest.length} more {rest.length === 1 ? "source" : "sources"}</summary>
          <ul className={s.srcs}>{rest.map((x) => <SourceItem key={x.url} x={x} withExcerpt />)}</ul>
        </details>
      )}
      {c.sources_match && (
        <p className={`${s.match} ${s[c.sources_match]}`}>Source match: <b>{MATCH_WORD[c.sources_match]}</b> · relevance of the excerpts, not agreement</p>
      )}
    </div>
  );
}

function SourceItem({ x, withExcerpt }: { x: Claim["sources"][number]; withExcerpt: boolean }) {
  const date = shortDate(x.publish_date);
  return (
    <li>
      <a href={x.url} rel="noopener nofollow">{x.title ?? domain(x.url)}</a>{" "}
      <span className={s.site}>{domain(x.url)}{date ? ` · ${date}` : ""}</span>
      {withExcerpt && x.excerpt && <span className={s.excerpt}>“{trim(x.excerpt, 220)}”</span>}
    </li>
  );
}
