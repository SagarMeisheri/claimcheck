import type { Step } from "./types";

/** The analysis steps, in order: shown as waiting before the pipeline reports any, then ticked off as they finish.
 *  Keys and labels match the pipeline (pipeline/claimcheck/agents/pipeline.py: initial_steps). */
export const DEFAULT_STEPS: Step[] = [
  { key: "creator", label: "Matching the channel to a creator profile", status: "pending" },
  { key: "ingest_gate", label: "Checking the video details", status: "pending" },
  { key: "extractor", label: "Reading the video, tagging statements and sections", status: "pending" },
  { key: "claim_filter", label: "Applying the content policy", status: "pending" },
  { key: "speaker_profiler", label: "Building speaker profiles", status: "pending" },
  { key: "publisher", label: "Saving results", status: "pending" },
];
