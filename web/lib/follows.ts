// Followed channels live in the browser only (no accounts in the MVP).
const KEY = "claimcheck-follows";

export function readFollows(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function toggleFollow(id: string): string[] {
  const now = readFollows();
  const next = now.includes(id) ? now.filter((x) => x !== id) : [...now, id];
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: following just won't persist */
  }
  return next;
}
