"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useRef, useState } from "react";
import { inFlight, mergePatch, patchOf, type LivePatch } from "@/lib/live";

let browser: SupabaseClient | null | undefined;
/** The browser's connection to the database: the anon key only, so row level security decides what it is sent. */
function browserDb(): SupabaseClient | null {
  if (browser !== undefined) return browser;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  browser = url && key ? createClient(url, key, { auth: { persistSession: false }, realtime: { params: { eventsPerSecond: 20 } } }) : null;
  return browser;
}

const POLL_MS = 2500;

/**
 * Listens for the source lookups of one video while they run. Every update of a claim in flight arrives as the pipeline saves it
 * (Realtime), so `patches` holds what each lookup has found so far. If the connection is not there (Realtime is off, or it dropped)
 * the same patches are fetched every few seconds instead; the page works either way, only less smoothly.
 *
 * `onFinished(claimId, patch)` is called once when a lookup that was in flight ends (done, failed, or put back): the caller
 * fetches the finished result, which carries the sources themselves.
 */
export function useLiveClaims({ episodeId, videoId, enabled, onFinished }: {
  episodeId: string; videoId: string; enabled: boolean; onFinished(claimId: string, patch: LivePatch): void;
}): { patches: Record<string, LivePatch>; connected: boolean } {
  const [patches, setPatches] = useState<Record<string, LivePatch>>({});
  const [connected, setConnected] = useState(false);
  const connectedRef = useRef(false);
  const finished = useRef(onFinished);
  finished.current = onFinished;
  const known = useRef(new Set<string>()); // lookups seen in flight, so only their end is reported

  useEffect(() => {
    if (!enabled) return;
    let stop = false;

    const apply = (id: string, p: LivePatch) => {
      if (inFlight(p.sources_status)) {
        known.current.add(id);
        setPatches((m) => ({ ...m, [id]: mergePatch(m[id], p) }));
      } else if (known.current.delete(id)) {
        setPatches((m) => { const { [id]: _gone, ...rest } = m; return rest; });
        finished.current(id, p);
      }
    };

    // What is in flight now: on arrival, after a reconnect, and while there is no live connection.
    const resync = async () => {
      try {
        const r = await fetch(`/api/live/${videoId}`, { cache: "no-store" });
        if (!r.ok || stop) return;
        const rows = ((await r.json()) as { claims: Record<string, unknown>[] }).claims;
        const now = new Set<string>();
        for (const row of rows) {
          const p = patchOf(row);
          if (p && typeof row.id === "string") { now.add(row.id); apply(row.id, p); }
        }
        for (const id of [...known.current]) if (!now.has(id)) apply(id, { sources_status: "done" }); // no longer in flight: it ended
      } catch { /* try again */ }
    };

    const db = browserDb();
    const channel = db?.channel(`claims-${episodeId}`)
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "claims", filter: `episode_id=eq.${episodeId}` }, (payload) => {
        const row = payload.new as Record<string, unknown>;
        const p = patchOf(row);
        if (p && typeof row.id === "string") apply(row.id, p);
      })
      .subscribe((status) => {
        if (stop) return;
        const ok = status === "SUBSCRIBED";
        connectedRef.current = ok;
        setConnected(ok);
        if (ok) void resync(); // anything that happened before the connection was made
      });

    void resync();
    const timer = window.setInterval(() => { if (!connectedRef.current) void resync(); }, POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(timer);
      connectedRef.current = false;
      if (channel && db) void db.removeChannel(channel);
    };
  }, [enabled, episodeId, videoId]);

  return { patches, connected };
}
