import { NextResponse, type NextRequest } from "next/server";
import { reviewerFromHeader } from "@/lib/auth";

// HTTP basic auth for the reviewer page. Server actions posted from /review pass through here too.
export function proxy(req: NextRequest) {
  if (!process.env.REVIEW_PASSWORD) {
    // No password set: lock the page.
    return new NextResponse("Reviewer access is not configured.", { status: 503 });
  }
  if (reviewerFromHeader(req.headers.get("authorization"))) return NextResponse.next();
  return new NextResponse("Authentication required.", {
    status: 401, headers: { "WWW-Authenticate": 'Basic realm="ClaimCheck review"' },
  });
}

export const config = { matcher: ["/review/:path*", "/review"] };
