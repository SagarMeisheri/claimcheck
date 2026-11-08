import type { Step } from "./types";

/** The analysis steps, in order: shown as waiting before the pipeline reports any, then ticked off as they finish.
 *  Keys and labels match the pipeline (pipeline/claimcheck/agents/pipeline.py: initial_steps). */
export const DEFAULT_STEPS: Step[] = [
  { key: "ingest_gate", label: "Checking the video details", status: "pending" },
  { key: "people_profiler", label: "Profiling the show, hosts and guests", status: "pending" },
  { key: "extractor", label: "Reading the video, listing questions and answers", status: "pending" },
  { key: "claim_filter", label: "Applying the content policy", status: "pending" },
  { key: "speaker_profiler", label: "Profiling anyone new who spoke", status: "pending" },
  { key: "interview_tagger", label: "Tagging how each question was asked", status: "pending" },
  { key: "publisher", label: "Saving results", status: "pending" },
];

/** How many steps have finished: the page refreshes each time this grows, so a step's results show as soon as it ends. */
export function stepsDone(steps: Step[] | null | undefined): number {
  return (steps ?? []).filter((s) => s.status === "done" || s.status === "skipped").length;
}
