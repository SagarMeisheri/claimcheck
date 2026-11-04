"""Global guardrail plugin: per-video cost cap and token accounting.

Registered once on every runner, so it applies to every agent and model call
(including each source lookup's isolated session).
"""

from __future__ import annotations

from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from ..context import get_context


class BudgetPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="claimcheck_budget")
        self._models: dict[tuple[str, str], str] = {}

    async def before_model_callback(self, *, callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
        ctx = get_context()
        self._models[(callback_context.invocation_id, callback_context.agent_name)] = llm_request.model or ""
        try:
            ctx.budget.check()
        except Exception:
            ctx.log("budget", "episode_cost_cap", "blocked", f"spent ${ctx.budget.spent_usd:.2f}")
            raise
        return None

    async def after_model_callback(self, *, callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
        # With streaming, every partial piece repeats the running token total. Count only the final,
        # aggregated response, or the same tokens are charged once per piece.
        if llm_response.partial:
            return None
        ctx = get_context()
        usage = llm_response.usage_metadata
        if usage is None:
            return None
        model = self._models.get((callback_context.invocation_id, callback_context.agent_name)) or llm_response.model_version or ""
        price_in, price_out = _price_for(model, ctx.settings.prices)
        # Agentic video bills the frames, audio and transcript it loads as tool-use tokens, so they count as input.
        tin = (usage.prompt_token_count or 0) + (getattr(usage, "tool_use_prompt_token_count", None) or 0)
        tout = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        ctx.budget.add(tin / 1e6 * price_in + tout / 1e6 * price_out, tin, tout)
        return None


def _price_for(model: str, prices: dict) -> tuple[float, float]:
    for name, p in prices.items():
        if name and name in model:
            return p
    # Unknown model: assume the highest known price so the cap errs on the safe side.
    return max(prices.values(), key=lambda p: p[1])


def charge_usage(model: str, usage) -> None:
    """Adds one model response's tokens to the video's budget (same prices as BudgetPlugin)."""
    if usage is None:
        return
    ctx = get_context()
    price_in, price_out = _price_for(model, ctx.settings.prices)
    tin = (usage.prompt_token_count or 0) + (getattr(usage, "tool_use_prompt_token_count", None) or 0)
    tout = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    ctx.budget.add(tin / 1e6 * price_in + tout / 1e6 * price_out, tin, tout)


def metered_gemini(model: str):
    """A Gemini model that checks the cost cap and counts its tokens itself.

    For callers that use a model outside an agent runner, so BudgetPlugin never sees the call: ADK's LlmClassifier
    (the source triage) calls the model directly.
    """
    from google.adk.models.google_llm import Gemini

    class MeteredGemini(Gemini):
        async def generate_content_async(self, llm_request, stream=False):
            get_context().budget.check()
            async for resp in super().generate_content_async(llm_request, stream):
                if not getattr(resp, "partial", False):
                    charge_usage(self.model, resp.usage_metadata)
                yield resp

    return MeteredGemini(model=model)
