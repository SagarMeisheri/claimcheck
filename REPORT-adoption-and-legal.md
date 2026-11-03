> **Superseded (3 Nov 2026):** ClaimCheck no longer publishes verdicts. It now tags statements and shows sources for claims; see `README.md`. This report describes the earlier verdict-based version.

# ClaimCheck: why it may struggle to get users, and the legal risks

*Written 3 Nov 2026. Companion to `REPORT.md`. Based on web research (sources at the end) and the ClaimCheck code. This is research, not legal advice; the README already says a lawyer should review before launch, and this report gives that lawyer a list to work from.*

---

## Short version

- **Fact-checking is a small-audience product everywhere.** Most people never visit a fact-checking site. The people who do are a small, already-sceptical minority, and the people most exposed to false claims don't come. The industry is shrinking: closures outnumbered openings 3 to 1 in 2025, and three-quarters of fact-checkers say they are financially vulnerable or in crisis.
- **ClaimCheck adds its own hurdles.** It's a separate website while Indians watch on YouTube. It starts empty, and each viewer has to press Verify and wait. The verdicts are AI-made, and research shows AI fact-checks don't help people tell true from false the way human ones do. The site is English-only while much of the target content is Hindi.
- **The biggest legal risk is defamation.** The site publishes "False" next to the names of politicians and creators. Because ClaimCheck writes those verdicts itself, it can't claim the "intermediary" protection that platforms get. Indian fact-checkers have faced arrests, multiple FIRs and defamation notices. The code also shows a "verbatim" quote and a speaker name for every statement, and both are AI-generated and never checked.
- **Other risks:** India's IT Rules for digital news publishers, Election Commission rules during polls, a possible revival of the government Fact Check Unit, state "fake news" bills, and **YouTube's API terms, which the app currently breaks** (it stores video data for longer than 30 days).

---

## Part 1: Why fact-checking sites don't get popular (research)

| Reason | Evidence |
|---|---|
| **People don't go looking for fact-checks** | A 2017 study found over half of US adults had never visited any fact-checking site. A 2022 audience study found most people didn't know the main fact-checkers, and concluded fact-checking serves "a small and engaged minority". |
| **The wrong people come** | Fact-checking sites draw visitors, but not the heavy consumers of false content. People pick fact-checks that suit their side, and "the most extreme partisans may not be visiting their sites at all". |
| **Fact-checks travel slower than the claim** | Fact-checkers mostly publish on their own sites. A false claim spreads inside the platform where it started, while the correction sits somewhere else. |
| **Format** | Long, careful write-ups lose to short feeds. Most fact-checking is in English, which leaves out large non-English audiences. |
| **Trust** | Large parts of the public see fact-checkers as biased. In India's polarised politics, any verdict on a politician will be read as taking a side. |
| **Distribution is disappearing** | Meta ended US third-party fact-checking in Jan 2025 and moved to Community Notes. Google removed fact-check snippets from Search in June 2025; they had been seen 120 million times in the EU in just the first half of 2024. |
| **Money** | The Duke Reporters' Lab 2026 census counts 437 active projects, down from a 2024 peak of 464, with 30 closures against 10 launches in 2025. 75% of IFCN members say they are financially vulnerable or in crisis. **Logically**, a well-funded AI fact-checking startup, went into administration in July 2025 after losing its Meta and TikTok contracts. |
| **AI fact-checks specifically** | A PNAS study (Dec 2024) found that ChatGPT correctly flagged about 90% of false headlines, yet **people's ability to tell true from false did not improve**. Human fact-checks did help. Where the AI was unsure, it made people *more* likely to believe dubious headlines. |
| **India's news habits** | The Reuters Institute 2026 report says about 58% of Indians rely on YouTube for news and 52% avoid news. |

---

## Part 2: Why ClaimCheck in particular may not get users

These come from the code and product design, checked against the research above.

