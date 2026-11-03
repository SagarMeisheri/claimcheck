"""HTTP entry point (Cloud Run). The web app calls these endpoints with a shared secret.

Auth: a shared secret in the X-Pipeline-Secret header. The service never takes instructions from video content;
it only accepts a URL or an id.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import warnings
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .guardrails.input_checks import parse_video_id
from .store import make_store

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.basicConfig(level=logging.INFO)
logging.getLogger("google_adk").setLevel(logging.ERROR)
log = logging.getLogger("claimcheck")

_settings = get_settings()
_store = make_store(_settings)
_running: dict[str, asyncio.Task] = {}  # key -> task, so a run can be cancelled and not started twice


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Runs live in this process only: after a restart, anything still running can never finish.
    try:
        _store.reset_interrupted()
    except Exception:
        log.exception("could not clean up interrupted runs")
    yield


app = FastAPI(title="ClaimCheck pipeline", lifespan=lifespan)


def _auth(secret: Optional[str]) -> None:
    expected = _settings.pipeline_secret
    if not expected:
        raise HTTPException(500, "PIPELINE_SHARED_SECRET is not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "bad secret")


def _start(key: str, coro) -> None:
    task = asyncio.create_task(coro)
    _running[key] = task
    task.add_done_callback(lambda t, k=key: _running.pop(k, None) if _running.get(k) is t else None)


def _busy(key: str) -> bool:
    task = _running.get(key)
    return bool(task and not task.done())


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "fast_model": _settings.fast_model, "lite_model": _settings.lite_model}


class RunRequest(BaseModel):
    url: str
    episode_id: Optional[str] = None
    submitted_by: Optional[str] = None
    wait: bool = False  # true = run inline and return the result (useful for local testing)


@app.post("/episodes")
async def run(req: RunRequest, x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    _auth(x_pipeline_secret)
    if not parse_video_id(req.url):
        raise HTTPException(400, "Not a valid YouTube video URL")
    from .agents.pipeline import run_episode

    if req.wait:
        return await run_episode(req.url, settings=_settings, store=_store, episode_id=req.episode_id, submitted_by=req.submitted_by)
    key = req.episode_id or req.url
    if _busy(key):
        return {"accepted": True, "episode_id": req.episode_id}
    _start(key, run_episode(req.url, settings=_settings, store=_store, episode_id=req.episode_id, submitted_by=req.submitted_by))
    return {"accepted": True, "episode_id": req.episode_id}


@app.post("/episodes/{episode_id}/cancel")
async def cancel(episode_id: str, x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Stops a running analysis and marks the episode skipped. Works even if the run is no longer in memory."""
    _auth(x_pipeline_secret)
    task = _running.get(episode_id)
    was_running = bool(task and not task.done())
    if was_running:
        task.cancel()
        try:
            await task
        except BaseException:  # CancelledError or whatever the run raised while stopping
            pass
    _store.db.table("episodes").update({"status": "skipped", "skip_reason": "Cancelled."}
                                       ).eq("id", episode_id).in_("status", ["queued", "processing"]).execute()
    return {"cancelled": True, "was_running": was_running}


@app.post("/episodes/{episode_id}/sources-all")
async def sources_all(episode_id: str, wait: bool = False, x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Looks up sources for every claim of a video that has finished its first pass."""
    _auth(x_pipeline_secret)
    from .agents.video_sources import run_video_sources

    key = f"sources-all:{episode_id}"
    if _busy(key):
        raise HTTPException(409, "Already checking sources for this video.")
    if not await _store.get_episode(episode_id):
        raise HTTPException(404, "Video not found.")
    if wait:
        return await run_video_sources(episode_id, settings=_settings, store=_store)
    _start(key, run_video_sources(episode_id, settings=_settings, store=_store))
    return {"accepted": True, "episode_id": episode_id}


class SourcesRequest(BaseModel):
    wait: bool = False  # true = run inline and return the result (local testing)


@app.post("/claims/{claim_id}/sources")
async def sources_one(claim_id: str, req: Optional[SourcesRequest] = None,
                      x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Looks up sources for one factual claim. The web app has already rate-limited the request.

    Answers 409 with a readable reason when it can't run (not a claim, already done, video over its cost cap),
    so the web app can show it straight away.
    """
    _auth(x_pipeline_secret)
    from .agents.sources_on_demand import precheck, run_claim_sources

    row = await _store.get_claim_for_sources(claim_id)
    ok, reason, code = precheck(row, _settings)
    if not ok:
        raise HTTPException(code, reason)
    if not await _store.start_claim_sources(claim_id):
        raise HTTPException(409, "Already searching.")
    if req and req.wait:
        return await run_claim_sources(claim_id, settings=_settings, store=_store)
    _start(f"claim:{claim_id}", run_claim_sources(claim_id, settings=_settings, store=_store))
    return {"accepted": True, "claim_id": claim_id, "status": "searching"}


@app.post("/maintenance/youtube-refresh")
async def youtube_refresh(x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Called daily by the web app's maintenance cron."""
    _auth(x_pipeline_secret)
    from .maintenance import refresh_youtube_data

    return await refresh_youtube_data(_store, _settings)
