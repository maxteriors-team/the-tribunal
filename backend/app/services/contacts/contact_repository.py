"""Contact repository - data access layer for contact operations."""

import uuid
from typing import Any

import structlog
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.encryption import hash_phone, hash_value
from app.db.pagination import paginate_rows
from app.db.scope import get_workspace_owned
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.tag import ContactTag
from app.services.contacts.contact_filters import apply_contact_filters, apply_contact_list_filters
from app.services.tags import TagService
from app.utils.phone import normalize_phone_safe

logger = structlog.get_logger()


async def list_contacts_paginated(
    workspace_id: uuid.UUID,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status_filter: str | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    # Advanced filters
    tags: list[uuid.UUID] | None = None,
    tags_match: str = "any",
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source: str | None = None,
    company_name: str | None = None,
    created_after: Any | None = None,
    created_before: Any | None = None,
    enrichment_status: str | None = None,
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> tuple[Any, int]:
    """Build and execute contact list query with filters and pagination.

    Args:
        workspace_id: The workspace UUID
        db: Database session
        page: Page number (1-indexed)
        page_size: Number of items per page
        status_filter: Optional status filter
        search: Optional search term
        sort_by: Optional sort field (created_at, last_conversation, unread_first)

    Returns:
        Tuple of (rows, total_count) where rows contain contact data with conversation stats
    """
    log = logger.bind(workspace_id=str(workspace_id), page=page, page_size=page_size)

    # Subquery to get conversation data per contact (aggregated across all conversations)
    conv_subquery = (
        select(
            Conversation.contact_id,
            func.sum(Conversation.unread_count).label("total_unread"),
            func.max(Conversation.last_message_at).label("max_message_at"),
            # Get the direction of the most recent message
            func.max(Conversation.last_message_direction).label("last_direction"),
        )
        .where(Conversation.workspace_id == workspace_id)
        .where(Conversation.contact_id.isnot(None))
        .group_by(Conversation.contact_id)
        .subquery()
    )

    # Build query with conversation data
    query = (
        select(
            Contact,
            func.coalesce(conv_subquery.c.total_unread, 0).label("unread_count"),
            conv_subquery.c.max_message_at.label("last_message_at"),
            conv_subquery.c.last_direction.label("last_message_direction"),
        )
        .outerjoin(conv_subquery, Contact.id == conv_subquery.c.contact_id)
        .where(Contact.workspace_id == workspace_id)
        .options(selectinload(Contact.contact_tags).selectinload(ContactTag.tag))
    )

    query = apply_contact_list_filters(
        query,
        status_filter=status_filter,
        search=search,
    )

    # Apply advanced filters
    query = apply_contact_filters(
        query,
        workspace_id,
        tags=tags,
        tags_match=tags_match,
        lead_score_min=lead_score_min,
        lead_score_max=lead_score_max,
        is_qualified=is_qualified,
        source=source,
        company_name=company_name,
        created_after=created_after,
        created_before=created_before,
        enrichment_status=enrichment_status,
        filter_rules=filter_rules,
        filter_logic=filter_logic,
    )

    # Apply sorting (always include Contact.id as final sort key for stable pagination)
    if sort_by == "unread_first":
        # Unread contacts first (by unread count desc), then by last message time
        query = query.order_by(
            conv_subquery.c.total_unread.desc().nullslast(),
            conv_subquery.c.max_message_at.desc().nullslast(),
            Contact.id.desc(),
        )
    elif sort_by == "last_conversation":
        # Sort by most recent conversation first, contacts with no conversation go last
        query = query.order_by(
            conv_subquery.c.max_message_at.desc().nullslast(),
            Contact.id.desc(),
        )
    else:
        query = query.order_by(Contact.created_at.desc(), Contact.id.desc())

    paginated = await paginate_rows(db, query, page=page, page_size=page_size)
    rows = paginated.items

    log.info("contacts_listed", total=paginated.total, returned=len(rows))

    return rows, paginated.total


async def get_contact_by_id(
    contact_id: int,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> Contact | None:
    """Get a specific contact by ID.

    Args:
        contact_id: The contact ID
        workspace_id: The workspace UUID
        db: Database session

    Returns:
        Contact object or None if not found
    """
    return await get_workspace_owned(
        db,
        Contact,
        contact_id,
        workspace_id,
        options=[selectinload(Contact.contact_tags).selectinload(ContactTag.tag)],
    )


async def create_contact(
    workspace_id: uuid.UUID,
    db: AsyncSession,
    first_name: str,
    last_name: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    company_name: str | None = None,
    status: str = "new",
    tags: list[str] | None = None,
    notes: str | None = None,
    source: str | None = None,
    important_dates: dict[str, Any] | None = None,
    attribution_fields: dict[str, Any] | None = None,
) -> Contact:
    """Create a new contact.

    Args:
        workspace_id: The workspace UUID
        db: Database session
        first_name: First name (required)
        last_name: Last name
        email: Email address
        phone_number: Phone number
        company_name: Company name
        status: Contact status
        tags: List of tags
        notes: Additional notes
        source: Source of the contact
        attribution_fields: Structured lead-source attribution values

    Returns:
        Created contact
    """
    contact = Contact(
        workspace_id=workspace_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        email_hash=hash_value(email) if email else None,
        phone_number=phone_number,
        phone_hash=hash_phone(phone_number) if phone_number else None,
        company_name=company_name,
        status=status,
        notes=notes,
        source=source,
        important_dates=important_dates,
        **(attribution_fields or {}),
    )
    db.add(contact)
    await db.flush()
    await TagService(db).add_tags_to_contact(
        workspace_id=workspace_id,
        contact_id=contact.id,
        names=tags,
    )
    await db.commit()
    return await get_contact_by_id(contact.id, workspace_id, db) or contact


async def update_contact(
    contact: Contact,
    db: AsyncSession,
    update_data: dict[str, Any],
) -> Contact:
    """Update a contact with new data.

    Args:
        contact: Contact object to update
        db: Database session
        update_data: Dictionary of fields to update

    Returns:
        Updated contact
    """
    tag_names = update_data.pop("tags", None)

    for field, value in update_data.items():
        setattr(contact, field, value)
        if field == "email":
            contact.email_hash = hash_value(value) if value else None
        elif field == "phone_number" and value:
            contact.phone_hash = hash_phone(value)

    if tag_names is not None:
        await TagService(db).replace_contact_tags_by_name(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            names=tag_names,
        )

    await db.commit()
    return await get_contact_by_id(contact.id, contact.workspace_id, db) or contact


async def delete_contact(
    contact: Contact,
    db: AsyncSession,
) -> None:
    """Delete a contact.

    Args:
        contact: Contact object to delete
        db: Database session
    """
    await db.delete(contact)
    await db.commit()


async def bulk_delete_contacts(
    contact_ids: list[int],
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[int, list[str]]:
    """Delete multiple contacts at once.

    Args:
        contact_ids: List of contact IDs to delete
        workspace_id: The workspace UUID
        db: Database session

    Returns:
        Tuple of (deleted_count, list_of_errors)
    """
    errors: list[str] = []

    # Single query to fetch all contacts at once
    result = await db.execute(
        select(Contact).where(
            Contact.id.in_(contact_ids),
            Contact.workspace_id == workspace_id,
        )
    )
    contacts = result.scalars().all()

    # Track found contact IDs
    found_ids = {contact.id for contact in contacts}

    # Track missing contact IDs
    for contact_id in contact_ids:
        if contact_id not in found_ids:
            errors.append(f"Contact {contact_id} not found")

    # Bulk delete all found contacts in one statement
    # Database CASCADE will handle related deletions
    if found_ids:
        await db.execute(
            delete(Contact).where(
                Contact.id.in_(found_ids),
                Contact.workspace_id == workspace_id,
            )
        )

    await db.commit()

    deleted = len(contacts)

    return deleted, errors


async def bulk_update_status(
    contact_ids: list[int],
    workspace_id: uuid.UUID,
    new_status: str,
    db: AsyncSession,
) -> tuple[int, list[str]]:
    """Update the status of multiple contacts at once.

    Args:
        contact_ids: List of contact IDs to update
        workspace_id: The workspace UUID
        new_status: The new status to set
        db: Database session

    Returns:
        Tuple of (updated_count, list_of_errors)
    """
    errors: list[str] = []

    # Find all contacts that exist in this workspace
    result = await db.execute(
        select(Contact.id).where(
            Contact.id.in_(contact_ids),
            Contact.workspace_id == workspace_id,
        )
    )
    found_ids = {row[0] for row in result.all()}

    # Track missing contact IDs
    for contact_id in contact_ids:
        if contact_id not in found_ids:
            errors.append(f"Contact {contact_id} not found")

    # Bulk update all found contacts in one statement
    if found_ids:
        await db.execute(
            update(Contact)
            .where(
                Contact.id.in_(found_ids),
                Contact.workspace_id == workspace_id,
            )
            .values(status=new_status)
        )

    await db.commit()

    return len(found_ids), errors


async def get_contact_timeline(
    contact_id: int,
    workspace_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get the conversation timeline for a contact.

    Returns a unified timeline of SMS messages, calls, appointments, etc.

    Args:
        contact_id: The contact ID
        workspace_id: The workspace UUID
        db: Database session
        limit: Maximum items to return

    Returns:
        List of timeline items (dicts)
    """
    log = logger.bind(contact_id=contact_id, workspace_id=str(workspace_id))

    # Get contact
    contact = await get_contact_by_id(contact_id, workspace_id, db)
    if not contact:
        return []

    timeline_items: list[dict[str, Any]] = []

    # Normalize contact phone for matching
    normalized_contact_phone = (
        normalize_phone_safe(contact.phone_number) if contact.phone_number else None
    )

    # Get conversations for this contact (by contact_id or phone number)
    conv_query = select(Conversation).where(
        Conversation.workspace_id == workspace_id,
    )

    if contact.phone_number and normalized_contact_phone:
        conv_query = conv_query.where(
            or_(
                Conversation.contact_id == contact_id,
                Conversation.contact_phone == contact.phone_number,
                Conversation.contact_phone == normalized_contact_phone,
            )
        )
    else:
        conv_query = conv_query.where(Conversation.contact_id == contact_id)

    conv_result = await db.execute(conv_query)
    conversations = conv_result.scalars().all()

    # Get all conversation IDs
    conversation_ids = [conv.id for conv in conversations]

    if conversation_ids:
        # Fetch only the most recent `limit` messages across all of this
        # contact's conversations. The timeline is ultimately sorted by
        # timestamp and clipped to `limit` items, so materializing more than
        # that in Python wastes a full table scan on every poll (this endpoint
        # is polled every 3s by the contact viewer).
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .options(selectinload(Message.call_outcome))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        recent_messages = msg_result.scalars().all()

        for msg in recent_messages:
            # Determine type based on channel
            if msg.channel == "imessage":
                item_type = "sms"
            elif msg.channel == "voice":
                item_type = "call"
            else:
                item_type = msg.channel

            signals: dict[str, Any] | None = None
            if msg.call_outcome is not None and msg.call_outcome.signals:
                signals = dict(msg.call_outcome.signals)

            timeline_items.append(
                {
                    "id": msg.id,
                    "type": item_type,
                    "timestamp": msg.created_at,
                    "direction": msg.direction,
                    "is_ai": msg.is_ai,
                    "content": msg.body,
                    "duration_seconds": msg.duration_seconds,
                    "recording_url": msg.recording_url,
                    "transcript": msg.transcript,
                    "status": msg.status,
                    "booking_outcome": msg.booking_outcome,
                    "signals": signals,
                    "original_id": msg.id,
                    "original_type": f"{msg.channel}_message",
                }
            )

    # Sort by timestamp (oldest first) for client display
    timeline_items.sort(key=lambda x: x["timestamp"])

    log.info("timeline_retrieved", item_count=len(timeline_items))

    return timeline_items


async def list_contact_ids(
    workspace_id: uuid.UUID,
    db: AsyncSession,
    status_filter: str | None = None,
    search: str | None = None,
    # Advanced filters
    tags: list[uuid.UUID] | None = None,
    tags_match: str = "any",
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source: str | None = None,
    company_name: str | None = None,
    created_after: Any | None = None,
    created_before: Any | None = None,
    enrichment_status: str | None = None,
    filter_rules: list[dict[str, Any]] | None = None,
    filter_logic: str = "and",
) -> tuple[list[int], int]:
    """Get all contact IDs matching filters (for Select All functionality)."""
    query = select(Contact.id).where(Contact.workspace_id == workspace_id)

    query = apply_contact_list_filters(
        query,
        status_filter=status_filter,
        search=search,
    )

    # Apply advanced filters
    query = apply_contact_filters(
        query,
        workspace_id,
        tags=tags,
        tags_match=tags_match,
        lead_score_min=lead_score_min,
        lead_score_max=lead_score_max,
        is_qualified=is_qualified,
        source=source,
        company_name=company_name,
        created_after=created_after,
        created_before=created_before,
        enrichment_status=enrichment_status,
        filter_rules=filter_rules,
        filter_logic=filter_logic,
    )

    query = query.order_by(Contact.created_at.desc(), Contact.id.desc())

    result = await db.execute(query)
    ids = [row[0] for row in result.all()]

    return ids, len(ids)


async def find_or_create_conversation(
    contact_id: int,
    workspace_id: uuid.UUID,
    contact_phone: str,
    workspace_phone: str,
    db: AsyncSession,
) -> Conversation:
    """Find or create a conversation for a contact.

    Args:
        contact_id: The contact ID
        workspace_id: The workspace UUID
        contact_phone: Contact's phone number (normalized)
        workspace_phone: Workspace phone number to use
        db: Database session

    Returns:
        Conversation object
    """
    # Try to find existing conversation by contact_id first (get most recent)
    conv_result = await db.execute(
        select(Conversation)
        .where(
            Conversation.workspace_id == workspace_id,
            Conversation.contact_id == contact_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conversation = conv_result.scalars().first()

    # If not found by contact_id, try finding by phone number
    if conversation is None:
        normalized_contact_phone = normalize_phone_safe(contact_phone) or contact_phone
        conv_result = await db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                or_(
                    Conversation.contact_phone == contact_phone,
                    Conversation.contact_phone == normalized_contact_phone,
                ),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalars().first()

        # If found by phone, link it to this contact
        if conversation is not None:
            conversation.contact_id = contact_id

    # If still no conversation, create one
    if conversation is None:
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact_id,
            workspace_phone=workspace_phone,
            contact_phone=normalize_phone_safe(contact_phone) or contact_phone,
            channel="sms",
            ai_enabled=False,
        )
        db.add(conversation)

    return conversation
