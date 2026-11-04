import { UrlForm } from "@/components/shell/UrlForm";
import { STATEMENT_TYPES, TYPE_ORDER } from "@/lib/statements";

export default function Home() {
  return (
    <div className="home">
      <div className="home-inner">
        <h1 className="home-title">Analyse a YouTube video</h1>
        <p className="home-lede">
          Paste a link and get a summary of the video and every statement in it, timestamped and tagged, with web sources
          for the claims.
        </p>
        <UrlForm />
        <ul className="home-types" aria-label="How statements are tagged">
          {TYPE_ORDER.map((t) => (
            <li key={t} style={{ ["--stype" as string]: STATEMENT_TYPES[t].cssVar }} title={STATEMENT_TYPES[t].meaning}>
              {STATEMENT_TYPES[t].label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
