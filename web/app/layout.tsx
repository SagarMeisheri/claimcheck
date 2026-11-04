import type { Metadata } from "next";
import Link from "next/link";
import { Sidebar } from "@/components/shell/Sidebar";
import { getSidebarVideos } from "@/lib/data";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ClaimCheck", template: "%s | ClaimCheck" },
  description: "Paste a YouTube link and see every statement in the video, tagged and timestamped, with sources for its claims.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
};

// The sidebar lists every video, so every page re-renders at least this often (seconds).
export const revalidate = 10;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
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
        <div className="app">
          <Sidebar videos={await getSidebarVideos()} />
          <div className="app-body">
            <main>{children}</main>
            <footer>
              AI-generated breakdowns of YouTube videos. Not a fact-check: nothing is judged true or false, and sources are
              shown for context. Quotes, speakers and tags can be wrong; use “Report a problem” on any statement.{" "}
              <Link href="/method">How it works</Link> · <Link href="/privacy">Privacy</Link>.
            </footer>
          </div>
        </div>
      </body>
    </html>
  );
}
