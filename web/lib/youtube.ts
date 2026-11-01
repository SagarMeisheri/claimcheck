// Same rules as the pipeline's parse_video_id (pipeline/claimcheck/guardrails/input_checks.py).
export function parseVideoId(raw: string): string | null {
  let u: URL;
  try {
    u = new URL(raw.trim());
  } catch {
    return null;
  }
  let host = u.hostname.toLowerCase().replace(/^(www|m)\./, "");
  let id: string | null = null;
  if (host === "youtu.be") id = u.pathname.slice(1).split("/")[0];
  else if (host === "youtube.com" || host === "music.youtube.com") {
    if (u.pathname === "/watch") id = u.searchParams.get("v");
    else {
      const parts = u.pathname.split("/").filter(Boolean);
      if (parts.length >= 2 && ["shorts", "live", "embed"].includes(parts[0])) id = parts[1];
    }
  }
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}
