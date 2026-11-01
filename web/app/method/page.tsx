import type { Metadata } from "next";
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
        <li>We decide whether a video is worth checking: how many specific facts it contains, and who is speaking.</li>
        <li>The AI lists the factual claims and the moment each was said. Opinions, predictions and personal stories are set aside.</li>
        <li>The most important claims (up to 25 a video) are checked. Official sources are searched first: RBI, MoSPI, PIB, the Election Commission, PubMed and others.</li>
        <li>A second AI model compares each claim with the sources and must quote the exact sentence it relied on.</li>
        <li>Code then checks the work: the quote must really appear in the source, the numbers must match, and a False verdict needs a strong source, high confidence and a second independent check.</li>
        <li>A person reviews every False verdict, and every Misleading or Disputed verdict on a political claim, before it appears.</li>
      </ol>

      <h2>What the verdicts mean</h2>
      <ul>
        {Object.entries(VERDICTS).map(([k, v]) => (
          <li key={k}><span className="vword" style={{ color: v.cssVar }}>{v.label}</span>: {v.meaning}</li>
        ))}
      </ul>

      <h2 id="policy">What we don&apos;t check</h2>
      <p>
        Religious or spiritual beliefs; claims about whole communities, castes or religions; private individuals and
        children; the merits of court cases still being heard; attacks and disasters in their first 48 hours; satire;
        opinions and predictions. For religion and caste, we only check numbers and documented events, such as census
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
