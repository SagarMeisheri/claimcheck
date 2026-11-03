"use client";

import { topicHue, topicLabel } from "@/lib/format";

/** A statement's subject tags (1-2). Each one is a button: pressing it filters the list to that subject. */
export function TopicTags({ topics, active, onPick }: { topics?: string[]; active?: string | null; onPick(t: string): void }) {
  if (!topics?.length) return null;
  return (
    <div className="topic-tags" aria-label="Subjects">
      {topics.map((t) => (
        <button key={t} type="button" className="topic-tag" aria-pressed={active === t} style={{ ["--th" as string]: topicHue(t) }}
                title={`Show statements about ${topicLabel(t).toLowerCase()}`} onClick={() => onPick(t)}>
          {topicLabel(t)}
        </button>
      ))}
    </div>
  );
}
