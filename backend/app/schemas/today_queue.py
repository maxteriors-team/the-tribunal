"""Schemas for the Today Queue — the ordered morning mission list."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TodayQueueKind = Literal[
    "approvals",
    "hot_nudges",
    "prospect_batch",
    "draft_campaign",
    "setup_gap",
]


class TodayQueueItem(BaseModel):
    """One ordered mission item on the Today queue."""

    id: str
    kind: TodayQueueKind
    priority: int
    title: str
    body: str
    count: int
    cta_label: str
    href: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TodayQueueResponse(BaseModel):
    """Ordered mission queue for a workspace."""

    items: list[TodayQueueItem]
    generated_at: datetime
