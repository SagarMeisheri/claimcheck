"""Creator and speaker profiles: matching them to a video, and turning them into context for the later steps.

Creators come from the `creators` table (top YouTube podcasts, matched by YouTube channel ID). Speakers come from the
`speakers` table, built from a web search the first time a named person appears (agents/speakers.py).

How the profiles are used:
  extraction   the show and its hosts, so the host can be named
  tags         statement + question + what was being discussed + speaker and show profiles + pages -> the answer's tags
  searches     who said it and where steer the first search; known positions and criticisms aim the second one
  summary      the context line only helps pick out relevant excerpts
Biases and criticisms are never shown to viewers (the database only exposes the neutral parts).
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Labels the extractor uses when no name was said or shown: these never get a profile.
_ROLE = re.compile(
    r"^(the\s+)?(co-?host|host|guest|panel+ist|speaker|narrator|moderator|interviewer|interviewee|anchor|caller|"
    r"audience( member)?|reporter|presenter|voice ?over|unknown|unidentified|participant|man|woman|person|expert|"
    r"commentator|announcer|off-?screen)\b", re.I)
_TITLES = re.compile(r"\b(dr|mr|mrs|ms|prof|professor|sir|shri|smt|sri|hon)\.?\s+", re.I)
_QUOTED = re.compile(r"[\"“”']([^\"“”']+)[\"“”']")  # Dan "Big Cat" Katz -> nickname
_PARENS = re.compile(r"\(([^)]*)\)")              # Adam Grandmaison (Adam22) -> alias


def is_role_label(label: str) -> bool:
    """True for 'Host', 'Guest 1', 'Panellist 2', 'Speaker (off-screen)'; False for a person's name."""
    t = (label or "").strip()
    return not t or bool(_ROLE.match(t)) or not re.search(r"[A-Za-zऀ-ॿ]{2,}", t)


