"""Per-video run context, carried through asyncio tasks with a ContextVar.

ADK session state must stay JSON-serialisable, so live objects (store, budget, guardrail log) live here instead. Fan-out tasks created with asyncio inherit the context automatically.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import Settings
from .schemas import GuardrailEvent


class BudgetExceeded(RuntimeError):
    pass


def is_budget_error(e: BaseException) -> bool:
    """ADK wraps plugin exceptions in RuntimeError; walk the cause chain."""
    seen = 0
    while e is not None and seen < 10:
        if isinstance(e, BudgetExceeded):
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0

    def add(self, usd: float, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.spent_usd += usd
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceeded(f"video cost ${self.spent_usd:.2f} reached cap ${self.cap_usd:.2f}")


@dataclass
class EpisodeContext:
    episode_id: str
    video_id: str
    settings: Settings
    policy: dict[str, Any]
    store: Any
    budget: Budget
    events: list[GuardrailEvent] = field(default_factory=list)
    # Returns the plugin list for each ADK runner (budget, Model Armor, ...)
    plugins_factory: Callable[[], list] = field(default=lambda: [])
    duration_s: int = 0  # video length, used to turn a statement's timestamp into progress

    def log(self, stage: str, rule: str, action: str, detail: str = "", claim_index: Optional[int] = None) -> None:
        self.events.append(GuardrailEvent(stage=stage, rule=rule, action=action, detail=detail[:500], claim_index=claim_index))


async def report_progress(ec: "EpisodeContext", label: str, pct: int) -> None:
    """Writes the current step to the episode row so the web app can show a progress bar. Never raises."""
    try:
        await ec.store.update_episode(ec.episode_id, {"progress": {"label": label, "pct": max(0, min(100, int(pct)))}})
    except Exception:
        pass


_current: contextvars.ContextVar[Optional[EpisodeContext]] = contextvars.ContextVar("claimcheck_episode", default=None)


def set_context(ctx: EpisodeContext) -> contextvars.Token:
    return _current.set(ctx)


def get_context() -> EpisodeContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("No EpisodeContext set; run inside run_episode()")
    return ctx
