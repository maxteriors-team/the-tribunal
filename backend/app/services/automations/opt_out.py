"""The ``no-automation`` contact tag: one customer, all automation off.

Some customers must be handled by a human only — a complaint in flight, a
friend of the owner, a commercial account with its own process. Muting each
automation one at a time is error-prone and cannot be checked at a glance, so
this is a single reserved tag on the *contact*.

What it suppresses:

- every event-driven automation (all of :data:`AUTOMATION_EVENT_TRIGGERS`),
  because :func:`app.services.automations.events.emit_automation_event` is the
  one choke point they all pass through; and
- the automatic quote-sent pipeline card, which is a direct service call and
  never touches the event bus.

What it does **not** suppress: anything an operator does by hand. This mutes
automation, not the human.

The check is one indexed ``EXISTS`` over ``contact_tags`` joined to ``tags``, and
on the event path it runs only *after* the existing "does any automation listen
for this?" short-circuit — so a workspace with no automations pays nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import ContactTag, Tag

__all__ = ["NO_AUTOMATION_TAG", "automation_suppressed", "no_automation_tag_exists"]

# Reserved tag name. Matched case-insensitively so "No-Automation" typed by hand
# behaves the same as the one the UI applies.
NO_AUTOMATION_TAG = "no-automation"


def no_automation_tag_exists(workspace_id: uuid.UUID, contact_id: int) -> Exists:
    """``EXISTS`` predicate: this contact carries the ``no-automation`` tag."""
    return (
        select(ContactTag.id)
        .join(Tag, Tag.id == ContactTag.tag_id)
        .where(
            ContactTag.contact_id == contact_id,
            Tag.workspace_id == workspace_id,
            Tag.name.ilike(NO_AUTOMATION_TAG),
        )
        .exists()
    )


async def automation_suppressed(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int | None,
) -> bool:
    """Whether automation is switched off for ``contact_id``.

    ``None`` contact ids (workspace-level events with no subject) are never
    suppressed — there is no customer to have opted out.
    """
    if contact_id is None:
        return False
    result = await db.execute(select(no_automation_tag_exists(workspace_id, contact_id)))
    return bool(result.scalar())
