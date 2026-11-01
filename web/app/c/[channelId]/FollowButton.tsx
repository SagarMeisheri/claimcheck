"use client";

import { useEffect, useState } from "react";
import { readFollows, toggleFollow } from "@/lib/follows";

export function FollowButton({ channelId }: { channelId: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => setOn(readFollows().includes(channelId)), [channelId]);
  return (
    <button className={`btn${on ? " secondary" : ""}`} aria-pressed={on}
            onClick={() => setOn(toggleFollow(channelId).includes(channelId))}>
      {on ? "Following" : "Follow"}
    </button>
  );
}
