import { timingSafeEqual } from "node:crypto";

function same(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Reviewer login (HTTP basic auth). Constant-time comparison; no password configured means nobody gets in. */
export function reviewerFromHeader(authorization: string | null): string | null {
  const user = process.env.REVIEW_USER ?? "";
  const pass = process.env.REVIEW_PASSWORD ?? "";
  if (!pass || !authorization?.startsWith("Basic ")) return null;
  const decoded = Buffer.from(authorization.slice(6), "base64").toString();
  const i = decoded.indexOf(":");
  if (i < 0) return null;
  const u = decoded.slice(0, i);
  const p = decoded.slice(i + 1);
  return same(u, user) && same(p, pass) ? u : null;
}
