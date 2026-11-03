import type { Metadata } from "next";
import { STATEMENT_TYPES, TYPE_ORDER } from "@/lib/statements";
import { SOURCES_NOTE } from "@/components/SourceList";

export const metadata: Metadata = { title: "How it works" };

export default function Method() {
  const contact = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  return (
    <div className="prose">
      <h1>How it works</h1>
      <p className="lede">
        ClaimCheck breaks a YouTube video into what was said, so you can skim a long podcast or interview in minutes. It
        is not a fact-check: nothing is judged true or false.
      </p>

      <h2>The steps</h2>
      <ol>
        <li>Anyone can paste a link to a public, finished YouTube video.</li>
        <li>An AI watches the video and lists its statements, each with the moment it was said, a short summary of the video, and one tag per statement.</li>
        <li>For a claim, you can press &quot;Check sources&quot;. ClaimCheck runs one web search (with Parallel) on the claim&apos;s wording and shows the top 5 results in the search engine&apos;s order: the page title, the site, the date and a short excerpt from the page. An AI then summarises those excerpts, and only those, in one or two sentences, with their own figures and dates and numbered links to them. It describes the pages and never says whether the statement is right; nothing is filtered out. It also rates the source match (High, Medium or Low): how directly the excerpts address the claim&apos;s specific point. That is about relevance, not agreement: a source giving a different figure for the same thing is a high match. Social media and video sites are left out of the search. &quot;Check sources for all claims&quot; runs the same search for up to 25 claims at a time.</li>
        <li>Results are saved and shown to everyone, so each claim only needs looking up once.</li>
      </ol>

      <h2>What the tags mean</h2>
      <ul>
        {TYPE_ORDER.map((k) => (
          <li key={k}><span className="stype" style={{ ["--stype" as string]: STATEMENT_TYPES[k].cssVar }}>{STATEMENT_TYPES[k].label}</span> {STATEMENT_TYPES[k].meaning}</li>
        ))}
      </ul>
      <p>A tag describes the kind of statement, not the speaker. It is a reading aid, not a judgement.</p>

      <h2>About sources</h2>
      <p>{SOURCES_NOTE} A result may support a statement, give a different figure, cover a different period, or simply be about the same subject: the summary gives each page&apos;s own numbers so you can compare, and the links let you check. The summary is AI output and can be wrong. Sites are labelled when they are official bodies or established news or research organisations; other sites are shown too. Finding no sources says nothing about whether a statement is right.</p>

      <h2>What the AI can get wrong</h2>
      <p>
        Everything on a video page is AI output: the wording of each statement, the transcript under &quot;What was
        said&quot;, the speaker names, the tags, the timestamps and the summary. They can be wrong. Use &quot;Watch
        20 s&quot; to hear the original before relying on anything, and report mistakes.
      </p>

      <h2 id="policy">What we don&apos;t show</h2>
      <p>
        Statements about religious or spiritual beliefs; claims about whole communities, castes or religions; private
        individuals and children; the merits of court cases still being heard; attacks and disasters in their first 48
        hours; and satire are not shown at all.
      </p>

      <h2>Limits</h2>
      <p>
        Each person can submit up to 5 videos and check sources up to 10 times a day. Each video has a fixed budget for
        AI and search costs; when it is used up, no more sources can be looked up for it.
      </p>

      <h2 id="report">Report a problem</h2>
      <p>
        Every statement has &quot;Report a problem&quot;: a wrong quote, speaker, tag, time or source, or any other
        concern, including legal ones. Reports are acknowledged within 24 hours and resolved within 15 days; statements
        that are wrong are corrected or removed.
        {contact && <> You can also write to <a href={`mailto:${contact}`}>{contact}</a>.</>}
      </p>
    </div>
  );
}
