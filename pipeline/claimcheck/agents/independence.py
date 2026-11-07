"""Which web pages can be a source for an answer, and which only repeat it.

A search on the answer's own words finds pages that repeat the answer: this episode's own listing or transcript, and the
speaker's own organisation saying the same thing (a company's press page for its CEO's figure). Those can't show that
anyone else says it. Each page gets a label, by code only (no model):

  same_episode      the episode itself, a transcript or a listing of it (policy.yaml sources.same_episode_hosts, the video's
                    own id, or a title that is the video's title).
  own_organisation  the site of an organisation the speaker is tied to (their profile's affiliations and role) or of the show.
  independent       everything else.
All three are kept and treated alike: the label only tells a reader where a page comes from.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from ..schemas import Source

INDEPENDENT, OWN, EPISODE = "independent", "own_organisation", "same_episode"

# Words in a role or affiliation that name a job or a kind of person, not an organisation.
_GENERIC = set("""ceo cfo cto coo cmo cio md founder cofounder co-founder cofounders director directors chairman chairperson chair
president vicepresident vice vp partner head manager managing executive former formerly ex current senior junior lead leader
host cohost co-host anchor editor chief professor prof dr mr mrs ms economist journalist author writer analyst researcher
scientist engineer investor entrepreneur advisor adviser consultant commentator expert spokesperson spokesman minister
governor secretary officer member board trustee fellow lecturer teacher student columnist correspondent reporter blogger
podcaster creator youtuber contributor associate assistant deputy joint general national global regional the and of at for in on with by to a an""".split())
_FRAGMENTS = re.compile(r"[,;/|&()]|\s[-–—]\s|\bat\b|\bof\b|\bfor\b|\band\b", re.I)
_WORD = re.compile(r"[A-Za-z0-9]+")
_TOKEN = re.compile(r"[a-z0-9]+")


def _slug(text: str) -> str:
    return "".join(_TOKEN.findall((text or "").lower()))


def org_terms(ctx: dict[str, Any]) -> list[str]:
    """Names of the organisations the speaker (and the show) are tied to, from the lookup context: the profile's
    affiliations and the role ('Co-Founder, Razorpay' -> Razorpay), plus the show's name. Short names only count when
    they are acronyms (NPCI, RBI), so 'Mint' or 'Economist' don't match a newspaper."""
    speaker = ctx.get("speaker") or {}
    raw: list[str] = [a for a in (speaker.get("affiliations") or []) if isinstance(a, str)]
    for field in (speaker.get("role"), speaker.get("summary")):
        if isinstance(field, str):
            raw.extend(_FRAGMENTS.split(field))
    creator = ctx.get("creator") or {}
    raw += [creator.get("podcast") or "", (ctx.get("video") or {}).get("channel") or ""]
    terms: list[str] = []
    for frag in raw:
        words = [w for w in _WORD.findall(frag or "") if w.lower() not in _GENERIC]
        if not words or len(words) > 4:
            continue
        phrase = " ".join(words)
        slug = _slug(phrase)
        acronym = len(words) == 1 and words[0].isupper() and len(slug) >= 3
        if len(slug) >= 5 or acronym:
            terms.append(slug)
    speaker_name = _slug(speaker.get("name") or speaker.get("label") or "")
    return [t for t in dict.fromkeys(terms) if t != speaker_name]


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _title_tokens(title: str) -> set[str]:
    return {w for w in _TOKEN.findall((title or "").lower()) if len(w) > 2}


def classify_source(url: str, title: str, ctx: dict[str, Any], policy: dict[str, Any], terms: Optional[list[str]] = None) -> tuple[str, str]:
    """(label, reason) for one page."""
    host = _host(url)
    video = ctx.get("video") or {}
    if any(host == h or host.endswith("." + h) for h in (policy.get("sources", {}).get("same_episode_hosts") or [])):
        return EPISODE, f"{host} lists or transcribes podcast episodes"
    if video.get("id") and video["id"] in url:
        return EPISODE, "the link is to this video"
    vt, pt = _title_tokens(video.get("title") or ""), _title_tokens(title)
    if len(vt) >= 3 and len(pt) >= 3 and len(vt & pt) / len(vt | pt) >= 0.6:
        return EPISODE, "its title is this video's title"
    host_slug = _slug(host)
    for term in (terms if terms is not None else org_terms(ctx)):
        if term in host_slug:
            return OWN, f"the site of {term}, which the speaker or the show is tied to"
    return INDEPENDENT, ""


def split_sources(sources: list[Source], ctx: dict[str, Any], policy: dict[str, Any]) -> tuple[list[Source], dict[str, int]]:
    """Every source with its label set (nothing is removed), and how many of each kind were seen. The label is a note for the reader."""
    terms = org_terms(ctx)
    kept: list[Source] = []
    counts = {INDEPENDENT: 0, OWN: 0, EPISODE: 0}
    for s in sources:
        label, _ = classify_source(s.url, s.title, ctx, policy, terms)
        counts[label] += 1
        kept.append(s.model_copy(update={"independence": label}))
    return kept, counts
