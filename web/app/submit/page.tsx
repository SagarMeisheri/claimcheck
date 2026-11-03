import type { Metadata } from "next";
import { SubmitForm } from "./SubmitForm";

export const metadata: Metadata = { title: "Analyse a video" };

export default function SubmitPage() {
  return (
    <>
      <h1>Analyse a video</h1>
      <p className="lede">
        Paste a link to any public YouTube video that has finished (not live). You&apos;ll get a summary and every
        statement tagged and timestamped. You can submit up to 5 videos a day.
      </p>
      <SubmitForm />
    </>
  );
}
