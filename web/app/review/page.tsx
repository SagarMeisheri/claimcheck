import type { Metadata } from "next";
import { cancelEpisode, deleteEpisode, reviewVerdict } from "@/app/actions";
import { getAllEpisodes, getPendingReviews } from "@/lib/data";
import { TIER_LABEL, VERDICTS, clock, domain, ytLink } from "@/lib/verdicts";

export const metadata: Metadata = { title: "Review queue", robots: { index: false } };
export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const items = await getPendingReviews();
  const episodes = await getAllEpisodes();
  return (
    <>
      <h1>Review queue</h1>
      <p className="lede">
        {items.length === 0
          ? "Nothing waiting. New False verdicts and political Misleading or Disputed verdicts will appear here."
          : `${items.length} ${items.length === 1 ? "verdict needs" : "verdicts need"} a decision before publishing.`}
      </p>
      {items.map(({ verdict: v, claim: c, episode: e }) => (
        <div key={v.id} className="review-card">
          <p className="meta">{e.channel_name}: {e.title}</p>
          <h3>{c.claim_text}</h3>
          <p className="meta">
            {c.speaker} at <a href={ytLink(e.youtube_video_id, c.start_s)} target="_blank" rel="noopener noreferrer">{clock(c.start_s)}</a>
            {c.context_quote && <>: “{c.context_quote}”</>}
          </p>
          <p>
            Proposed: <span className="vword" style={{ color: VERDICTS[v.verdict].cssVar }}>{VERDICTS[v.verdict].label}</span>{" "}
            at {Math.round(v.confidence * 100)}% confidence. {v.reasoning}
          </p>
          {v.citations.map((s) => (
            <blockquote key={s.url} style={{ borderLeft: "3px solid var(--rule)", margin: "0.5rem 0", paddingLeft: "0.8rem" }}>
              “{s.quote}”
              <div className="meta"><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || domain(s.url)}</a>. {TIER_LABEL[s.tier]}</div>
            </blockquote>
          ))}
          {v.downgrades && v.downgrades.length > 0 && (
            <p className="meta">Guardrail notes: {v.downgrades.join("; ")}</p>
          )}
          <form action={reviewVerdict}>
            <input type="hidden" name="verdict_id" value={v.id} />
            <div className="field">
              <label htmlFor={`note-${v.id}`}>Note (optional, kept internally)</label>
              <input id={`note-${v.id}`} name="note" />
            </div>
            <div className="row">
              <button className="btn" name="decision" value="approve">Publish as {VERDICTS[v.verdict].label}</button>
              <select name="new_verdict" defaultValue="unverifiable" aria-label="Change verdict to">
                {Object.entries(VERDICTS).map(([k, x]) => <option key={k} value={k}>{x.label}</option>)}
              </select>
              <button className="btn secondary" name="decision" value="change">Change and publish</button>
            </div>
          </form>
        </div>
      ))}

      <h2 id="videos">Videos</h2>
      <p className="lede">Stop a check that is queued or stuck, or remove a video and its claims.</p>
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
                <button className="btn secondary">Stop checking</button>
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
