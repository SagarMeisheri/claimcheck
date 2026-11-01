"""Before-tool guardrail for the evidence agent.

The model only chooses a query and a scope ("tier1" or "open"). Domains, limits
and blocklists are decided here and in the tool itself, never by the model.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ..context import get_context

ALLOWED_SCOPES = {"tier1", "open"}
MAX_QUERY_CHARS = 300


def before_evidence_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    ctx = get_context()
    claim_index = tool_context.state.get("claim_index")
    used = int(tool_context.state.get("searches_used", 0))
    if used >= ctx.settings.max_searches_per_claim:
        ctx.log("evidence", "max_searches_per_claim", "blocked", f"{used} searches used", claim_index)
        return {"error": "Search limit reached for this claim. Judge with the evidence already gathered."}
    scope = args.get("scope", "tier1")
    if scope not in ALLOWED_SCOPES:
        ctx.log("evidence", "scope_not_allowed", "blocked", str(scope), claim_index)
        return {"error": "scope must be 'tier1' or 'open'."}
    query = str(args.get("query", ""))
    if not query.strip() or len(query) > MAX_QUERY_CHARS:
        ctx.log("evidence", "query_invalid", "blocked", query[:80], claim_index)
        return {"error": f"query must be 1-{MAX_QUERY_CHARS} characters."}
    tool_context.state["searches_used"] = used + 1
    return None
