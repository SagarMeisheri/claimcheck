import { NextResponse, type NextRequest } from "next/server";

// HTTP basic auth for the reviewer queue. Server actions posted from /review pass through here too.
export function proxy(req: NextRequest) {
  const user = process.env.REVIEW_USER;
  const pass = process.env.REVIEW_PASSWORD;
  if (!pass) {
    // No password set: lock the page.
    return new NextResponse("Reviewer access is not configured.", { status: 503 });
  }
  const auth = req.headers.get("authorization");
  if (auth?.startsWith("Basic ")) {
    const [u, p] = atob(auth.slice(6)).split(":");
    if (u === user && p === pass) return NextResponse.next();
  }
  return new NextResponse("Authentication required.", {
    status: 401, headers: { "WWW-Authenticate": 'Basic realm="ClaimCheck review"' },
  });
}

export const config = { matcher: ["/review/:path*", "/review"] };
