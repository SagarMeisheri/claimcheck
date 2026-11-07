"""Answer tags: what code does with the classifier's answers. The classifier is replaced; no keys or network."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from google.adk.labs.classifiers import BinaryAnswer, ChoiceAnswer, ClassifierResponse

from claimcheck.agents import tags
from claimcheck.agents.research import Research
from claimcheck.config import Settings
from claimcheck.context import Budget, BudgetExceeded, EpisodeContext, set_context


def research(pages=None):
    pts = [{"text": "Pakistan's establishment is hostile.", "kind": "interpretation", "status": "sources_found"}]
    r = Research(points=pts, positions=[], queries=["q"], related=[], counter=[], summary="", counter_summary="", match="medium")
    r.all_pages = pages or []
    return r


def page(site, text="The army frames foreign policy.", independence="independent"):
    return {"url": f"https://{site}/a", "site": site, "title": f"{site} page", "date": "2024-05-01", "independence": independence, "text": text}


def choice(label, p=0.8, options=("supported", "partly", "contradicted", "unverified", "opinion")):
    rest = (1 - p) / (len(options) - 1)
    return ChoiceAnswer(choice=label, probabilities={o: (p if o == label else rest) for o in options})


def answers(support="supported", match="high", bias="leans", stake=0.1, p=0.8):
    return {"support": choice(support, p), "match": choice(match, p, ("high", "medium", "low")),
            "bias": choice(bias, p, ("balanced", "leans", "one_sided", "cant_tell")),
            "stake": BinaryAnswer(probability=stake)}


CTX = {"statement": "Pakistan harbors negative intentions toward India.", "statement_type": "opinion", "question_kind": "asked", "asked_by": "Raj Shamani",
       "question": "What are Pakistan's intentions?", "question_spoken": "So, are they ever going to want peace?",
       "speaker": {"name": "Sushant Sareen", "role": "Senior fellow", "affiliations": "Observer Research Foundation"},
       "creator": {"podcast": "The Show", "leaning": "Described as centre-right"}}


def test_each_tag_is_shown_only_what_it_needs():
    r = research([page("nbr.org"), page("gov.nic.in")])
    inp = tags.tag_inputs(CTX, r)
    assert list(inp) == ["support", "match", "bias", "stake", "question_type"]
    # support and match: the answer, its points and the pages; no profiles
    assert set(inp["support"]) == {"question_as_asked", "answer", "answer_type", "points", "pages"} and set(inp["match"]) == {"answer", "answer_type", "points", "pages"}
    # stake: the answer and both profiles; no pages
    assert set(inp["stake"]) == {"answer", "answer_type", "speaker_profile", "show_profile"}
    assert "Observer Research Foundation" in inp["stake"]["speaker_profile"] and "centre-right" in inp["stake"]["show_profile"]
    # the question type never sees the answer
    assert "answer" not in inp["question_type"] and "pages" not in inp["question_type"] and "Observer Research Foundation" in inp["question_type"]["speaker_profile"]
    assert inp["question_type"]["question_as_asked"] == "So, are they ever going to want peace?" and inp["question_type"]["asked_by"] == "Raj Shamani"
    # bias: the answer, the question, the profiles and a few pages
    assert set(inp["bias"]) == {"question_as_asked", "answer", "answer_type", "speaker_profile", "show_profile", "pages"}


def test_the_pages_are_every_search_excerpt_all_alike_and_the_limits_differ_by_tag():
    r = research([page(f"s{i}.example", text="x" * 2000) for i in range(45)])
    inp = tags.tag_inputs(CTX, r)
    assert [p["site"] for p in inp["support"]["pages"]] == [f"s{i}.example" for i in range(30)] and len(inp["support"]["pages"][0]["text"]) == tags.PAGE_TEXT_CHARS
    assert len(inp["bias"]["pages"]) == tags.BIAS_PAGES and len(inp["bias"]["pages"][0]["text"]) == tags.BIAS_PAGE_CHARS
    mixed = tags.tag_inputs(CTX, research([page("a.example", independence="own_organisation"), page("b.example", independence="same_episode")]))
    assert [p["site"] for p in mixed["support"]["pages"]] == ["a.example", "b.example"] and "independent" not in str(mixed["support"]["pages"])
    assert mixed["support"]["pages"][0]["date"] == "2024-05-01"


def test_without_profiles_or_pages_the_inputs_say_so():
    inp = tags.tag_inputs({"statement": "x"}, research())
    assert inp["stake"]["speaker_profile"] == "no profile found" and inp["support"]["pages"] == "the searches returned no pages"


def test_the_questions_are_choices_and_binaries():
    assert set(tags.QUESTIONS) == {"support", "match", "bias", "stake", "question_type"}
    assert set(tags.QUESTIONS["support"].criteria) == set(tags.SUPPORT) and set(tags.QUESTIONS["question_type"].criteria) == set(tags.QTYPES)


def test_the_tags_come_from_the_classifiers_answers():
    t = tags.decide(answers("supported", "high", "leans", stake=0.9), research([page('a.example')]))
    assert t["support"] == {"label": "supported", "p": 0.8} and t["match"]["label"] == "high" and t["bias"]["label"] == "leans"
    assert t["stake"] == {"yes": True, "p": 0.9}


def test_support_needs_at_least_one_page_of_any_kind():
    assert tags.decide(answers("supported"), research([page("company.example", independence="own_organisation")]))["support"]["label"] == "supported"
    assert tags.decide(answers("partly"), research([page("gov.nic.in")]))["support"]["label"] == "partly"
    assert tags.decide(answers("contradicted"), research())["support"]["label"] == "unverified"  # no page at all
    assert tags.decide(answers("opinion"), research())["support"]["label"] == "opinion"  # needs no page


def test_contradicted_needs_more_confidence_than_the_other_labels():
    assert tags.decide(answers("contradicted", p=0.5), research([page("a.example")]))["support"] == {"label": "partly", "p": 0.5}
    assert tags.decide(answers("contradicted", p=0.7), research([page("a.example")]))["support"]["label"] == "contradicted"
    assert tags.decide(answers("supported", p=0.5), research([page("a.example")]))["support"]["label"] == "supported"


def test_an_unsure_classifier_falls_back_to_the_cautious_label():
    t = tags.decide(answers("supported", "high", "one_sided", p=0.3), research([page('a.example')]))
    assert (t["support"]["label"], t["match"]["label"], t["bias"]["label"]) == ("unverified", "medium", "cant_tell")


def test_match_cannot_contradict_support():
    assert tags.decide(answers("unverified", "high"), research([page('a.example')]))["match"]["label"] == "medium"
    assert tags.decide(answers("supported", "low"), research([page('a.example')]))["match"]["label"] == "medium"
    assert tags.decide(answers("unverified", "low"), research([page('a.example')]))["match"]["label"] == "low"


# --- the step -------------------------------------------------------------------------------------

def make_ec(spent=0.0, **kw):
    ec = EpisodeContext(episode_id="e", video_id="v", settings=Settings(max_cost_usd_per_episode=3.0, **kw), policy={}, store=NS(),
                        budget=Budget(cap_usd=3.0, spent_usd=spent), plugins_factory=lambda: [])
    ec.logs = []
    ec.log = lambda *a, **k: ec.logs.append(a)
    return ec


def run(monkeypatch, r, ec=None, response=None, boom=None, fail=()):
    """Replaces each tag's classifier call: it answers its own question from `response` (all the answers) and records the call."""
    ec = ec or make_ec()
    seen = []
    response = response or answers()

    async def fake(name, payload):
        seen.append((name, payload))
        if boom:
            raise boom
        if name in fail:
            raise RuntimeError(f"{name} model down")
        return ClassifierResponse(answers={name: response[name]} if name in response else {})

    monkeypatch.setattr(tags, "_classify", fake)

    async def go():
        token = set_context(ec)
        try:
            await tags.tag_answer(CTX, r)
        finally:
            token.var.reset(token)

    asyncio.run(go())
    return ec, seen


