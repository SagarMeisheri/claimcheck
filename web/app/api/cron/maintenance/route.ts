import { NextResponse } from "next/server";
import { serviceDb } from "@/lib/data";

// Vercel Cron, daily (vercel.json):
// 1. Asks the pipeline to refresh stored YouTube data older than 25 days (YouTube allows at most 30) and hide
//    videos YouTube no longer serves.
// 2. Deletes rate-limit rows (salted IP hashes) older than 30 days, as the privacy page promises.
export const dynamic = "force-dynamic";
const RETENTION_DAYS = 30;

export async function GET(req: Request) {
  if (!process.env.CRON_SECRET || req.headers.get("authorization") !== `Bearer ${process.env.CRON_SECRET}`) {
    return new NextResponse("unauthorised", { status: 401 });
  }
  const res = await fetch(`${process.env.PIPELINE_URL}/maintenance/youtube-refresh`, {
    method: "POST", headers: { "x-pipeline-secret": process.env.PIPELINE_SHARED_SECRET ?? "" },
  }).catch(() => null);
  const youtube = res?.ok ? await res.json().catch(() => null) : { error: res ? `HTTP ${res.status}` : "pipeline unreachable" };

  const db = serviceDb();
  const before = new Date(Date.now() - RETENTION_DAYS * 86400e3).toISOString();
  const deleted: Record<string, number | string> = {};
  for (const table of ["submissions", "source_requests", "verify_requests"]) {
    const { count, error } = await db.from(table).delete({ count: "exact" }).lt("created_at", before);
    deleted[table] = error ? error.message : count ?? 0;
  }
  return NextResponse.json({ youtube, deleted }, { status: res?.ok ? 200 : 502 });
}
