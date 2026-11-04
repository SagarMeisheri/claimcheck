import { redirect } from "next/navigation";

/** Old "Analyse a video" page: the link box is on the home page now. */
export default function SubmitPage() {
  redirect("/");
}
