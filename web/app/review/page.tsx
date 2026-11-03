import type { Metadata } from "next";
import { cancelEpisode, deleteEpisode, hideStatement, resolveReport } from "@/app/actions";
import { getAllEpisodes, getOpenReports } from "@/lib/data";
import { STATEMENT_TYPES } from "@/lib/statements";
import { clock, ytLink } from "@/lib/format";
import type { ReportKind } from "@/lib/types";

export const metadata: Metadata = { title: "Reviewer", robots: { index: false } };
export const dynamic = "force-dynamic";

const KIND_LABEL: Record<ReportKind, string> = {
  wrong_quote: "Words aren't what was said", wrong_speaker: "Wrong speaker", wrong_tag: "Wrong tag",
  wrong_time: "Wrong timestamp", bad_source: "Wrong or irrelevant source", other: "Other",
};

export default async function ReviewPage() {
  const [reports, episodes] = await Promise.all([getOpenReports(), getAllEpisodes()]);
  return (
    <>
      <h1>Reports</h1>
      <p className="lede">
        {reports.length === 0
          ? "No open reports."
          : `${reports.length} open ${reports.length === 1 ? "report" : "reports"}. Under the IT Rules, acknowledge within 24 hours and resolve within 15 days.`}
      </p>
      {reports.map((r) => (
        <div key={r.id} className="review-card">
          <p className="meta">{r.episode.channel_name}: {r.episode.title} · {new Date(r.created_at).toLocaleString()}</p>
          <p><strong>{KIND_LABEL[r.kind] ?? r.kind}</strong>: {r.note}</p>
          <h3>{r.claim.claim_text}</h3>
          <p className="meta">
            {STATEMENT_TYPES[r.claim.statement_type].label}, {r.claim.speaker ?? "unknown speaker"} at{" "}
            <a href={ytLink(r.episode.youtube_video_id, r.claim.start_s)} target="_blank" rel="noopener noreferrer">{clock(r.claim.start_s)}</a>
            {r.claim.context_quote && <>: “{r.claim.context_quote}”</>}
          </p>
          <div className="row">
            <form action={hideStatement}>
              <input type="hidden" name="claim_id" value={r.claim.id} />
              <button className="btn secondary">Hide this statement</button>
            </form>
            <form action={resolveReport}>
              <input type="hidden" name="report_id" value={r.id} />
              <input type="hidden" name="status" value="accepted" />
              <button className="btn secondary">Mark fixed</button>
            </form>
            <form action={resolveReport}>
              <input type="hidden" name="report_id" value={r.id} />
              <input type="hidden" name="status" value="rejected" />
              <button className="btn secondary">Nothing wrong</button>
            </form>
          </div>
        </div>
      ))}

      <h2 id="videos">Videos</h2>
      <p className="lede">Stop an analysis that is queued or stuck, or remove a video and everything shown for it.</p>
      {episodes.length === 0 && <p className="meta">No videos yet.</p>}
      {episodes.map((e) => (
        <div key={e.id} className="review-card">
          <p className="meta">
            <strong>{e.status}</strong>
            {e.cost_usd != null && <> · ${Number(e.cost_usd).toFixed(2)}</>} · {new Date(e.created_at).toLocaleString()}
          </p>
          <h3>
            <a href={ytLink(e.youtube_video_id, 0)} target="_blank" rel="noopener noreferrer">{e.title || e.youtube_video_id}</a>
          </h3>
          {e.skip_reason && <p className="meta">{e.skip_reason}</p>}
          <div className="row">
            {["queued", "processing"].includes(e.status) && (
              <form action={cancelEpisode}>
                <input type="hidden" name="episode_id" value={e.id} />
                <button className="btn secondary">Stop</button>
              </form>
            )}
            <form action={deleteEpisode}>
              <input type="hidden" name="episode_id" value={e.id} />
              <button className="btn secondary">Delete video</button>
            </form>
          </div>
        </div>
      ))}
    </>
  );
}
