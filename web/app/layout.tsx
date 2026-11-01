import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ClaimCheck", template: "%s | ClaimCheck" },
  description: "Every claim in India's big political and money videos, checked against official sources, with the timestamp.",
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
              <Link href="/submit">Check a video</Link>
              <Link href="/balance">Balance</Link>
              <Link href="/method">How we check</Link>
            </nav>
          </div>
        </header>
        <main>{children}</main>
        <footer>
          <div>
            Verdicts are produced by AI and checked against the quoted sources; False and political Misleading or
            Disputed verdicts are reviewed by a person before they appear. Found a mistake? Use “Wrong verdict?” on any
            claim. <Link href="/method">Read how we check</Link>.
          </div>
        </footer>
      </body>
    </html>
  );
}
