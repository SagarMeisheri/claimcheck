import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";
import { getClaimSources } from "@/lib/data";

// Live state of one claim's source lookup, polled by the "Check sources" button. Never cached.
export const dynamic = "force-dynamic";

const FINAL = ["done", "failed", "not_requested"];

export async function GET(_req: Request, { params }: { params: Promise<{ claimId: string }> }) {
  const { claimId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return NextResponse.json({ status: "unknown" }, { status: 404 });
  const s = await getClaimSources(claimId);
  if (!s) return NextResponse.json({ status: "unknown" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  // Once the result is in, drop the cached video page so the next refresh shows it.
  if (FINAL.includes(s.sources_status) && s.video_id) revalidatePath(`/v/${s.video_id}`);
  return NextResponse.json({ status: s.sources_status, error: s.sources_error, sources: s.sources, summary: s.sources_summary, match: s.sources_match,
                             counter: s.counter_sources, counter_summary: s.counter_summary, route: s.sources_route, research: s.research, qa_tags: s.qa_tags },
                           { headers: { "Cache-Control": "no-store" } });
}
