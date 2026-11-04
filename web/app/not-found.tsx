import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>That video isn&apos;t here</h1>
      <p className="lede">It may have been removed, or the link is incomplete. <Link href="/">Analyse a video</Link>.</p>
    </>
  );
}
