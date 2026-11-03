import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy" };

export default function Privacy() {
  const contact = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  return (
    <div className="prose">
      <h1>Privacy</h1>
      <p className="lede">There are no accounts. We keep as little as we can.</p>

      <h2>What we store about you</h2>
      <ul>
        <li>
          <strong>A scrambled version of your IP address</strong>, when you submit a video, check sources or report a
          problem. It is a one-way salted hash, used only to apply the daily limits and to spot abuse. Rate-limit records
          are deleted after 30 days.
        </li>
        <li><strong>What you write in a report</strong>, so a person can act on it.</li>
        <li>
          <strong>Channels you follow</strong> stay in your own browser (local storage). They are never sent to us.
        </li>
      </ul>

      <h2>YouTube</h2>
      <p>
        Videos play in YouTube&apos;s own embedded player (from youtube-nocookie.com), which loads only when you press
        play. ClaimCheck uses YouTube API Services to read a video&apos;s title, length and channel. By using
        ClaimCheck you agree to the <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">YouTube
        Terms of Service</a>, and Google&apos;s use of data is covered by the{" "}
        <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Google Privacy Policy</a>.
        Video details are refreshed from YouTube at least every 30 days, and videos YouTube no longer shows are removed.
      </p>

      <h2>Other services</h2>
      <p>
        Videos are analysed with Google Gemini, and sources are searched with Parallel. Only the public video and the
        statement being searched are sent to them, never anything about you. The site is hosted on Vercel, the analysis
        service on Google Cloud, and the database on Supabase.
      </p>

      <h2>Contact</h2>
      <p>
        To ask about or delete anything we hold, use &quot;Report a problem&quot; on any statement
        {contact ? <> or write to <a href={`mailto:${contact}`}>{contact}</a></> : null}.
      </p>
    </div>
  );
}