def test_tagging_puts_the_tags_the_correctness_and_the_match_on_the_research(monkeypatch):
    r = research([page("nbr.org"), page("hudson.org"), page("idsa.in")])
    _, seen = run(monkeypatch, r, response=answers("partly", "medium", "balanced", stake=0.7))
    s = r.stored()
    assert sorted(n for n, _ in seen) == sorted(tags.QUESTIONS) and len(seen) == 5          # one classifier call per tag
    assert "question_type" not in s["tags"]                                                  # this fake answered only four of them
    assert s["tags"]["support"]["label"] == "partly" and s["tags"]["stake"]["yes"] is True
    assert s["correctness"]["label"] == "partly" and s["correctness"]["evidence"] == "strong" and len(s["correctness"]["basis"]) == 3
    assert r.match == "medium"


def test_a_failing_tag_is_left_out_and_logged_and_the_others_still_land(monkeypatch):
    r = research([page("a.example")])
    ec, _ = run(monkeypatch, r, fail=("bias", "stake"))
    t = r.stored()["tags"]
    assert "bias" not in t and "stake" not in t and t["support"]["label"] == "supported" and t["match"]["label"] == "high"
    assert sum(1 for l in ec.logs if l[1] == "tag_failed") == 2 and r.correctness["label"] == "supported"


