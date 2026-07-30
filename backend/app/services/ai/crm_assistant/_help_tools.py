"""Product-help retrieval for the CRM assistant.

"How do I set up an automation?" used to be answered from model priors: the
assistant had no product corpus, while its own prompt forbids inventing facts.
This tool points it at the workspace-level help corpus
(:mod:`app.services.knowledge.product_help`) through the same hybrid retrieval
stack the customer-facing agents use — vector KNN + keyword, fused and
diversified.

Retrieval is scoped to ``workspace_id`` with ``agent_id=None``, so it reads only
workspace-level help documents and can never surface another tenant's data or a
customer-facing agent's business knowledge.
"""

from __future__ import annotations

from typing import Any

from app.services.ai.crm_assistant._pagination import local_listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_errors import missing_argument
from app.services.knowledge.retrieval_service import (
    DEFAULT_TOP_K,
    knowledge_retrieval_service,
)

# Ceiling on passages per call, independent of what the model asks for, so one
# help lookup cannot crowd out the conversation.
MAX_TOP_K = 8

_GROUND_IN_PASSAGES = (
    "Answer only from these passages and say which help topic you used. "
    "Do not add product behaviour that is not written here."
)

_NO_MATCH = (
    "No product help matched that question. Tell the operator you do not have "
    "documented guidance for it instead of guessing, or search again with "
    "different wording."
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
    """Answer product and how-to questions from the workspace help corpus."""

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

        passages = await knowledge_retrieval_service.retrieve_passages(
            self.context.db,
            workspace_id=self.context.workspace_id,
            agent_id=None,
            query=query,
            top_k=_clamp_top_k(args.get("top_k")),
        )

        if not passages:
            return local_listing([], extra={"message": _NO_MATCH})

        return local_listing(
            [
                {
                    "title": passage.title,
                    "content": passage.content,
                    "score": round(passage.score, 4),
                }
                for passage in passages
            ],
            extra={"message": _GROUND_IN_PASSAGES},
        )
