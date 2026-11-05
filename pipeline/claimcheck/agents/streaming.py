"""Streams extracted answers (each saved with its question) to the database while the extractor is still writing them.

The extractor returns one JSON object, {"claims": [...], "summary": "..."}. With streaming on, ADK emits the
reply in pieces; this module pulls each complete statement out of the claims array as soon as its closing
brace arrives, runs the same content-policy code as ClaimFilter, and saves it, so the video page and the home
carousel fill in while the video is still being analysed. The final, complete reply is still the source of
truth: ClaimFilter and the Publisher run as before and only add whatever was missed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from ..context import EpisodeContext, report_progress
from ..schemas import ClaimRecord

log = logging.getLogger("claimcheck")

EXTRACTOR = "extractor"
_PROGRESS_FROM, _PROGRESS_TO = 12, 84  # % range the extraction fills; the claim filter finishes at 92
_FLUSH_EVERY_S = 2.0


class ObjectStream:
    """Incrementally finds the complete objects inside the first array of a streamed JSON document."""

    def __init__(self) -> None:
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._in_array = False
        self._done = False
        self._buf: list[str] = []  # characters of the object being read

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ch in chunk:
            if self._buf:
                self._buf.append(ch)
            if self._in_string:
                if self._escape:
                    self._escape = False
                elif ch == "\\":
                    self._escape = True
                elif ch == '"':
                    self._in_string = False
                continue
            if ch == '"':
                self._in_string = True
            elif ch in "{[":
                if ch == "{" and self._in_array and self._depth == 2:
                    self._buf = ["{"]
                elif ch == "[" and self._depth == 1 and not self._in_array and not self._done:
                    self._in_array = True
                self._depth += 1
            elif ch in "}]":
                self._depth -= 1
                if ch == "}" and self._buf and self._in_array and self._depth == 2:
                    try:
                        obj = json.loads("".join(self._buf))
                    except json.JSONDecodeError:
                        obj = {}  # keep the position so indices match the final list; it fails validation later
                    out.append(obj if isinstance(obj, dict) else {})
                    self._buf = []
                elif ch == "]" and self._in_array and self._depth == 1:
                    self._in_array, self._done = False, True
        return out


class StatementStreamer:
    """Handles the extractor's partial events: saves each statement as it completes."""

    def __init__(self, ec: EpisodeContext, auto: Any = None) -> None:
        self.ec = ec
        self.auto = auto  # AutoSources: starts each saved answer's source lookup
        self._stream = ObjectStream()
        self._index = 0
        self._counts: dict[str, int] = {}
        self._last_start_s = 0
        self._last_flush = 0.0
        self.saved = 0
        self.started = time.monotonic()
        self._first_chunk: Optional[float] = None
        self.broken = False  # a write failed: stop streaming and let the Publisher save everything at the end

    @staticmethod
    def text_of(ev: Any) -> str:
        parts = getattr(getattr(ev, "content", None), "parts", None) or []
        return "".join(p.text or "" for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))

    async def on_event(self, ev: Any) -> None:
        """Call for every partial event authored by the extractor."""
        if self.broken or getattr(ev, "author", "") != EXTRACTOR or not getattr(ev, "partial", False):
            return
        chunk = self.text_of(ev)
        if not chunk:
            return
        if self._first_chunk is None:
            self._first_chunk = time.monotonic() - self.started
            log.info("extractor timing: first text from the model at +%.1fs", self._first_chunk)
        for raw in self._stream.feed(chunk):
            await self._save(raw)
        await self._flush()

    async def _save(self, raw: dict[str, Any]) -> None:
        from .stages import build_record  # imported here: stages imports from this package

        i, self._index = self._index, self._index + 1
        if i >= int(self.ec.policy["claims"]["max_extracted"]):
            return
        rec: Optional[ClaimRecord] = build_record(i, raw, self.ec, log=False)
        if rec is None:
            return
        try:
            await self.ec.store.save_statement(self.ec.episode_id, rec)
        except Exception:
            log.exception("could not stream statement %s; the Publisher will save it", i)
            self.broken = True
            return
        self.saved += 1
        if self.auto is not None:
            self.auto.submit(rec)
        if self.saved == 1:
            log.info("extractor timing: first statement saved at +%.1fs", time.monotonic() - self.started)
        t = rec.claim.statement_type or "other"
        self._counts[t] = self._counts.get(t, 0) + 1
        self._last_start_s = max(self._last_start_s, rec.start_s)

    async def _flush(self, force: bool = False) -> None:
        """Updates the per-type counts and the progress bar, at most every couple of seconds."""
        now = time.monotonic()
        if not self.saved or (not force and now - self._last_flush < _FLUSH_EVERY_S):
            return
        self._last_flush = now
        duration = max(int(self.ec.duration_s or 0), 1)
        frac = min(1.0, self._last_start_s / duration)
        pct = _PROGRESS_FROM + int((_PROGRESS_TO - _PROGRESS_FROM) * frac)
        try:
            await self.ec.store.update_episode(self.ec.episode_id, {"statement_counts": dict(self._counts)})
        except Exception:
            log.exception("could not update statement counts")
        await report_progress(self.ec, f"Reading the video: {self.saved} answers found so far", pct)

    async def finish(self) -> None:
        log.info("extractor timing: %s statements streamed, run finished at +%.1fs", self.saved, time.monotonic() - self.started)
        await self._flush(force=True)
