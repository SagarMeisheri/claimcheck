import type { Metadata } from "next";
import { SubmitForm } from "./SubmitForm";

export const metadata: Metadata = { title: "Check a video" };

export default function SubmitPage() {
  return (
    <>
      <h1>Check a video</h1>
      <p className="lede">
        Paste a public YouTube link. Videos need to be at least 5 minutes long and finished (not live). You can submit up
        to 5 videos a day.
      </p>
      <SubmitForm />
    </>
  );
}
