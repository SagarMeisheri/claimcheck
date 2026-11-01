"""HTTP entry point (Cloud Run). The web app or cron calls POST /episodes.

Auth: a shared secret in the X-Pipeline-Secret header. The service never takes
instructions from video content; it only accepts a URL.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import warnings
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .guardrails.input_checks import parse_video_id
from .store import make_store

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.basicConfig(level=logging.INFO)
logging.getLogger("google_adk").setLevel(logging.ERROR)

app = FastAPI(title="ClaimCheck pipeline")
_settings = get_settings()
_store = make_store(_settings)
_running: dict[str, asyncio.Task] = {}  # episode_id -> task, so a run can be cancelled


@app.on_event("startup")
def _fail_orphaned_runs() -> None:
    """Runs live in this process only: after a restart, anything still 'processing' can never finish."""
    try:
        _store.db.table("episodes").update({"status": "failed", "skip_reason": "Interrupted by a service restart. Delete it or submit it again."}
                                           ).eq("status", "processing").execute()
    except Exception:
        logging.getLogger("claimcheck").exception("could not clean up orphaned runs")
    try:
        _store.reset_interrupted_verifications()
    except Exception:
        logging.getLogger("claimcheck").exception("could not clean up interrupted verifications")


class RunRequest(BaseModel):
    url: str
    episode_id: Optional[str] = None
    submitted_by: Optional[str] = None
    wait: bool = False  # true = run inline and return the result (useful for local testing)


def _auth(secret: Optional[str]) -> None:
    expected = _settings.pipeline_secret
    if not expected:
        raise HTTPException(500, "PIPELINE_SHARED_SECRET is not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "bad secret")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "fast_model": _settings.fast_model, "judge_model": _settings.judge_model}


@app.post("/episodes")
async def run(req: RunRequest, background: BackgroundTasks, x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    _auth(x_pipeline_secret)
    if not parse_video_id(req.url):
        raise HTTPException(400, "Not a valid YouTube video URL")
    from .agents.pipeline import run_episode

    if req.wait:
        return await run_episode(req.url, settings=_settings, store=_store, episode_id=req.episode_id,
                                 submitted_by=req.submitted_by)
    task = asyncio.create_task(run_episode(req.url, settings=_settings, store=_store, episode_id=req.episode_id,
                                           submitted_by=req.submitted_by))
    key = req.episode_id or str(id(task))
    _running[key] = task
    task.add_done_callback(lambda t, k=key: _running.pop(k, None) if _running.get(k) is t else None)
    return {"accepted": True, "episode_id": req.episode_id}


@app.post("/episodes/{episode_id}/cancel")
async def cancel(episode_id: str, x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Stops a running check and marks the episode skipped. Works even if the run is no longer in memory."""
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


class VerifyRequest(BaseModel):
    wait: bool = False  # true = verify inline and return the result (local testing)


@app.post("/claims/{claim_id}/verify")
async def verify_one(claim_id: str, req: Optional[VerifyRequest] = None,
                     x_pipeline_secret: Optional[str] = Header(default=None)) -> dict:
    """Verifies one factual claim on request. The web app has already rate-limited the request.

    Answers 409 with a readable reason when the claim can't be verified (not factual, already verified,
    video over its cost cap), so the web app can show it straight away.
    """
    _auth(x_pipeline_secret)
    from .agents.on_demand import precheck, run_claim_verification

    row = await _store.get_claim_for_verification(claim_id)
    ok, reason, code = precheck(row, _settings)
    if not ok:
        raise HTTPException(code, reason)
    if not await _store.start_claim_verification(claim_id):
        raise HTTPException(409, "Already being verified.")
    if req and req.wait:
        return await run_claim_verification(claim_id, settings=_settings, store=_store)
    task = asyncio.create_task(run_claim_verification(claim_id, settings=_settings, store=_store))
    key = f"claim:{claim_id}"
    _running[key] = task
    task.add_done_callback(lambda t, k=key: _running.pop(k, None) if _running.get(k) is t else None)
    return {"accepted": True, "claim_id": claim_id, "status": "verifying"}
