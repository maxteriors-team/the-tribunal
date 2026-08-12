"""Product-help retrieval for the CRM assistant.

The tool ranks the markdown bundled with the backend directly. Product guidance
therefore changes atomically with a deployment and cannot lag behind because a
workspace seed or embedding request was skipped. It also cannot surface tenant
business knowledge: only ``backend/docs/help`` is searched.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.services.ai.crm_assistant._pagination import local_listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_errors import missing_argument
from app.services.knowledge.product_help import ProductHelpError, search_help_documents

logger = structlog.get_logger()
DEFAULT_TOP_K = 5

# Ceiling on passages per call, independent of what the model asks for, so one
# help lookup cannot crowd out the conversation.
MAX_TOP_K = 8

_GROUND_IN_PASSAGES = (
    "Answer only from these passages. Give numbered steps for a how-to, preserve "
    "every UI label and route exactly, and name the source topic. Do not add "
    "product behavior that is not written here."
)

_NO_MATCH = (
    "No bundled product help matched that question. Tell the operator the "
    "workflow is not documented as supported instead of guessing."
)


def _clamp_top_k(raw_value: Any) -> int:
    """Clamp a model-supplied ``top_k`` into ``[1, MAX_TOP_K]``."""

    if raw_value is None:
        return DEFAULT_TOP_K
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return max(1, min(value, MAX_TOP_K))


class HelpAssistantTools:
    """Answer product and how-to questions from bundled help articles."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {"search_help": self.search_help}

    async def search_help(self, args: ToolArguments) -> dict[str, object]:
        query = str(args.get("query") or "").strip()
        if not query:
            return missing_argument(
                "query",
                "Pass the operator's question, e.g. 'how do I set up an automation'.",
            )

        try:
            passages = search_help_documents(
                query,
                top_k=_clamp_top_k(args.get("top_k")),
            )
        except ProductHelpError as exc:
            logger.exception("product_help_source_unavailable", error=str(exc))
            return {
                "success": False,
                "error": "Product help is temporarily unavailable; do not answer from memory.",
            }

        if not passages:
            return local_listing([], extra={"message": _NO_MATCH})

        return local_listing(
            [
                {
                    "title": passage.title,
                    "content": passage.content,
                    "source": passage.source,
                    "score": passage.score,
                }
                for passage in passages
            ],
            extra={"message": _GROUND_IN_PASSAGES},
        )
