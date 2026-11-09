"""Tagging an answer (agents/qa_tags.py) and assessing it against its pages (agents/assess.py): routing by claim type, what each call sees,
the verdict from the claims, and the skepticism rules. The classifier, the research and the assessment call are replaced; no keys or network."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from google.adk.labs.classifiers import BinaryAnswer, ChoiceAnswer, ClassifierResponse

from claimcheck.agents import assess, qa_tags, research
from claimcheck.agents.research import Research
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext, set_context
from claimcheck.schemas import AssessOut, ClaimFinding, PageNote


def ch(label, opts, p=0.8):
    rest = (1 - p) / (len(opts) - 1)
    return ChoiceAnswer(choice=label, probabilities={o: (p if o == label else rest) for o in opts})


def yes(p=0.9):
    return BinaryAnswer(probability=p)


def page(site="news.example", independence="independent"):
    return {"url": f"https://{site}/a", "site": site, "title": "t", "date": "2026-01-01", "independence": independence, "text": "Wukong cost about $70 million to make, the studio said."}


def make_research(pages):
    r = Research(points=[{"text": "A point.", "kind": "figure", "status": "sources_found"}], positions=[], queries=["q"], related=[],
                 counter=[], summary="", counter_summary="", match="medium")
    r.all_pages = pages
    r.pages = [{"url": pg["url"], "site": pg["site"], "title": pg["title"], "independence": pg["independence"]} for pg in pages]
    return r


def finding(verdict="supported", page=1, claim="Wukong cost at least $70 million.", reason="The page gives the same figure.", quote="", says="The page says about $70 million."):
    return ClaimFinding(claim=claim, verdict=verdict, page=page, page_says=says if page else "", quote=quote, reason=reason)


def assessed(*findings, pages=1, relevant=True, missing_context=""):
    """What the assessment call returns: a line for each of `pages` pages and the claims."""
    return AssessOut(pages=[PageNote(page=i, tldr=f"Page {i} reports a cost.", relevant=relevant) for i in range(1, pages + 1)],
                     overview="The pages agree on the cost.", claims=list(findings or [finding()]), missing_context=missing_context)


CTX = {"statement": "Black Myth: Wukong cost at least $70 million.", "context_quote": "Wukong was seventy million...",
       "question": "How much does a game cost?", "question_spoken": "My only question is, how much money does it take?",
       "question_kind": "asked", "asked_by": "Vinamre Kasanaa",
       "speaker": {"name": "Varun Mayya", "role": "Co-founder of Aeos", "businesses": [{"name": "Aeos", "relation": "founder", "url": "https://a.example"}]}}


def run(monkeypatch, answers, ctx=CTX, pages=(page(),), points=True, fail=(), boom=None, settings=None, spent=0.0, out=None):
    """Runs tag_answer with `answers` as every classifier question's answer and `out` as the assessment (an AssessOut, an exception, or by
    default one supported claim). Returns (tags, research, calls, ec); the assessment calls are in ec.assessed."""
    calls, seen = [], []

    async def classify(names, payload, extra=None):
        calls.append((tuple(names), payload))
        if boom:
            raise boom
        if set(names) & set(fail):
            raise RuntimeError("model down")
        return ClassifierResponse(answers={n: answers[n] for n in names if n in answers})

    async def generate(state):
        seen.append(state)
        res = assessed(pages=len(pages)) if out is None else out
        if isinstance(res, Exception):
            raise res
        return res

    async def fake_research(ctx, location, force=False):
        return make_research(list(pages)) if points else None

    monkeypatch.setattr(qa_tags, "_classify", classify)
    monkeypatch.setattr(assess, "_generate", generate)
    monkeypatch.setattr(research, "research_answer", fake_research)
    ec = EpisodeContext(episode_id="e", video_id="v", settings=settings or Settings(max_cost_usd_per_episode=3.0), policy={}, store=NS(),
                        budget=Budget(cap_usd=3.0, spent_usd=spent), plugins_factory=lambda: [])
    ec.assessed = seen

    async def go():
        token = set_context(ec)
        try:
            return await qa_tags.tag_answer(ctx, None)
        finally:
            token.var.reset(token)

    t = asyncio.run(go())
    return t.tags, t.research, calls, ec


BASE = {"answer_type": ch("evasive", qa_tags.ATYPES), "claim_type": ch("objective_fact", qa_tags.CTYPES)}


def test_a_researched_answer_costs_a_tagging_call_and_an_assessment_and_gets_the_chain(monkeypatch):
    tags, r, calls, ec = run(monkeypatch, BASE)
    assert [c[0] for c in calls] == [("answer_type", "claim_type", "stake_link", "stake_item", "self_serving_pivot", "disclosed")]
    assert len(ec.assessed) == 1
    assert tags["answer"]["type"] == "evasive" and tags["claim"]["type"] == "objective_fact" and tags["grounding"]["label"] == "grounded"
    assert tags["chain"] == "Evasive A → Objective fact → Grounded" and tags["grounding"]["evidence"] == "limited" and r.match == "high"


def test_a_pure_opinion_is_exempt_with_one_call_and_no_search(monkeypatch):
    tags, r, calls, ec = run(monkeypatch, {**BASE, "claim_type": ch("pure_opinion", qa_tags.CTYPES, 0.9)})
    assert len(calls) == 1 and r is None and ec.assessed == [] and tags["grounding"]["label"] == "exempt" and tags["chain"].endswith("Pure opinion → Exempt")


def test_an_unsure_pure_opinion_is_researched_after_all(monkeypatch):
    tags, r, calls, ec = run(monkeypatch, {**BASE, "claim_type": ch("pure_opinion", qa_tags.CTYPES, 0.5)})
    assert r is not None and len(ec.assessed) == 1 and tags["grounding"]["label"] == "grounded"


def test_nothing_checkable_makes_a_prediction_exempt_and_a_fact_plausible(monkeypatch):
    tags, r, _, _ = run(monkeypatch, {**BASE, "claim_type": ch("prediction", qa_tags.CTYPES)}, points=False)
    assert r is None and tags["grounding"]["label"] == "exempt"
    tags, _, _, _ = run(monkeypatch, BASE, points=False)
    assert tags["grounding"]["label"] == "plausible"  # the speaker's own history: no public record


def test_searches_that_return_no_page_leave_the_answer_plausible_and_make_no_call(monkeypatch):
    tags, r, _, ec = run(monkeypatch, BASE, pages=())
    assert ec.assessed == [] and tags["grounding"]["label"] == "plausible" and "failed" not in tags


def test_every_answer_is_set_against_the_speakers_profile_whatever_their_tags(monkeypatch):
    tags, _, calls, _ = run(monkeypatch, BASE)  # CTX has a profile (a business) but no incentive tag at all
    assert calls[0][0] == ("answer_type", "claim_type", "stake_link", "stake_item", "self_serving_pivot", "disclosed")
    assert "Aeos" in str(calls[0][1]["speaker_profile"]) and "pages" not in calls[0][1]
    assert calls[0][1]["question_as_asked"] == CTX["question_spoken"] and calls[0][1]["spoken_words"].startswith("Wukong")
    assert tags["profile_checked"] >= 1 and "stake" not in tags and "conflict" not in tags  # compared, nothing found


def test_a_speaker_with_no_profile_has_nothing_to_compare(monkeypatch):
    bare = {k: v for k, v in CTX.items() if k != "speaker"}
    tags, _, calls, _ = run(monkeypatch, BASE, ctx=bare)
    assert calls[0][0] == ("answer_type", "claim_type") and "profile_checked" not in tags


STAKE = {**CTX, "speaker_incentives": {"commercial": {"reason": "Founder of Aeos", "url": "https://a.example/p", "site": "a.example"},
                                       "access_preserving": {"reason": "internal only"}}}
LINK = {"stake_link": ch("benefits", qa_tags.STAKE_LINKS), "stake_item": ch("1", ["1", "2", "3"])}


def test_internal_tags_are_never_offered_as_a_stake():
    items = qa_tags.stake_items(STAKE)
    assert items[0]["kind"] == "commercial" and "internal" not in str(items)


SELF = {**BASE, **LINK, "answer_type": ch("narrative", qa_tags.ATYPES), "claim_type": ch("anchored_opinion", qa_tags.CTYPES), "disclosed": yes(0.8)}


def test_rule_1_a_claim_backed_only_by_the_speakers_own_organisation_is_ungrounded(monkeypatch):
    tags, _, calls, _ = run(monkeypatch, SELF, ctx=STAKE, pages=[page("aeos.example", "own_organisation")])
    assert "Aeos" in str(calls[0][1]["speaker_profile"])
    assert tags["grounding"]["label"] == "ungrounded" and tags["grounding"]["was"] == "grounded"
    assert tags["conflict"] == {"kind": "self_report", "disclosure": "disclosed"}
    assert tags["stake"]["link"] == "benefits" and tags["stake"]["item"] == {
        "kind": "commercial", "text": "commercial: Founder of Aeos", "url": "https://a.example/p", "site": "a.example"}
    assert tags["stake"]["disclosure"] == "disclosed"
    assert tags["chain"] == "Narrative A → Anchored opinion → Ungrounded (self-report, disclosed)"


def test_rule_1_a_self_serving_claim_no_page_settles_is_ungrounded(monkeypatch):
    tags, _, _, _ = run(monkeypatch, SELF, ctx=STAKE, out=assessed(finding("not_found", page=0, reason="No page gives this figure.")))
    assert tags["grounding"]["label"] == "ungrounded" and tags["grounding"]["was"] == "plausible"


def test_rule_1_an_independent_page_that_backs_part_of_it_keeps_it_partly_grounded(monkeypatch):
    """The roti case: the rice decline is on an independent page, the roti RDA figure is on none. That is 'partly', not 'ungrounded'."""
    out = assessed(finding("partly", reason="The page reports a fall in rice zinc but gives no roti or RDA figure."),
                   finding("not_found", page=0, claim="Roti gave 56% of the zinc RDA, now 25%.", reason="No page gives these figures."))
    tags, _, _, _ = run(monkeypatch, SELF, ctx=STAKE, out=out)
    g = tags["grounding"]
    assert g["label"] == "partly" and "was" not in g and tags["conflict"]["kind"] == "self_report"
    assert [c["verdict"] for c in g["claims"]] == ["partly", "not_found"] and g["claims"][0]["reason"].startswith("The page reports")
    assert tags["chain"].startswith("Narrative A → Anchored opinion → Partly grounded")


def test_rule_1_an_independent_page_keeps_a_grounded_self_serving_claim(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**SELF, "disclosed": yes(0.2)}, ctx=STAKE,
                        pages=[page("aeos.example", "own_organisation"), page("reuters.example")],
                        out=assessed(finding(page=2), pages=2))
    assert tags["grounding"]["label"] == "grounded" and tags["conflict"]["disclosure"] == "undisclosed"


def test_a_touched_stake_is_shown_but_is_not_a_conflict(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**BASE, **LINK, "stake_link": ch("touches", qa_tags.STAKE_LINKS), "disclosed": yes(0.2)}, ctx=STAKE)
    assert tags["stake"]["link"] == "touches" and tags["stake"]["disclosure"] == "undisclosed"
    assert "conflict" not in tags and tags["grounding"]["label"] == "grounded"


def test_an_unsure_link_or_item_finds_no_stake(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**BASE, **LINK, "stake_link": ch("benefits", qa_tags.STAKE_LINKS, 0.4)}, ctx=STAKE)
    assert "stake" not in tags and "conflict" not in tags
    tags, _, _, _ = run(monkeypatch, {**BASE, **LINK, "stake_item": ch("1", ["1", "2", "3"], 0.2)}, ctx=STAKE)
    assert "stake" not in tags


def test_rule_2_missing_context_is_flagged_only_for_ideological_or_financial_speakers(monkeypatch):
    out = assessed(missing_context="A later page gives a lower base rate that changes the picture.")
    tags, _, _, _ = run(monkeypatch, BASE, ctx={**CTX, "speaker_incentives": {"ideological": {}}}, out=out)
    assert tags["grounding"]["label"] == "grounded" and tags["flags"] == ["missing_context"]
    assert tags["grounding"]["missing_context"].startswith("A later page") and tags["chain"].endswith("Grounded (missing context)")
    assert "flags" not in run(monkeypatch, BASE, out=out)[0]


def test_a_self_serving_pivot_counts_only_for_a_pivot(monkeypatch):
    tags, _, _, _ = run(monkeypatch, {**BASE, "self_serving_pivot": yes()}, ctx=STAKE)
    assert "conflict" not in tags  # evasive, not a pivot
    tags, _, _, _ = run(monkeypatch, {**BASE, "answer_type": ch("pivot", qa_tags.ATYPES), "self_serving_pivot": yes()}, ctx=STAKE)
    assert tags["flags"] == ["self_serving_pivot"] and tags["conflict"]["kind"] == "self_serving_pivot"


def test_staged_pushback_is_asked_only_when_the_host_is_tagged_soft(monkeypatch):
    soft = {**CTX, "host_incentives": {"invested_peer": {}}, "host": {"name": "Host"}}
    tags, _, calls, _ = run(monkeypatch, {**BASE, "staged_pushback": yes()}, ctx=soft)
    assert "staged_pushback" in calls[0][0] and "host_interests" in calls[0][1] and tags["flags"] == ["staged_pushback"]
    _, _, calls, _ = run(monkeypatch, BASE, ctx={**CTX, "host_incentives": {"adversarial": {}}})
    assert "staged_pushback" not in calls[0][0]


def test_a_low_confidence_answer_type_falls_back_to_unclear(monkeypatch):
    assert run(monkeypatch, {**BASE, "answer_type": ch("pivot", qa_tags.ATYPES, 0.3)})[0]["answer"]["type"] == "unclear"


def test_a_failed_tagging_call_is_left_out_and_routes_to_research(monkeypatch):
    tags, r, _, ec = run(monkeypatch, BASE, fail=("answer_type",))
    assert r is not None and "answer" not in tags and "claim" not in tags and tags["grounding"]["label"] == "grounded"
    assert tags["failed"] == sorted(["answer_type", "claim_type", "stake_link", "stake_item", "self_serving_pivot", "disclosed"]) and any(e.rule == "tag_failed" for e in ec.events)


def test_a_budget_error_is_never_swallowed(monkeypatch):
    with pytest.raises(BudgetExceeded):
        run(monkeypatch, BASE, boom=BudgetExceeded("cap"))
    with pytest.raises(BudgetExceeded):
        run(monkeypatch, BASE, out=BudgetExceeded("cap"))


def test_with_tags_off_the_answer_is_only_researched(monkeypatch):
    tags, r, calls, _ = run(monkeypatch, BASE, settings=Settings(tag_answers=False))
    assert tags is None and r is not None and calls == []


def test_a_research_failure_reaches_the_caller_as_itself(monkeypatch):
    async def down(ctx, location, force=False):
        raise research.ResearchUnavailable("every search failed")

    monkeypatch.setattr(research, "research_answer", down)
    monkeypatch.setattr(qa_tags, "_classify", lambda names, payload, extra=None: _answer_with(names))
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(), policy={}, store=NS(), budget=Budget(cap_usd=3.0), plugins_factory=lambda: [])

    async def go():
        token = set_context(ec)
        try:
            await qa_tags.tag_answer(CTX, None)
        finally:
            token.var.reset(token)

    with pytest.raises(research.ResearchUnavailable):
        asyncio.run(go())


async def _answer_with(names):
    return ClassifierResponse(answers={n: BASE[n] for n in names if n in BASE})


# --- The assessment: the answer's claims against the pages (agents/assess.py) ---------------------------------

PAGES = (
    {**page("bloomberg.com"), "title": "AI capex", "text": "Big tech may spend about $200 billion on AI in 2025, a two-year gain that triples 2020-2022."},
    {**page("other.example"), "text": "Unrelated."},
)
QUOTE = "may spend about $200 billion on AI in 2025"
WRONG = finding("contradicted", claim="AI needs $1.5 to 2 trillion in revenue", says="Big tech capex is about $200 billion in 2025",
                reason="The answer talks of revenue needed; the page gives capex of $200 billion, not trillions.", quote=QUOTE)


def tags_for(monkeypatch, out, pages=PAGES):
    return run(monkeypatch, BASE, pages=pages, out=out)[0]


def test_every_page_gets_a_tldr_and_every_claim_a_verdict_and_a_reason(monkeypatch):
    out = assessed(finding("supported"), finding("partly", claim="It rose every year.", reason="The page covers one year only."), pages=2)
    tags, r, _, ec = run(monkeypatch, BASE, pages=PAGES, out=out)
    assert [p["tldr"] for p in r.pages] == ["Page 1 reports a cost.", "Page 2 reports a cost."] and all(p["relevant"] for p in r.pages)
    assert tags["grounding"]["overview"] and [c["verdict"] for c in tags["grounding"]["claims"]] == ["supported", "partly"]
    assert all(c["reason"] for c in tags["grounding"]["claims"]) and tags["grounding"]["claims"][0]["site"] == "bloomberg.com"
    assert "PAGE 1" in ec.assessed[0]["pages"] and "PAGE 2" in ec.assessed[0]["pages"] and ec.assessed[0]["question"]


def test_the_label_comes_from_the_claims_not_from_the_model():
    v = lambda *vs: assess.label_of([{"verdict": x} for x in vs])  # noqa: E731
    assert v("supported", "supported") == "grounded" and v("supported", "partly") == "partly" and v("supported", "not_found") == "partly"
    assert v("partly") == "partly" and v("not_found", "not_found") == "plausible" and v("supported", "contradicted", "not_found") == "contradicted"


def test_a_contradicted_claim_gives_what_was_said_and_how_the_page_differs(monkeypatch):
    g = tags_for(monkeypatch, assessed(WRONG, pages=2))["grounding"]
    c = g["contradiction"]
    assert g["label"] == "contradicted"
    assert c["said"].startswith("AI needs") and c["sources_say"].startswith("Big tech") and c["difference"].startswith("The answer talks")
    assert c["site"] == "bloomberg.com" and c["url"] == "https://bloomberg.com/a" and c["quote"] == QUOTE
    assert g["basis"][0]["url"] == "https://bloomberg.com/a" and g["basis"][0]["quote"] == QUOTE and g["basis"][0]["finding"] == "Page 1 reports a cost."


def test_a_contradiction_needs_a_quote_that_is_on_the_page(monkeypatch):
    g = tags_for(monkeypatch, assessed(WRONG.model_copy(update={"quote": "spending will reach $5 trillion by 2030"}), pages=2))["grounding"]
    assert g["label"] == "partly" and "contradiction" not in g and "not treated as a contradiction" in g["claims"][0]["reason"]
    g = tags_for(monkeypatch, assessed(WRONG.model_copy(update={"quote": ""}), pages=2))["grounding"]
    assert g["label"] == "partly"


def test_a_supported_claim_with_a_quote_that_is_not_on_the_page_keeps_the_verdict_and_drops_the_quote(monkeypatch):
    g = tags_for(monkeypatch, assessed(finding(quote="spending will reach $5 trillion by 2030"), pages=2))["grounding"]
    assert g["label"] == "grounded" and "quote" not in g["claims"][0]


def test_a_quote_may_use_ellipses_and_any_case(monkeypatch):
    out = assessed(WRONG.model_copy(update={"quote": "MAY SPEND about $200 billion ... a two-year gain that triples"}), pages=2)
    assert tags_for(monkeypatch, out)["grounding"]["contradiction"]["quote"]


def test_a_verdict_that_names_no_real_page_is_not_found(monkeypatch):
    for page_no in (0, 9):
        g = tags_for(monkeypatch, assessed(finding("supported", page=page_no), pages=2))["grounding"]
        assert g["label"] == "plausible" and g["claims"][0]["verdict"] == "not_found" and "url" not in g["claims"][0]


def test_match_is_the_share_of_pages_that_speak_to_a_claim(monkeypatch):
    assert tags_for(monkeypatch, assessed(pages=2))["match"] == {"label": "high", "p": 1.0}
    assert tags_for(monkeypatch, assessed(pages=2, relevant=False))["match"] == {"label": "low", "p": 0.0}
    mixed = assessed(pages=2).model_copy(update={"pages": [PageNote(page=1, tldr="a", relevant=True), PageNote(page=2, tldr="b", relevant=False)]})
    many = tuple(page(f"s{i}.example") for i in range(4))
    out = assessed(pages=4).model_copy(update={"pages": [PageNote(page=1, tldr="a", relevant=True)] + [PageNote(page=i, tldr="b", relevant=False) for i in (2, 3, 4)]})
    assert tags_for(monkeypatch, out, pages=many)["match"] == {"label": "medium", "p": 0.25}
    assert tags_for(monkeypatch, mixed)["match"]["label"] == "high"


def test_a_failed_assessment_leaves_the_answer_without_a_grounding_tag_and_says_so(monkeypatch):
    tags, r, _, ec = run(monkeypatch, BASE, out=RuntimeError("model down"))
    assert r is not None and "grounding" not in tags and tags["failed"] == ["grounding"] and any(e.rule == "assess_failed" for e in ec.events)
    tags, _, _, _ = run(monkeypatch, BASE, out=AssessOut())  # a reply with no usable claim
    assert "grounding" not in tags and tags["failed"] == ["grounding"]