1. **It's a destination, but the audience is on YouTube.** To use ClaimCheck, a viewer has to leave YouTube, paste a link, and come back later. There is no browser extension, no WhatsApp-friendly share flow (only a share image), and no way to show results where people watch.
2. **Empty at launch, and slow on first use.** The README says "the app starts empty". The first person to submit a video waits 10–30 minutes, and then sees **tags but no verdicts** until someone presses Verify and waits again. Most visitors will leave before seeing any value.
3. **It asks the viewer to do the work.** Verify is on-demand and limited to 10 per person per day. The people who press it are those who already doubt the speaker, which matches the "small engaged minority" finding.
4. **Many results will be "Unverifiable".** The strict checks downgrade a verdict whenever:
   - the quote isn't found word-for-word on the page,
   - the numbers don't match within 5%,
   - no source is official or major news,
   - a False verdict has confidence below 0.8.

   These checks protect against legal risk, but a page full of "Unverifiable" feels like nothing happened. *(Likely; not yet measured, since the system hasn't run live.)*
5. **Every False verdict waits for a reviewer.** The most shareable result, "this politician said something false", is held back. Without a staffed reviewer, those verdicts may never appear.
6. **English only.** The site is `lang="en"` with no Hindi interface, and the extractor writes claims in English. Much of the seeded channel list (Aaj Tak, Lallantop, Ravish Kumar, Dhruv Rathee, Ajeet Bharti…) is Hindi-language.
7. **No reason to come back.** There are no accounts or notifications. "Following" is saved only in one browser, so there's no habit loop.
8. **Political channels and their fans will push back.** The seed list deliberately includes both government-supportive and critical commentators. Each side's supporters are likely to call the site biased whenever their side is flagged, which is the pattern Indian fact-checkers already face.
9. **Hard to make money.** YouTube's API policy bans selling ads or sponsorships on any page showing YouTube API data, unless the page also has other independently valuable content (III.G.1.d). The site's pages are built around YouTube data. Each video also has real AI and search costs (see `REPORT.md`).

**What tends to work instead** (from the research): putting fact-checks where people already are (inside the platform, broadcast partnerships, WhatsApp tiplines), shorter conversational formats, local languages, and crowd-based notes. A 2026 Nature Communications study found Community Notes on X reduced resharing of misleading posts.

---

## Part 3: Legal risks in India

Ranked by likelihood × impact.

### 1. Defamation: highest risk

- **What the law says.** Defamation is a crime in India (Bharatiya Nyaya Sanhita s.356; up to 2 years in prison) and grounds for a civil suit. The Supreme Court upheld criminal defamation in *Subramanian Swamy v. Union of India* (2016). The main defence is **truth published for the public good**, and that is decided case by case, so it only helps after a costly trial.
- **No platform shield.** IT Act s.79 protects intermediaries for content written by *others*. ClaimCheck writes its own verdicts, summaries, tags and "corrections", so it is a **publisher**, not an intermediary. The intermediary question is unsettled even for Wikipedia (*ANI v. Wikimedia*: the Supreme Court overturned the High Court's takedown order in 2025, but the defamation suit continues).
- **AI makes it worse, not safer.** Courts have not settled whether AI output creates liability. In the US, *Walters v. OpenAI* (2025) was won partly because of prominent disclaimers and a reader who knew the output was wrong. *Starbuck v. Google* survived a motion to dismiss in July 2026. ClaimCheck's case is weaker than a chatbot's: it **publishes** verdicts as fact-checks, to the public, about named people.
- **What happens to fact-checkers in practice.** Alt News co-founder Mohammed Zubair was jailed in 2022 over a four-year-old tweet and faced several criminal cases in different places. Alt News reports that defamation notices are a constant financial drain. The IFCN describes "targeted harassment and threats of litigation".
- **Specific weak points in the code:**
  - **Every statement shows a "verbatim" quote and a named speaker that are never checked.** `context_quote` and `speaker` come straight from Gemini (`prompts.py:62-64`), and nothing compares them with the real transcript. A made-up quote shown under a politician's name is a defamation risk even with no verdict.
  - **Tags describe people's speech.** "Loaded language" and "Hearsay" appear next to a named speaker's words. The prompt tells the model to stay neutral, but the tag itself is a characterisation.
  - **Cache reuse** (see `REPORT.md`, finding 6) can attach another claim's verdict to a slightly different statement.
  - **Memory-only True verdicts** from Verify all are published with no source.
  - **The share image** (`/api/og/[id]`) puts the verdict word in large type next to a channel name. It's built to spread beyond the site, and context gets lost.

### 2. IT Rules 2021, Part III (digital news publishers)

ClaimCheck publishes analysis of current-affairs content, so it likely counts as a "publisher of news and current affairs content". That brings:
- a code of ethics,
- a grievance officer (acknowledge complaints in 24 h, resolve in 15 days),
- reporting its details to the Ministry of Information & Broadcasting,
- a three-tier oversight structure ending in government oversight, which can lead to blocking orders.

### 3. Elections

The Election Commission applies the Model Code of Conduct to online content. In the 2026 state elections it set a **3-hour takedown** expectation for flagged misleading AI content, and acted against **11,000+ posts** with FIRs. A site publishing AI verdicts on candidates during a campaign will draw attention. The 48-hour "silence period" before polling (RP Act s.126) also needs legal advice. Practical step: decide whether to pause or require review for verdicts on political claims during polling periods.

### 4. Government fact-checking and "fake news" laws

- **Fact Check Unit.** The 2023 IT Rules amendment let a government Fact Check Unit (PIB) label content "fake". The Bombay High Court struck it down in 2024. The **Supreme Court agreed in March 2026 to hear the Centre's appeal**, without staying the High Court ruling. If the FCU comes back, a government body could label ClaimCheck's own verdicts false. Separately, ClaimCheck treats PIB as a top-tier source, which is both an editorial and a legal awkwardness.
- **Karnataka's Misinformation and Fake News (Prohibition) Bill 2025.** The draft proposed up to **7 years in jail**, ₹10 lakh fines, and a regulator able to block "false" content. It was reported for the winter 2025 session; I found no confirmation it passed. Andhra Pradesh was reported to be drafting something similar. A fact-checker that publishes a wrong verdict could itself be accused under such laws.

### 5. Religion and communal content

The charges used against fact-checkers are often not defamation but "hurting religious sentiments" or "promoting enmity" (BNS s.196/299). ClaimCheck's policy already hides religion and community statements, which is good. The risk remains through mis-tagging (the model decides `policy_tier`) and through politics that touches religion.

### 6. YouTube API terms: currently in breach

The app works only while Google allows it to use the YouTube API, and losing access would break submissions and the RSS feed.
- **Data older than 30 days (III.E.4.c–d).** Data from the YouTube API can be kept at most 30 days, then must be refreshed or deleted. ClaimCheck keeps titles, lengths, publish dates, channel names and avatars **forever**. The seed script mentions a monthly refresh, but nothing runs it, and video metadata is never refreshed.
- **"Must not modify… functionality of a YouTube player" (III.I.6).** Forcing 1.5× speed and 75% captions on every video is a grey area.
- **"Must not… defame… or harass anyone" (III.I.11).** A wrong "False" verdict about a creator also breaks YouTube's terms.
- **Advertising restriction (III.G.1.d)**, noted above.

### 7. Personal data (DPDP)

The site stores salted IP hashes for rate limiting. Most duties under India's DPDP Rules start on **13 May 2027**. Add a privacy notice and an automatic deletion period for the `submissions` and `verify_requests` tables before then.

### 8. Copyright: low risk

Short verbatim quotes and summaries used for criticism and reporting current events fall under fair dealing (Copyright Act s.52). The app shows source quotes but does not store full fetched pages. Video is embedded through YouTube's official player, not copied.

---

## Part 4: What would reduce the risk and help adoption

**Legal**
1. **Check quotes against the transcript.** Before publishing, check each `context_quote` against the real captions, as the code already does for source quotes, or label it "AI paraphrase" rather than calling it verbatim.
2. **Use prominent "AI-generated, may be wrong" labels** on every verdict and on the share image, plus a visible corrections log. Disclaimers mattered in *Walters v. OpenAI*.
3. **Have a working complaints process**: a named grievance officer, an email address, and a 24 h / 15-day response, as the IT Rules require.
4. **Pause political verdicts, or require review for them, during election periods**, and get specific advice on the silence period.
5. **Drop memory-only True verdicts and fix cache reuse** (`REPORT.md` findings 4 and 6).
6. **Comply with YouTube's terms**: a nightly job to refresh or delete YouTube metadata older than 30 days, and use YouTube's default playback speed.
7. **Set up legal structure and insurance**: incorporate (don't run it personally), get media-liability insurance, and have a lawyer review the content policy, as the README already plans.

**Adoption**
1. **Meet people where they watch**: a browser extension or a "share to WhatsApp" card linking to the exact claim and timestamp.
2. **Pre-verify popular videos** so the first visitor sees results, not an empty page and a Verify button.
3. **Add a Hindi interface**, and output claims in the language spoken.
4. **Make the tagging the product, not the verdicts.** "This 2-hour podcast: 40 claims, 60 opinions, 15 forecasts, 8 pieces of hearsay" is useful, low-risk and instant. Verdicts can be an extra.
5. **Pick one narrow audience first**, e.g. personal-finance and health videos (lower legal heat than politics), and grow from there.

---

## Sources

**Audience and industry**
- [Expand fact-checking to broadcast news (ICFJ)](https://www.icfj.org/news/reach-wider-audience-expand-fact-checking-broadcast-news)
- [Same article (IJNet)](https://ijnet.org/en/story/reach-wider-audience-expand-fact-checking-broadcast-news)
- [Fact-checking is failing (Stanford JSK)](https://jskfellows.stanford.edu/fact-checking-is-failing-heres-why-reaching-critical-audiences-is-essential-a37ff280bdf1?gi=be051e60bb73)
- [Questioning Fact-Checking: An Audience Perspective (Journalism Practice, 2022)](https://www.tandfonline.com/doi/full/10.1080/17512786.2022.2097118)
- [Fact-Checking and Audience Engagement (Digital Journalism)](https://www.tandfonline.com/doi/full/10.1080/21670811.2021.2006073)
- [What the fake-news study means for fact-checkers (Poynter)](https://www.poynter.org/fact-checking/2018/what-that-new-major-study-about-fake-news-means-and-doesnt-mean-for-fact-checkers/)
- [Community-based fact-checking reduces spread on X (Nature Communications 2026)](https://www.nature.com/articles/s41467-026-72597-0)
- [Same study (PMC copy)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13144318/)
- [Duke Reporters' Lab 2026 census](https://reporterslab.org/2026/06/12/2026-census-fact-checking-losses-continue-amid-funding-pressure-but-most-projects-persist/)
- [Duke Reporters' Lab 2025 census](https://reporterslab.org/2025/06/19/fact-checkers-persevere-as-politicians-platforms-turn-up-heat/)
- [Fact-checkers report challenges at GlobalFact 2026 (PolitiFact)](https://www.politifact.com/article/2026/jun/24/at-globalfact-2026-fact-checkers-report-challenges/)
- [Google kills the fact-checking snippet (Nieman Lab)](https://www.niemanlab.org/2025/06/google-kills-the-fact-checking-snippet/)
- [Google removes ClaimReview snippets (Poynter)](https://www.poynter.org/ifcn/2025/google-claimreview-fact-checks-snippets-removed/)
- [The web just got harder to trust (Full Fact)](https://fullfact.org/technology/the-web-just-got-a-little-harder-to-trust/)
- [Google kills ClaimReview (Indicator)](https://indicator.media/p/google-kills-claimreview-fact-checking-meta-monetized-sputnik)
- [Meta's fact-checking decision and India (Business Standard)](https://www.business-standard.com/companies/news/meta-fact-checking-decision-impact-on-india-digital-regulation-125011000186_1.html)
- [Oversight Board warns on Community Notes (Nieman Lab)](https://www.niemanlab.org/2026/03/metas-oversight-board-warns-that-community-notes-arent-a-proper-substitute-for-fact-checking-globally/)
- [Oversight Board asks Meta not to replace fact-checking (The Star)](https://www.thestar.com.my/tech/tech-news/2026/09/14/oversight-board-asks-meta-not-to-replace-fact-checking-with-community-notes)
- [Logically (Wikipedia)](https://en.wikipedia.org/wiki/Logically_(company))
- [Logically files for administration (BeBeez)](https://bebeez.eu/2025/07/06/fact-checker-logically-files-for-administration-after-losing-tiktok-and-meta-contracts)
- [Logically layoffs (Sifted)](https://sifted.eu/articles/anti-misinformation-startup-logically-lays-off-dozens-in-global-cost-cutting-drive)
- [Fact-checking LLM information can decrease headline discernment (PNAS 2024)](https://www.pnas.org/doi/10.1073/pnas.2322823121)
- [AI fact checks can increase belief in false headlines (Phys.org)](https://phys.org/news/2024-12-ai-fact-belief-false-headlines.html)
- [Reuters Institute Digital News Report 2026](https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2026)
- [DNR 2026 executive summary](https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2026/dnr-executive-summary)
- [52% of Indians avoid news, 58% rely on YouTube (The Wire)](https://m.thewire.in/article/media/digital-news-report-by-the-reuters-institute-avoid-news-digital-youtube-social-media-report)

**Legal (India)**
- [India fact-checkers face threats, jail (France 24 / AFP)](https://www.france24.com/en/live-news/20221116-india-fact-checkers-face-threats-jail-in-misinformation-fight)
- [Mohammed Zubair (Wikipedia)](https://en.wikipedia.org/wiki/Mohammed_Zubair_(journalist))
- [Fact checker faces threats, criminal cases (Article 14)](https://article-14.com/post/a-fact-checker-faces-threats-criminal-cases-for-drawing-attention-to-hate-speech-by-hindu-extremists-62a2abc1e66e0)
- [Indian fact-checkers face threats (UCA News)](https://www.ucanews.com/news/indian-fact-checkers-face-threats-in-misinformation-fight/99435)
- [Criminal defamation under IPC and BNS (King Stubb & Kasiva)](https://ksandk.com/md/litigation/criminal-defamation-ipc-bharatiya-nyaya-sanhita/)
- [Section 79 and fact check units (Mondaq)](https://www.mondaq.com/india/it-and-internet/1521872/from-safe-harbor-to-watchdog-section-79-of-the-it-act-controversy-over-fact-check-units)
- [Section 79 explained (ApniLaw)](https://www.apnilaw.com/acts/can-social-media-platforms-be-held-liable-for-harmful-content-section-79-explained)
- [ANI v. Wikimedia (Wikipedia)](https://en.wikipedia.org/wiki/Asian_News_International_v._Wikimedia_Foundation)
- [Why the Supreme Court reversed the Wikipedia takedown (ThePrint)](https://theprint.in/judiciary/why-supreme-court-reversed-delhi-high-courts-wikipedia-page-takedown-order-in-ani-defamation-case/2622282/)
- [Delhi HC ANI v. Wikipedia interim order (SCC Online)](https://www.scconline.com/blog/post/2025/04/07/delhi-high-court-directs-wikipedia-remove-defamatory-content-ani-legal-news/)
- [Delhi HC rejects ANI's interim plea against ChatGPT (LiveLaw)](https://www.livelaw.in/high-court/delhi-high-court/delhi-high-court-rejects-ani-copyright-suit-open-ai-chatgpt-542736)
- [Walters v. OpenAI dismissed (Cleary Gottlieb)](https://www.clearygottlieb.com/news-and-insights/publication-listing/georgia-court-dismisses-defamation-lawsuit-against-openai-over-chatgpt-output)
- [Walters v. OpenAI one year on (Inforrm)](https://inforrm.org/2026/07/24/ai-one-year-on-what-walters-v-openai-tells-us-about-ai-hallucinations-and-defamation-liability-nataly-tedone/)
- [Defamation in the AI era (Quinn Emanuel)](https://www.quinnemanuel.com/the-firm/publications/client-alert-defamation-in-the-ai-era/)
- [AI defamation disputes (Bloomberg Law)](https://news.bloomberglaw.com/esg/ai-defamation-disputes-trip-up-courts-seeking-a-mind-to-blame)
- [AI defamation lawsuit tracker](https://ailawsuittracker.com/issues/defamation/)
- [IT Rules 2021 (MeitY, updated 2023)](https://www.meity.gov.in/static/uploads/2024/02/Information-Technology-Intermediary-Guidelines-and-Digital-Media-Ethics-Code-Rules-2021-updated-06.04.2023-.pdf)
- [IT Rules 2021 Part III explainer (Veritect)](https://veritect.ai/digital-data-ai-law/it-rules-2021-part-iii-digital-media-ethics-code)
- [IT Rules 2021 highlights (Mondaq)](https://www.mondaq.com/india/social-media/1050302/highlights-information-technology-intermediary-guidelines-and-digital-media-ethics-code-rules-2021)
- [Supreme Court to hear FCU appeal (Storyboard18)](https://www.storyboard18.com/how-it-works/supreme-court-agrees-to-hear-centre-appeal-on-it-rules-amendment-on-fact-check-unit-91843.htm)
- [SC refuses stay on FCU judgment (IFF)](https://internetfreedom.in/supreme-court-of-india-issued-notice-but-refused-any-stay-in-union-of-indias-challenge-to-the-bombay-high-court-judgement-holding-fact-check-unit-to-be-ultra-vires/)
- [Karnataka fake news bill (MediaNama)](https://www.medianama.com/2025/06/223-karnataka-misinformation-fake-news-prohibition-bill/)
- [Karnataka proposes stringent fake news law (South First)](https://thesouthfirst.com/news/karnataka-proposes-stringent-law-to-ban-fake-news-faces-legal-and-civil-rights-scrutiny)
- [Karnataka bill planned for winter session (Storyboard18)](https://www.storyboard18.com/amp/digital/karnataka-govt-plans-to-introduce-anti-fake-news-legislation-during-winter-session-83952.htm)
- [Andhra moves to draft a misinformation law (South First)](https://thesouthfirst.com/news/after-karnataka-andhra-moves-to-draft-law-against-misinformation-on-social-media/)
- [ECI 3-hour takedown rule (MediaNama)](https://www.medianama.com/2026/04/223-eci-orders-3-hour-takedown-rule-ai-fake-content-elections/)
- [ECI tightens watch ahead of 2026 polls (Business Today)](https://www.businesstoday.in/india/story/eci-tightens-watch-on-unlawful-social-media-content-ahead-of-2026-polls-526381-2026-04-19)
- [EC acted against 11,000 posts (Scroll)](https://scroll.in/latest/1092227/scroll_in)
- [ECI AI deepfake guidelines, Bihar 2025 (MediaNama)](https://www.medianama.com/2025/10/223-eci-bans-ai-deepfakes-guidelines-bihar-assembly-elections-2025/)
- [DPDP Act and Rules timeline (Taxmann)](https://www.taxmann.com/post/blog/analysis-indias-dpdp-act-and-rules/)
- [DPDP Rules 2025 (TCSA)](https://www.tcsa.in/frameworks/dpdp/rules-2025)

**YouTube**
- [YouTube API Services Developer Policies (official)](https://developers.google.com/youtube/terms/developer-policies)
- [Required Minimum Functionality (official)](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [Complying with YouTube's Developer Policies (official)](https://developers.google.com/youtube/terms/developer-policies-guide)