def test_when_every_classifier_fails_the_research_stays_untagged(monkeypatch):
    r = research([page("a.example")])
    ec, _ = run(monkeypatch, r, boom=RuntimeError("model down"))
    assert "tags" not in r.stored() and r.correctness is None and r.match == "medium" and sum(1 for l in ec.logs if l[1] == "tag_failed") == 5


def test_a_budget_error_is_not_swallowed(monkeypatch):
    with pytest.raises(BudgetExceeded):
        run(monkeypatch, research([page('a.example')]), boom=BudgetExceeded("cap"))


def test_it_does_not_run_when_off_or_when_the_video_cannot_pay_for_it(monkeypatch):
    _, seen = run(monkeypatch, research([page('a.example')]), ec=make_ec(tag_answers=False))
    assert seen == []
    _, seen = run(monkeypatch, research([page('a.example')]), ec=make_ec(spent=2.995))
    assert seen == []


# --- the question tags: their own classifier calls too ------------------------------------------------

def with_question(qtype="leading", p=0.8, **kw):
    a = answers(**kw)
    a["question_type"] = choice(qtype, p, tags.QTYPES)
    return a


def test_the_question_type_is_a_call_of_its_own_with_the_answer_tags_unchanged():
    t = tags.decide(with_question("leading", 0.9), research([page("a.example")]))
    assert t["question_type"] == {"label": "leading", "p": 0.9}
    assert t["support"]["label"] == "supported"


def test_an_unsure_question_type_is_unclear():
    assert tags.decide(with_question("softball", 0.3), research([page("a.example")]))["question_type"]["label"] == "unclear"


def test_a_tag_with_no_answer_is_absent_not_defaulted():
    t = tags.decide({"bias": answers()["bias"]}, research())
    assert list(t) == ["bias"]
    assert tags.question_analysis(CTX, t) is None                                      # no question tag to save


def test_the_question_tags_are_saved_on_the_answer_with_whether_they_came_from_the_hosts_own_words():
    t = tags.decide(with_question("challenging", 0.8), research())
    assert tags.question_analysis(CTX, t) == {"type": "challenging", "p": 0.8, "spoken": True}
    plain = {k: v for k, v in CTX.items() if k != "question_spoken"}
    assert tags.question_analysis(plain, t)["spoken"] is False                      # tagged from the AI's plain-words rewrite: approximate
    assert tags.question_analysis({**CTX, "question_kind": "implied"}, t) is None   # nobody asked it
    assert tags.question_analysis({"statement": "x"}, t) is None                    # no question at all


def test_a_plain_words_question_comes_with_a_note_not_to_infer_wording_that_is_not_there():
    inp = tags.tag_inputs({k: v for k, v in CTX.items() if k != "question_spoken"}, research())
    assert inp["question_type"]["question_as_asked"] == "What are Pakistan's intentions?" and "plain-words rewrite" in inp["question_type"]["note"]
    assert "note" not in tags.tag_inputs(CTX, research())["question_type"]


def test_tagging_runs_all_five_calls_and_puts_the_question_analysis_on_the_research(monkeypatch):
    r = research([page("a.example")])
    _, seen = run(monkeypatch, r, response=with_question("leading", 0.85))
    assert len(seen) == 5 and r.question_analysis == {"type": "leading", "p": 0.85, "spoken": True}
    assert r.stored()["tags"]["question_type"]["label"] == "leading"
    assert dict(seen)["question_type"].keys().isdisjoint({"answer", "pages"})          # the question type never saw the answer or the pages
