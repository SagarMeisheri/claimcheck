import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ClaimCheck", template: "%s | ClaimCheck" },
  description: "Paste a YouTube link and see every statement in the video, tagged and timestamped, with sources for its claims.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Anek+Latin:wdth,wght@75..100,400..700&family=Mukta:wght@400;600&display=swap"
        />
      </head>
      <body>
        <header className="site-head">
          <div className="bar">
            <Link href="/" className="brand">ClaimCheck</Link>
            <nav className="site-nav" aria-label="Main">
              <Link href="/">Latest</Link>
              <Link href="/submit">Analyse a video</Link>
              <Link href="/method">How it works</Link>
              <Link href="/privacy">Privacy</Link>
            </nav>
          </div>
        </header>
        <main>{children}</main>
        <footer>
          <div>
            AI-generated breakdowns of YouTube videos. Not a fact-check: nothing is judged true or false, and sources are
            shown for context. Quotes, speakers and tags can be wrong; use “Report a problem” on any statement.{" "}
            <Link href="/method">How it works</Link> · <Link href="/privacy">Privacy</Link>.
          </div>
        </footer>
      </body>
    </html>
  );
}
