"""Customer review read tools for the CRM assistant.

Read-only. Replying to a review is a public, customer-facing act, so it stays on
the HTTP surface behind ``comms:send`` where a human composes it.
"""

from __future__ import annotations

from app.services.ai.crm_assistant._pagination import listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument
from app.services.reviews.review_service import ReviewService


class ReviewAssistantTools:
    """Read customer reviews and their sentiment."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = ReviewService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {"list_reviews": self.list_reviews}

    async def list_reviews(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        sentiment = args.get("sentiment")
        if sentiment is not None and not isinstance(sentiment, str):
            return invalid_argument("sentiment must be a string.")

        status = args.get("status")
        if status is not None and not isinstance(status, str):
            return invalid_argument("status must be a string.")

        is_public = args.get("is_public")
        if is_public is not None and not isinstance(is_public, bool):
            return invalid_argument("is_public must be a boolean.")

        page = await self.service.list_reviews(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            status_filter=status,
            is_public=is_public,
            sentiment=sentiment,
        )
        return listing(
            [review.model_dump(mode="json") for review in page.items],
            total=page.total,
        )
