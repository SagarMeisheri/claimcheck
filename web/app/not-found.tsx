import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>That scorecard doesn&apos;t exist</h1>
      <p className="lede">It may have been removed, or the link is incomplete. <Link href="/">See the latest scorecards</Link>.</p>
    </>
  );
}
