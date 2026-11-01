import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";
import { getClaimStatus } from "@/lib/data";

// Live verification state of one claim, polled by the Verify button. Never cached. The verdict is included only when public.
export const dynamic = "force-dynamic";

const FINAL = ["verified", "awaiting_review", "failed", "not_requested"];

export async function GET(_req: Request, { params }: { params: Promise<{ claimId: string }> }) {
  const { claimId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return NextResponse.json({ status: "unknown" }, { status: 404 });
  const s = await getClaimStatus(claimId);
  if (!s) return NextResponse.json({ status: "unknown" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  // Once the result is in, drop the cached video page so the next refresh shows it.
  if (FINAL.includes(s.verification_status) && s.video_id) revalidatePath(`/v/${s.video_id}`);
  return NextResponse.json({ status: s.verification_status, error: s.verify_error, outcome: s.outcome }, { headers: { "Cache-Control": "no-store" } });
}
