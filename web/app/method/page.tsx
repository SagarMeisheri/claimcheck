import type { Metadata } from "next";
import { STATEMENT_TYPES, TYPE_ORDER } from "@/lib/statements";
import { VERDICTS } from "@/lib/verdicts";

export const metadata: Metadata = { title: "How we check" };

export default function Method() {
  return (
    <div className="prose">
      <h1>How we check a video</h1>
      <p className="lede">
        An AI system finds the claims and the evidence. Rules written in code decide what can be published, and a person
        reviews the verdicts that matter most.
      </p>

      <h2>The steps</h2>
      <ol>
        <li>We decide whether a video is worth analysing: how much substantive public-interest content it has, and who is speaking.</li>
        <li>The AI breaks the video into statements, each with the moment it was said, and tags each one: claim, opinion, forecast, hearsay, analogy or loaded language. Only claims can be checked against sources; the other tags help you see how an argument is built.</li>
        <li>Nothing is verified automatically. Press Verify on any claim to check it against sources. A verified claim is saved and shown to everyone, so it&apos;s only checked once.</li>
        <li>Verification searches official sources first: RBI, MoSPI, PIB, the Election Commission, PubMed and others. A second AI model compares the claim with the sources and must quote the exact sentence it relied on.</li>
        <li>Code then checks the work: the quote must really appear in the source, the numbers must match, and a False verdict needs a strong source, high confidence and a second independent check.</li>
        <li>A person reviews every False verdict, and every Misleading or Disputed verdict on a political claim, before it appears, including ones that viewers asked for.</li>
      </ol>

      <h2>What the tags mean</h2>
      <ul>
        {TYPE_ORDER.map((k) => (
          <li key={k}><span className="stype" style={{ ["--stype" as string]: STATEMENT_TYPES[k].cssVar }}>{STATEMENT_TYPES[k].label}</span> {STATEMENT_TYPES[k].meaning}</li>
        ))}
      </ul>
      <p>
        A tag describes the statement, not the speaker. It is a reading aid, not a verdict: an opinion or forecast can be
        perfectly reasonable.
      </p>

      <h2>Limits on verification</h2>
      <p>
        Each person can verify up to 10 claims a day, and each video has a fixed budget for verification. When a video
        reaches it, no more of its claims can be verified.
      </p>

      <h2>What the verdicts mean</h2>
      <ul>
        {Object.entries(VERDICTS).map(([k, v]) => (
          <li key={k}><span className="vword" style={{ color: v.cssVar }}>{v.label}</span>: {v.meaning}</li>
        ))}
      </ul>

      <h2 id="policy">What we don&apos;t check</h2>
      <p>
        Religious or spiritual beliefs; claims about whole communities, castes or religions; private individuals and
        children; the merits of court cases still being heard; attacks and disasters in their first 48 hours; satire.
        Statements on these topics aren&apos;t shown at all. Opinions and predictions are tagged but not verified. For religion and caste, we only check numbers and documented events, such as census
        figures or election results.
      </p>

      <h2>Sources</h2>
      <p>
        Government statistics, regulators, courts and peer-reviewed research count as official sources. Major news
        organisations come next. Social media posts are never used as evidence. When official and independent figures
        disagree, as with unemployment, we show both and mark the claim Disputed data.
      </p>

      <h2>Balance</h2>
      <p>
        We check the same number of political videos each week from channels that tend to support the government and
        channels that tend to criticise it. <a href="/balance">See the numbers</a>.
      </p>

      <h2>Mistakes</h2>
      <p>
        Every claim has a “Wrong verdict?” button. A reviewer reads each report, and corrected verdicts are marked as
        changed after review.
      </p>
    </div>
  );
}