def name_key(name: str) -> str:
    """Lower case, titles and punctuation dropped: 'Dr. Andrew Huberman' -> 'andrew huberman'."""
    t = _TITLES.sub("", (name or "").strip())
    t = re.sub(r"[^\w\s]+", " ", t.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def host_groups(creator: Optional[dict[str, Any]]) -> list[list[str]]:
    """Each host's names, nicknames and aliases first, full name last, from profile.hosts:
    'Dan "Big Cat" Katz & Eric Sollenberger' -> [["Big Cat", "Dan Katz"], ["Eric Sollenberger"]]."""
    hosts = ((creator or {}).get("profile") or {}).get("hosts") or ""
    groups: list[list[str]] = []
    for part in re.split(r",|&|\band\b|/", hosts):
        p = part.strip()
        if not p or re.search(r"\b(cast|crew|ensemble)\b", p, re.I):
            continue
        names = [m.strip() for m in _QUOTED.findall(p) + _PARENS.findall(p)]
        plain = " ".join(_PARENS.sub("", _QUOTED.sub("", p)).split())
        if plain:
            names.append(plain)
        names = [n for n in dict.fromkeys(names) if len(name_key(n)) > 2]
        if names:
            groups.append(names)
    return groups


def host_names(creator: Optional[dict[str, Any]]) -> list[str]:
    """Every name the creator's hosts go by."""
    return list(dict.fromkeys(n for g in host_groups(creator) for n in g))


def match_host(label: str, creator: Optional[dict[str, Any]]) -> Optional[str]:
    """The host name a speaker label refers to ('Joe Rogan', 'Rogan', 'Big Cat'), or None."""
    key = name_key(label)
    if not key:
        return None
    words = set(key.split())
    for host in host_names(creator):
        hk = name_key(host)
        if key == hk or (len(words) >= 1 and words <= set(hk.split()) and len(key) >= 4):
            return host
    return None


def usable_creator(creator: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The creator row, or None for a channel a web search couldn't describe (saved so it isn't searched again)."""
    if creator and (creator.get("profile") or {}).get("identified") is False:
        return None
    return creator


# The v2 profile keys the later steps get (profiles are numbered into items for the classifiers by numbered_profile).
V2_KEYS = ("narrative", "expertise", "credentials", "businesses", "financial_interests", "political", "praise", "critiques",
           "controversy_reports", "bias_claims", "sponsors", "ownership")


def creator_context(creator: Optional[dict[str, Any]]) -> dict[str, Any]:
    """What the later steps get about the show. Empty if the channel isn't a known creator."""
    if not creator:
        return {}
    p = creator.get("profile") or {}
    # Curated shows already carry notes on leaning (biases) and on how the show is received (criticism, controversies); a show
    # found by a live search has leaning and public_opinion. Either way the later steps get the same two fields.
    opinion = p.get("public_opinion") or " ".join(x for x in (p.get("criticism"), p.get("controversies")) if x)
    return {k: v for k, v in {
        "podcast": creator.get("podcast"), "summary": creator.get("summary"), "hosts": p.get("hosts"),
        "country": creator.get("country"), "biases": p.get("biases"), "criticism": p.get("criticism"),
        "controversies": p.get("controversies"), "leaning": p.get("leaning") or p.get("biases"),
        "leaning_basis": p.get("leaning_basis") or ("curated" if p.get("biases") else ""), "public_opinion": opinion,
        **{k: p.get(k) for k in V2_KEYS},
    }.items() if v}


def speaker_context(speaker: Optional[dict[str, Any]], label: str = "") -> dict[str, Any]:
    """What the later steps get about the person who said a statement."""
    if not speaker or speaker.get("status") != "ready":
        return {"label": label} if label else {}
    p = speaker.get("profile") or {}
    return {k: v for k, v in {
        "name": speaker.get("name") or label, "summary": speaker.get("summary"), "role": p.get("role"),
        "affiliations": p.get("affiliations"), "known_positions": p.get("known_positions"), "criticisms": p.get("criticisms"),
        "leaning": p.get("leaning") or p.get("known_positions"),
        "leaning_basis": p.get("leaning_basis") or ("described" if p.get("known_positions") else ""),
        "public_opinion": p.get("public_opinion") or p.get("criticisms"),
        **{k: p.get(k) for k in V2_KEYS},
    }.items() if v}


def extraction_context(creator: Optional[dict[str, Any]]) -> str:
    """One line for the extractor: the show and its hosts (so the host can be named). Neutral parts only."""
    if not creator:
        return ""
    hosts = ((creator.get("profile") or {}).get("hosts") or "").strip()
    return f"Show: {creator.get('podcast')}" + (f". Hosts: {hosts}." if hosts else ".")


# ISO 3166-1 alpha-2 codes for Parallel's geo-targeting, from creators.country.
_COUNTRY_CODES = {
    "us": "us", "india": "in", "uk": "gb", "brazil": "br", "spain": "es", "mexico": "mx", "canada": "ca",
    "germany": "de", "france": "fr", "saudi arabia": "sa", "australia": "au", "dominican rep.": "do", "japan": "jp",
}


def search_location(creator: Optional[dict[str, Any]], default: str = "in") -> str:
    """Where to geo-target searches: the creator's country ('UK / US' -> gb, 'Japan (Intl)' -> jp), else the default."""
    country = ((creator or {}).get("country") or "").lower()
    first = re.split(r"\s*/\s*|\s*\(", country)[0].strip()
    return _COUNTRY_CODES.get(first, default)


def section_for(start_s: int, sections: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The section a moment falls in: the last one starting at or before it."""
    hit = None
    for s in sorted(sections or [], key=lambda x: x.get("start_s", 0)):
        if s.get("start_s", 0) <= start_s:
            hit = s
    return hit


SPEAKER_KEYS = ("name", "role", "affiliations", "leaning", "leaning_basis", "public_opinion")
SHOW_KEYS = ("podcast", "hosts", "country", "leaning", "leaning_basis", "public_opinion")


def profile_text(p: dict[str, Any], keys: tuple[str, ...]) -> str:
    """A profile as plain 'key: value' lines, for the classifiers that read it."""
    return "\n".join(f"{k}: {p[k]}" for k in keys if p.get(k))


# --- Comprehensive (version 2) profiles ------------------------------------------------------------------
PROFILE_VERSION = 2
PROFILE_MAX_AGE_DAYS = 90
# Where each cited list of a v2 profile is stored inside `profile`. The names avoid the keys the public_profile columns strip
# (speakers: known_positions, criticisms; creators: biases, controversies, criticism), because these are attributed and shown.
CITED_LISTS = {"businesses": "businesses", "financial_interests": "financial_interests", "praise": "praise", "criticism": "critiques",
               "controversies": "controversy_reports", "bias_claims": "bias_claims", "sponsors": "sponsors", "ownership": "ownership"}


def needs_rebuild(row: Optional[dict[str, Any]], now: Optional[Any] = None) -> bool:
    """A ready profile from before version 2, or one older than PROFILE_MAX_AGE_DAYS, is rebuilt when a new video meets it."""
    import datetime as dt

    if not row:
        return True
    if int(row.get("profile_version") or 1) < PROFILE_VERSION:
        return True
    at = row.get("profiled_at")
    if not at:
        return False
    try:
        when = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return ((now or dt.datetime.now(dt.timezone.utc)) - when).days > PROFILE_MAX_AGE_DAYS


def _clip(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def cite(items: list[Any], pages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """A profile's cited items with the page each came from ({..., "url", "site"}); an item naming no real page is dropped."""
    by_n = {pg["n"]: pg for pg in pages}
    out: list[dict[str, Any]] = []
    for it in items or []:
        d = it.model_dump() if hasattr(it, "model_dump") else dict(it)
        pg = by_n.get(d.pop("page", None))
        if not pg:
            continue
        d = {k: (_clip(v, 300) if isinstance(v, str) else v) for k, v in d.items()}
        if not any(isinstance(v, str) and v for v in d.values()):
            continue
        out.append({**d, "url": pg.get("url", ""), "site": pg.get("site", "")})
        if len(out) >= limit:
            break
    return out


INTERNAL_INCENTIVES = frozenset({"access_preserving", "audience_captured"})  # steer the skepticism rules; never shown


def split_incentives(cited: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The profile writer's cited incentive tags as ({tag: {"reason", "url", "site"}} visible, internal). The first item per tag wins."""
    visible: dict[str, Any] = {}
    internal: dict[str, Any] = {}
    for it in cited:
        tag = it.get("tag")
        if not tag or not it.get("reason"):
            continue
        target = internal if tag in INTERNAL_INCENTIVES else visible
        target.setdefault(tag, {"reason": it["reason"], "url": it.get("url", ""), "site": it.get("site", "")})
    return visible, internal


def v2_fields(out: Any, pages: list[dict[str, Any]]) -> dict[str, Any]:
    """The cited, comprehensive part of a profile (shared by speakers and creators), ready to merge into `profile`."""
    fields: dict[str, Any] = {"narrative": _clip(getattr(out, "narrative", ""), 1800)}
    for src, key in CITED_LISTS.items():
        if hasattr(out, src):
            fields[key] = cite(getattr(out, src), pages)
    if hasattr(out, "expertise"):
        fields["expertise"] = [_clip(x, 80) for x in out.expertise[:8] if str(x).strip()]
        fields["credentials"] = _clip(out.credentials, 400)
    pol = getattr(out, "political", None)
    if pol is not None:
        page = {pg["n"]: pg for pg in pages}.get(pol.page)
        leaning = _clip(pol.leaning, 300) if pol.basis != "none" else ""
        fields["political"] = {k: v for k, v in {
            "leaning": leaning, "basis": pol.basis if leaning or pol.posts else "none",
            "posts": [_clip(x, 160) for x in pol.posts[:6] if str(x).strip()],
            "url": (page or {}).get("url", ""), "site": (page or {}).get("site", "")}.items() if v}
        # The fields older code reads (profile_text, the web's leaning line).
        fields["leaning"] = leaning or "; ".join(fields["political"].get("posts", []))
        fields["leaning_basis"] = ("declared" if pol.posts else pol.basis) if fields["leaning"] else ""
    if hasattr(out, "incentives"):
        visible, internal = split_incentives(cite(getattr(out, "incentives"), pages, limit=12))
        fields["incentives"], fields["incentives_internal"] = visible, internal
    praise, crit = fields.get("praise") or [], fields.get("critiques") or []
    opinion = [f"Praised by {x['by']}: {x['text']}" if x.get("by") else f"Praised: {x['text']}" for x in praise[:3]]
    opinion += [f"Criticised by {x['by']}: {x['text']}" if x.get("by") else f"Criticised: {x['text']}" for x in crit[:3]]
    fields["public_opinion"] = _clip(" ".join(opinion), 900)
    return {k: v for k, v in fields.items() if v}


def numbered_profile(p: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """A profile as numbered items for the incentive classifiers: each item is one fact, with the page it came from, so a
    classifier can name the item its tag rests on (agents/profile_tags.py)."""
    items: list[dict[str, Any]] = []

    def add(kind: str, text: str, url: str = "", site: str = "") -> None:
        text = _clip(text, 400)
        if text:
            items.append({"n": len(items) + 1, "kind": kind, "text": text, "url": url, "site": site})

    for k in keys:
        v = p.get(k)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v if isinstance(x, str))
        if isinstance(v, str) and v:
            add(k, v)
    for b in p.get("businesses") or []:
        add("business", f"{b.get('relation', '')} of {b.get('name', '')}" + (f" ({b['sector']})" if b.get("sector") else "")
            + ("" if b.get("current", True) else " (former)"), b.get("url", ""), b.get("site", ""))
    for f in p.get("financial_interests") or []:
        add("financial_interest", f.get("what", ""), f.get("url", ""), f.get("site", ""))
    for sp in p.get("sponsors") or []:
        add("sponsor", f"Sponsor: {sp.get('name', '')}" + (f" ({sp['category']})" if sp.get("category") else ""), sp.get("url", ""), sp.get("site", ""))
    for o in p.get("ownership") or []:
        add("ownership", o.get("text", ""), o.get("url", ""), o.get("site", ""))
    pol = p.get("political") or {}
    if pol.get("leaning") or pol.get("posts"):
        add("political", "; ".join(x for x in [pol.get("leaning", "")] + list(pol.get("posts") or []) if x), pol.get("url", ""), pol.get("site", ""))
    for x in p.get("critiques") or []:
        add("criticism", (f"{x['by']}: " if x.get("by") else "") + x.get("text", ""), x.get("url", ""), x.get("site", ""))
    for x in p.get("controversy_reports") or []:
        add("controversy", x.get("what", "") + (f" ({x['when']})" if x.get("when") else ""), x.get("url", ""), x.get("site", ""))
    for x in p.get("bias_claims") or []:
        add("bias_claim", (f"{x['by']}: " if x.get("by") else "") + x.get("claim", ""), x.get("url", ""), x.get("site", ""))
    return items
