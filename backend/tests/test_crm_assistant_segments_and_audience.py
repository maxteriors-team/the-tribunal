"""CRM assistant saved audiences and bounded campaign enrollment."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.segment import Segment
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.campaigns.audience_service import (
    MAX_CAMPAIGN_AUDIENCE_SIZE,
    CampaignAudienceError,
    CampaignAudienceService,
)
from app.services.contacts.contact_filter_validation import (
    ContactFilterValidationError,
    validate_contact_filter_rules,
)


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self.rows)

    def scalar_one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar_one_or_none(self) -> Any | None:
        return self.rows[0] if self.rows else None


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _campaign(workspace_id: uuid.UUID, **overrides: Any) -> Campaign:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": workspace_id,
        "name": "Dormant lead follow-up",
        "campaign_type": CampaignType.SMS,
        "status": CampaignStatus.DRAFT,
        "total_contacts": 0,
    }
    values.update(overrides)
    return Campaign(**values)


def _contact(
    contact_id: int,
    workspace_id: uuid.UUID,
    *,
    phone: str | None = "+15550000000",
    sms_consent_status: str = "unknown",
) -> Contact:
    return Contact(
        id=contact_id,
        workspace_id=workspace_id,
        first_name=f"Contact {contact_id}",
        last_name="Test",
        phone_number=phone,
        sms_consent_status=sms_consent_status,
        status="new",
    )


def _segment(workspace_id: uuid.UUID) -> Segment:
    return Segment(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="New leads",
        definition={
            "logic": "and",
            "rules": [{"field": "status", "operator": "equals", "value": "new"}],
        },
        is_dynamic=True,
        contact_count=0,
    )


@pytest.mark.parametrize(
    "rules",
    [
        [],
        [{"field": "unknown", "operator": "equals", "value": "x"}],
        [{"field": "status", "operator": "contains", "value": "new"}],
        [{"field": "tags", "operator": "has_any", "value": ["not-a-uuid"]}],
    ],
)
def test_model_authored_contact_filters_fail_closed(rules: list[dict[str, Any]]) -> None:
    with pytest.raises(ContactFilterValidationError):
        validate_contact_filter_rules(rules)


async def test_create_segment_rejects_unsupported_filter_before_querying(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "create_segment",
        {
            "name": "Unsafe broad audience",
            "filter_rules": [{"field": "unknown", "operator": "equals", "value": "x"}],
        },
    )

    assert result["code"] == "invalid_argument"
    db.execute.assert_not_awaited()
    db.add.assert_not_called()


async def test_create_segment_saves_normalized_dynamic_definition_and_count(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    db.execute.return_value = _Result([3])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "create_segment",
        {
            "name": " New leads ",
            "filter_logic": "and",
            "filter_rules": [{"field": "status", "operator": "equals", "value": "new"}],
        },
    )

    assert result["success"] is True
    segment = db.add.call_args.args[0]
    assert isinstance(segment, Segment)
    assert segment.name == "New leads"
    assert segment.definition == {
        "logic": "and",
        "rules": [{"field": "status", "operator": "equals", "value": "new"}],
    }
    assert segment.contact_count == 3
    assert segment.is_dynamic is True


async def test_create_segment_rejects_foreign_tag_ids(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    tag_id = uuid.uuid4()
    db.execute.return_value = _Result([])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "create_segment",
        {
            "name": "Foreign tag",
            "filter_rules": [{"field": "tags", "operator": "has_any", "value": [str(tag_id)]}],
        },
    )

    assert result["code"] == "not_found"
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tags.workspace_id" in compiled
    assert workspace_id.hex in compiled
    db.add.assert_not_called()


async def test_campaign_lookup_is_tenant_scoped_and_non_disclosing(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    db.execute.return_value = _Result([])

    with pytest.raises(CampaignAudienceError, match="Campaign not found") as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=uuid.uuid4(), contact_ids=[1]
        )

    assert error.value.code == "not_found"
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "campaigns.workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_explicit_audience_rejects_foreign_contacts_before_inserting(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    db.execute.side_effect = [_Result([campaign]), _Result([_contact(1, workspace_id)])]

    with pytest.raises(CampaignAudienceError) as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=campaign.id, contact_ids=[1, 2]
        )

    assert error.value.code == "not_found"
    assert db.execute.await_count == 2
    contact_query = db.execute.await_args_list[1].args[0]
    compiled = str(contact_query.compile(compile_kwargs={"literal_binds": True}))
    assert "contacts.workspace_id" in compiled
    assert campaign.total_contacts == 0


async def test_enrollment_rejects_non_draft_campaign(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id, status=CampaignStatus.RUNNING)
    db.execute.return_value = _Result([campaign])

    with pytest.raises(CampaignAudienceError) as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=campaign.id, contact_ids=[1]
        )

    assert error.value.code == "campaign_not_draft"
    assert db.execute.await_count == 1


async def test_enrollment_deduplicates_and_counts_ineligible_contacts(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    contacts = [
        _contact(1, workspace_id),
        _contact(2, workspace_id, phone=None),
        _contact(3, workspace_id, sms_consent_status="opted_out"),
        _contact(4, workspace_id),
    ]
    db.execute.side_effect = [
        _Result([campaign]),
        _Result(contacts),
        _Result([1]),
        _Result([4]),
    ]

    result = await CampaignAudienceService(db, workspace_id).enroll(
        campaign_id=campaign.id, contact_ids=[1, 2, 3, 4, 4]
    )

    assert result.source_count == 4
    assert result.eligible_count == 2
    assert result.duplicate_count == 1
    assert result.ineligible_count == 2
    assert result.added_count == 1
    assert campaign.total_contacts == 1


async def test_full_segment_audience_enrolls_more_than_preview_size(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    segment = _segment(workspace_id)
    contacts = [_contact(contact_id, workspace_id) for contact_id in range(1, 6)]
    db.execute.side_effect = [
        _Result([campaign]),
        _Result([segment]),
        _Result([len(contacts)]),
        _Result(contacts),
        _Result([]),
        _Result([contact.id for contact in contacts]),
    ]

    result = await CampaignAudienceService(db, workspace_id).enroll(
        campaign_id=campaign.id, segment_id=segment.id
    )

    assert result.source_count == 5
    assert result.added_count == 5
    assert campaign.total_contacts == 5


async def test_oversized_segment_fails_before_any_enrollment_write(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    segment = _segment(workspace_id)
    db.execute.side_effect = [
        _Result([campaign]),
        _Result([segment]),
        _Result([MAX_CAMPAIGN_AUDIENCE_SIZE + 1]),
    ]

    with pytest.raises(CampaignAudienceError) as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=campaign.id, segment_id=segment.id
        )

    assert error.value.code == "audience_too_large"
    assert db.execute.await_count == 3
    assert campaign.total_contacts == 0


async def test_persisted_segment_rejects_tag_from_another_workspace(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    segment = _segment(workspace_id)
    segment.definition = {
        "logic": "and",
        "rules": [{"field": "tags", "operator": "has_any", "value": [str(uuid.uuid4())]}],
    }
    db.execute.side_effect = [_Result([campaign]), _Result([segment]), _Result([])]

    with pytest.raises(CampaignAudienceError) as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=campaign.id, segment_id=segment.id
        )

    assert error.value.code == "invalid_segment"
    assert db.execute.await_count == 3
    assert campaign.total_contacts == 0


async def test_oversized_explicit_input_fails_before_contact_lookup(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    campaign = _campaign(workspace_id)
    db.execute.return_value = _Result([campaign])

    with pytest.raises(CampaignAudienceError) as error:
        await CampaignAudienceService(db, workspace_id).enroll(
            campaign_id=campaign.id,
            contact_ids=[1] * (MAX_CAMPAIGN_AUDIENCE_SIZE + 1),
        )

    assert error.value.code == "audience_too_large"
    assert db.execute.await_count == 1
    assert campaign.total_contacts == 0
