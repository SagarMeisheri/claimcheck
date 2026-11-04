import Link from "next/link";

/**
 * Switch between a video's two pages: the interactive view and the plain notes page (statements and sources as text).
 * The notes page exists only for finished videos, so the switch is hidden for the others.
 */
export function ViewSwitch({ videoId, current, status }: { videoId: string; current: "interactive" | "notes"; status: string }) {
  if (status !== "done") return null;
  return (
    <nav className="view-switch" aria-label="Page view">
      <Link href={`/v/${videoId}`} aria-current={current === "interactive" ? "page" : undefined}>Interactive</Link>
      <Link href={`/notes/${videoId}`} aria-current={current === "notes" ? "page" : undefined}>Notes</Link>
    </nav>
  );
}
