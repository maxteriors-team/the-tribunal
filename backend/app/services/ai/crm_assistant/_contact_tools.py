"""Contact and dashboard CRM assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.encryption import hash_phone, hash_value
from app.db.scope import select_workspace_owned
from app.models.appointment import Appointment
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.tag import ContactTag, Tag
from app.schemas.contact import ContactUpdate
from app.services.ai.contact_context_snapshot import (
    MAX_TIMELINE_ITEMS,
    MAX_TIMELINE_OFFSET,
    ContactContextSnapshotService,
)
from app.services.ai.crm_assistant._pagination import count_matching, listing, local_listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_errors import (
    conflict,
    invalid_argument,
    not_found,
    validation_failed,
)
from app.services.contacts.contact_filters import apply_contact_filters
from app.services.contacts.contact_repository import (
    get_contact_by_id,
    get_contact_timeline,
)
from app.services.contacts.contact_repository import (
    update_contact as repository_update_contact,
)
from app.services.dashboard.today_queue_service import TodayQueueService
from app.services.tags import TagService
from app.utils.phone import normalize_phone_safe, phone_lookup_variants

# Shortest digit run we treat as a phone-number lookup. Below this a numeric
# query is far more likely to be a house number or a partial name fragment.
_MIN_PHONE_QUERY_DIGITS = 7


def phone_hash_candidates(query: str) -> list[str]:
    """Return lookup hashes for every canonical format of a phone-like query.

    ``Contact.phone_number`` is Fernet-encrypted and non-deterministic, so an
    ILIKE against it encrypts the *pattern* before it reaches Postgres and can
    never match. Equality against the deterministic, indexed ``phone_hash`` is
    the only path that works. The operator may type any format, so every
    canonical variant is hashed and matched with ``IN``.
    """

    digit_count = sum(1 for char in query if char.isdigit())
    if digit_count < _MIN_PHONE_QUERY_DIGITS:
        return []
    return sorted({hash_phone(variant) for variant in phone_lookup_variants(query)})


def email_hash_candidate(query: str) -> str | None:
    """Return the lookup hash for an email-shaped query, else ``None``.

    Same reason as :func:`phone_hash_candidates`: ``Contact.email`` is
    encrypted, so only ``email_hash`` equality can match.
    """

    candidate = query.strip()
    if "@" not in candidate or any(char.isspace() for char in candidate):
        return None
    return hash_value(candidate)


def contact_search_predicate(query: str) -> ColumnElement[bool] | None:
    """Build the OR-predicate for a free-text contact search.

    Plain columns (name, company) use ILIKE. Encrypted contact details use
    deterministic hash equality. ``None`` means "no filter" — an empty query
    lists the newest contacts.
    """

    term = query.strip()
    if not term:
        return None

    pattern = f"%{term}%"
    clauses: list[ColumnElement[bool]] = [
        Contact.first_name.ilike(pattern),
        Contact.last_name.ilike(pattern),
        Contact.company_name.ilike(pattern),
    ]

    phone_hashes = phone_hash_candidates(term)
    if phone_hashes:
        clauses.append(Contact.phone_hash.in_(phone_hashes))

    email_hash = email_hash_candidate(term)
    if email_hash is not None:
        clauses.append(Contact.email_hash == email_hash)

    return or_(*clauses)


# Fields the assistant may edit directly. Tags and notes have additive tools so
# a model cannot accidentally replace their entire history/collection.
_CONTACT_UPDATE_FIELDS = frozenset(
    {
        "first_name",
        "last_name",
        "email",
        "phone_number",
        "company_name",
        "address_line1",
        "address_line2",
        "address_city",
        "address_state",
        "address_zip",
        "status",
        "lead_score",
        "important_dates",
    }
)
_MAX_NOTE_LENGTH = 5000
_MAX_TAGS_PER_CALL = 20


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bounded_integer(
    value: object,
    *,
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc
    return min(max(parsed, minimum), maximum)


def _identity_resolution(
    *,
    query: str,
    total: int,
    serialized_contacts: list[dict[str, Any]],
) -> dict[str, object] | None:
    if not query.strip():
        return None
    if total == 0:
        return {
            "status": "not_found",
            "candidate_count": 0,
            "next_action": "Ask for another identifier; do not infer a contact.",
        }
    if total == 1 and serialized_contacts:
        return {
            "status": "resolved",
            "candidate_count": 1,
            "contact_id": serialized_contacts[0]["id"],
            "next_action": "Call get_contact_context before claiming current record state.",
        }
    return {
        "status": "ambiguous",
        "candidate_count": total,
        "next_action": (
            "Ask the operator to choose a candidate; do not guess or call "
            "get_contact_context until one contact_id is confirmed."
        ),
    }


def _loaded_tag_names(contact: Contact) -> list[str]:
    """Read tag names without triggering an async lazy load."""

    contact_tags = contact.__dict__.get("contact_tags")
    if not contact_tags:
        return []
    return sorted(
        contact_tag.tag.name for contact_tag in contact_tags if contact_tag.tag is not None
    )


def serialize_contact(contact: Contact) -> dict[str, Any]:
    """Serialize the useful operator-facing contact record, including notes."""

    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "phone": contact.phone_number,
        "email": contact.email,
        "company": contact.company_name,
        "address": {
            "line1": contact.address_line1,
            "line2": contact.address_line2,
            "city": contact.address_city,
            "state": contact.address_state,
            "zip": contact.address_zip,
        },
        "status": contact.status,
        "lead_score": contact.lead_score,
        "engagement_score": contact.engagement_score,
        "is_qualified": contact.is_qualified,
        "qualification_signals": contact.qualification_signals,
        "tags": _loaded_tag_names(contact),
        "notes": contact.notes,
        "important_dates": contact.important_dates,
        "source": contact.source,
        "last_appointment_status": contact.last_appointment_status,
        "last_engaged_at": _iso(contact.last_engaged_at),
        "created_at": _iso(contact.created_at),
        "updated_at": _iso(contact.updated_at),
    }


def _parse_datetime(value: object, field: str) -> datetime | None:
    """Parse an ISO-8601 tool argument and normalize naive values to UTC."""

    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 date or datetime") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


class ContactAssistantTools:
    """Read and mutate contacts for CRM assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "search_contacts": self.search_contacts,
            "find_contacts": self.find_contacts,
            "get_contact": self.get_contact,
            "get_contact_context": self.get_contact_context,
            "create_contact": self.create_contact,
            "update_contact": self.update_contact,
            "add_contact_note": self.add_contact_note,
            "add_contact_tags": self.add_contact_tags,
            "get_dashboard_stats": self.get_dashboard_stats,
            "get_today_queue": self.get_today_queue,
        }

    async def search_contacts(self, args: ToolArguments) -> dict[str, object]:
        query = str(args.get("query") or "")
        limit = min(args.get("limit", 10), 50)

        stmt = select_workspace_owned(Contact, self.context.workspace_id)
        predicate = contact_search_predicate(query)
        if predicate is not None:
            stmt = stmt.where(predicate)

        total = await count_matching(self.context.db, Contact, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Contact.created_at.desc()).limit(limit)
        )
        contacts = result.scalars().all()
        serialized_contacts = [
            {
                "id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone_number,
                "email": contact.email,
                "status": contact.status,
                "company": contact.company_name,
                "lead_score": contact.lead_score,
                "engagement_score": contact.engagement_score,
                "is_qualified": contact.is_qualified,
                "qualification_signals": contact.qualification_signals,
                "source": contact.source,
                "last_appointment_status": contact.last_appointment_status,
                "last_engaged_at": (
                    contact.last_engaged_at.isoformat() if contact.last_engaged_at else None
                ),
                "created_at": contact.created_at.isoformat() if contact.created_at else None,
                "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
            }
            for contact in contacts
        ]
        resolution = _identity_resolution(
            query=query,
            total=total,
            serialized_contacts=serialized_contacts,
        )
        return listing(
            serialized_contacts,
            total=total,
            extra={"identity_resolution": resolution} if resolution else None,
        )

    async def get_contact_context(self, args: ToolArguments) -> dict[str, object]:
        """Return one complete, timestamped, workspace-scoped contact snapshot."""

        try:
            contact_id = _bounded_integer(
                args.get("contact_id"),
                field="contact_id",
                default=0,
                minimum=0,
                maximum=2**63 - 1,
            )
            timeline_limit = _bounded_integer(
                args.get("timeline_limit"),
                field="timeline_limit",
                default=20,
                minimum=1,
                maximum=MAX_TIMELINE_ITEMS,
            )
            timeline_offset = _bounded_integer(
                args.get("timeline_offset"),
                field="timeline_offset",
                default=0,
                minimum=0,
                maximum=MAX_TIMELINE_OFFSET,
            )
        except ValueError as exc:
            return invalid_argument(
                str(exc),
                "Use integer contact_id, timeline_limit, and timeline_offset values.",
            )
        if contact_id <= 0:
            return invalid_argument(
                "contact_id must be a positive integer.",
                "Call search_contacts and use its resolved contact_id.",
            )

        snapshot = await ContactContextSnapshotService(
            self.context.db,
            timeline_limit=timeline_limit,
            timeline_offset=timeline_offset,
        ).get_snapshot(
            workspace_id=self.context.workspace_id,
            contact_id=contact_id,
        )
        if snapshot is None:
            return not_found(
                "Contact",
                "Call search_contacts in this workspace; do not search another workspace.",
            )

        returned = len(snapshot.recent_timeline)
        next_offset = (
            snapshot.timeline_offset + snapshot.timeline_limit
            if snapshot.timeline_has_more
            else None
        )
        return {
            "success": True,
            "data": {
                "snapshot": snapshot.model_dump(mode="json", exclude={"workspace_id"}),
                "rendered_context": snapshot.render(),
                "timeline_page": {
                    "offset": snapshot.timeline_offset,
                    "limit": snapshot.timeline_limit,
                    "returned": returned,
                    "has_more": snapshot.timeline_has_more,
                    "next_offset": next_offset,
                },
                "evidence_rules": {
                    "observed_at": snapshot.observed_at.isoformat(),
                    "record_timestamp_path": "provenance[*].updated_at",
                    "untrusted_content_paths": [
                        "snapshot.free_form_notes[*].content",
                        "snapshot.recent_timeline[*].content",
                    ],
                    "state_precedence": (
                        "Current structured fields override stale notes or timeline text; "
                        "surface genuine structured conflicts instead of choosing one silently."
                    ),
                    "response_requirement": (
                        "Cite observed_at and the relevant provenance.updated_at timestamp "
                        "for every current-state claim."
                    ),
                },
            },
        }

    async def get_contact(self, args: ToolArguments) -> dict[str, object]:
        """Return one full, workspace-scoped contact record and optional timeline."""

        contact_id = int(args["contact_id"])
        contact = await get_contact_by_id(
            contact_id,
            self.context.workspace_id,
            self.context.db,
        )
        if contact is None:
            return not_found(
                "Contact",
                "Call search_contacts or find_contacts to get a valid contact_id.",
            )

        data = serialize_contact(contact)
        if args.get("include_timeline"):
            limit = min(max(int(args.get("timeline_limit", 20)), 1), 50)
            timeline = await get_contact_timeline(
                contact_id,
                self.context.workspace_id,
                self.context.db,
                limit=limit,
            )
            data["recent_timeline"] = [
                {
                    **item,
                    "id": str(item["id"]),
                    "timestamp": (
                        item["timestamp"].isoformat()
                        if isinstance(item.get("timestamp"), datetime)
                        else item.get("timestamp")
                    ),
                }
                for item in timeline
            ]
        return {"success": True, "data": data}

    async def find_contacts(self, args: ToolArguments) -> dict[str, object]:
        """Find contacts with structured filters from the shared filter engine."""

        raw_filters = args.get("filters")
        filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}
        limit = min(max(int(args.get("limit", 20)), 1), 50)

        try:
            created_after = _parse_datetime(filters.get("created_after"), "created_after")
            created_before = _parse_datetime(filters.get("created_before"), "created_before")
            last_engaged_before = _parse_datetime(
                filters.get("last_engaged_before"), "last_engaged_before"
            )
            last_engaged_after = _parse_datetime(
                filters.get("last_engaged_after"), "last_engaged_after"
            )
        except ValueError as exc:
            return invalid_argument(str(exc), "Use ISO dates such as 2026-07-29.")

        not_contacted_days = filters.get("not_contacted_days")
        if not_contacted_days is not None:
            if last_engaged_before is not None:
                return invalid_argument(
                    "Use either not_contacted_days or last_engaged_before, not both.",
                    "Remove one of the two overlapping filters and retry.",
                )
            days = int(not_contacted_days)
            if days < 1 or days > 3650:
                return invalid_argument(
                    "not_contacted_days must be between 1 and 3650.",
                    "Choose a positive number of days and retry.",
                )
            last_engaged_before = datetime.now(UTC) - timedelta(days=days)

        requested_tag_names = [
            str(value).strip() for value in filters.get("tags", []) if str(value).strip()
        ]
        tags_match = str(filters.get("tags_match") or "any")
        tag_ids: list[Any] = []
        resolved_tag_names: list[str] = []
        if requested_tag_names:
            tag_result = await self.context.db.execute(
                select(Tag.id, Tag.name).where(
                    Tag.workspace_id == self.context.workspace_id,
                    func.lower(Tag.name).in_([name.lower() for name in requested_tag_names]),
                )
            )
            tag_rows = tag_result.all()
            tag_ids = [row[0] for row in tag_rows]
            resolved_tag_names = [row[1] for row in tag_rows]
            if not tag_ids and tags_match != "none":
                return listing(
                    [],
                    total=0,
                    extra={"unresolved_tags": requested_tag_names},
                )

        filter_rules: list[dict[str, Any]] = []
        status = filters.get("status")
        if status:
            filter_rules.append({"field": "status", "operator": "equals", "value": status})

        stmt = select_workspace_owned(Contact, self.context.workspace_id).options(
            selectinload(Contact.contact_tags).selectinload(ContactTag.tag)
        )
        stmt = apply_contact_filters(
            stmt,
            self.context.workspace_id,
            tags=tag_ids or None,
            tags_match=tags_match,
            lead_score_min=filters.get("lead_score_min"),
            lead_score_max=filters.get("lead_score_max"),
            is_qualified=filters.get("is_qualified"),
            source=filters.get("source"),
            company_name=filters.get("company_name"),
            created_after=created_after,
            created_before=created_before,
            enrichment_status=filters.get("enrichment_status"),
            filter_rules=filter_rules or None,
        )

        include_never_contacted = bool(filters.get("include_never_contacted", True))
        if last_engaged_before is not None:
            before_clause = Contact.last_engaged_at <= last_engaged_before
            if include_never_contacted:
                before_clause = or_(Contact.last_engaged_at.is_(None), before_clause)
            stmt = stmt.where(before_clause)
        if last_engaged_after is not None:
            stmt = stmt.where(Contact.last_engaged_at >= last_engaged_after)

        total = await count_matching(self.context.db, Contact, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Contact.created_at.desc(), Contact.id.desc()).limit(limit)
        )
        contacts = result.scalars().unique().all()
        resolved_lower = {name.lower() for name in resolved_tag_names}
        unresolved_tags = sorted(
            name for name in requested_tag_names if name.lower() not in resolved_lower
        )
        extra = {"unresolved_tags": unresolved_tags} if unresolved_tags else None
        return listing(
            [serialize_contact(contact) for contact in contacts],
            total=total,
            extra=extra,
        )

    async def update_contact(self, args: ToolArguments) -> dict[str, object]:
        """Update one contact through the existing contact repository."""

        contact_id = int(args["contact_id"])
        contact = await get_contact_by_id(
            contact_id,
            self.context.workspace_id,
            self.context.db,
        )
        if contact is None:
            return not_found(
                "Contact",
                "Call search_contacts or find_contacts to get a valid contact_id.",
            )

        raw_updates = {key: value for key, value in args.items() if key in _CONTACT_UPDATE_FIELDS}
        if not raw_updates:
            return invalid_argument(
                "No contact fields were provided to update.",
                "Include at least one field to change alongside contact_id.",
            )

        if "phone_number" in raw_updates:
            normalized_phone = normalize_phone_safe(str(raw_updates["phone_number"]))
            if normalized_phone is None:
                return invalid_argument(
                    "phone_number is not a valid phone number.",
                    "Use a complete number, preferably E.164 such as +15551234567.",
                )
            duplicate_result = await self.context.db.execute(
                select_workspace_owned(
                    Contact,
                    self.context.workspace_id,
                    Contact.phone_hash == hash_phone(normalized_phone),
                    Contact.id != contact_id,
                ).limit(1)
            )
            duplicate = duplicate_result.scalar_one_or_none()
            if duplicate is not None:
                return conflict(
                    "Another contact already uses that phone number.",
                    "Update the existing contact in `data` instead of merging records implicitly.",
                    data={"id": duplicate.id},
                )
            raw_updates["phone_number"] = normalized_phone

        try:
            validated = ContactUpdate.model_validate(raw_updates).model_dump(exclude_unset=True)
        except ValidationError as exc:
            return validation_failed("Contact", str(exc))

        updated = await repository_update_contact(contact, self.context.db, validated)
        return {"success": True, "data": serialize_contact(updated)}

    async def add_contact_note(self, args: ToolArguments) -> dict[str, object]:
        """Append a timestamped note without overwriting prior notes."""

        contact_id = int(args["contact_id"])
        note = str(args["note"]).strip()
        if not note:
            return invalid_argument("The note cannot be blank.", "Provide the note text and retry.")
        if len(note) > _MAX_NOTE_LENGTH:
            return invalid_argument(
                f"The note is longer than {_MAX_NOTE_LENGTH} characters.",
                "Shorten the note and retry.",
            )

        contact = await get_contact_by_id(
            contact_id,
            self.context.workspace_id,
            self.context.db,
        )
        if contact is None:
            return not_found(
                "Contact",
                "Call search_contacts or find_contacts to get a valid contact_id.",
            )

        entry = f"[{datetime.now(UTC).isoformat(timespec='minutes')}] {note}"
        existing = (contact.notes or "").rstrip()
        notes = f"{existing}\n\n{entry}" if existing else entry
        updated = await repository_update_contact(contact, self.context.db, {"notes": notes})
        return {
            "success": True,
            "data": {
                "id": updated.id,
                "note_added": note,
                "notes": updated.notes,
            },
        }

    async def add_contact_tags(self, args: ToolArguments) -> dict[str, object]:
        """Idempotently add named tags without replacing existing tags."""

        contact_id = int(args["contact_id"])
        names = [str(value).strip() for value in args.get("tags", []) if str(value).strip()]
        if not names:
            return invalid_argument(
                "At least one non-blank tag is required.",
                "Provide a `tags` array and retry.",
            )
        if len(names) > _MAX_TAGS_PER_CALL:
            return invalid_argument(
                f"At most {_MAX_TAGS_PER_CALL} tags can be added at once.",
                "Split the tags into smaller groups.",
            )

        contact = await get_contact_by_id(
            contact_id,
            self.context.workspace_id,
            self.context.db,
        )
        if contact is None:
            return not_found(
                "Contact",
                "Call search_contacts or find_contacts to get a valid contact_id.",
            )

        added = await TagService(self.context.db).add_tags_to_contact(
            workspace_id=self.context.workspace_id,
            contact_id=contact_id,
            names=names,
        )
        await self.context.db.commit()
        all_tags_result = await self.context.db.execute(
            select(Tag.name)
            .join(ContactTag, ContactTag.tag_id == Tag.id)
            .where(
                ContactTag.contact_id == contact_id,
                Tag.workspace_id == self.context.workspace_id,
            )
            .order_by(Tag.name)
        )
        return {
            "success": True,
            "data": {
                "id": contact_id,
                "added_tags": [tag.name for tag in added],
                "tags": list(all_tags_result.scalars().all()),
            },
        }

    async def create_contact(self, args: ToolArguments) -> dict[str, object]:
        phone = str(args["phone"])
        # ``phone_number`` is non-deterministically encrypted, so equality
        # against it never matches and this guard used to be dead code —
        # duplicates were created and reported as success. Match the
        # deterministic, indexed hash instead, across every format variant.
        duplicate_hashes = phone_hash_candidates(phone) or [hash_phone(phone)]
        existing = await self.context.db.execute(
            select_workspace_owned(
                Contact,
                self.context.workspace_id,
                Contact.phone_hash.in_(duplicate_hashes),
            ).limit(1)
        )
        duplicate = existing.scalar_one_or_none()
        if duplicate is not None:
            # Return the id so the model can update instead of duplicating.
            return conflict(
                "A contact with that phone number already exists.",
                "Call update_contact with the id in `data` instead of creating a new one.",
                data={
                    "id": duplicate.id,
                    "first_name": duplicate.first_name,
                    "last_name": duplicate.last_name,
                    "phone": duplicate.phone_number,
                },
            )

        contact = Contact(
            workspace_id=self.context.workspace_id,
            first_name=args["first_name"],
            last_name=args.get("last_name"),
            phone_number=phone,
            email=args.get("email"),
            notes=args.get("notes"),
        )
        self.context.db.add(contact)
        await self.context.db.flush()

        return {
            "success": True,
            "data": {
                "id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone_number,
            },
        }

    async def get_today_queue(self, _args: ToolArguments) -> dict[str, object]:
        """Ordered Today mission queue: approvals, nudges, batches, drafts, gaps."""
        queue = await TodayQueueService(self.context.db).get_today_queue(self.context.workspace_id)
        return local_listing(
            [item.model_dump() for item in queue.items],
            extra={"generated_at": queue.generated_at.isoformat()},
        )

    async def get_dashboard_stats(self, _args: ToolArguments) -> dict[str, object]:
        contacts_count = await self.context.db.scalar(
            select_workspace_owned(Contact, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Contact)
        )
        campaigns_count = await self.context.db.scalar(
            select_workspace_owned(Campaign, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Campaign)
        )
        conversations_count = await self.context.db.scalar(
            select_workspace_owned(Conversation, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Conversation)
        )
        appointments_count = await self.context.db.scalar(
            select_workspace_owned(
                Appointment,
                self.context.workspace_id,
                Appointment.scheduled_at >= datetime.now(UTC),
            )
            .with_only_columns(func.count())
            .select_from(Appointment)
        )

        return {
            "success": True,
            "data": {
                "contacts": contacts_count or 0,
                "campaigns": campaigns_count or 0,
                "conversations": conversations_count or 0,
                "upcoming_appointments": appointments_count or 0,
            },
        }
