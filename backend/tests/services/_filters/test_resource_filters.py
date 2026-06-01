"""Behavior-preservation tests for the three resource filter engines.

These confirm that:

* The existing simple-kwargs API still produces the same WHERE clauses
  it did before the refactor.
* All three engines now accept ``filter_rules`` / ``filter_logic`` and
  route them through the shared helper.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType, LeadDiscoveryJob
from app.models.lead_prospect import LeadProspect, ProspectIdentityKind, ProspectStatus
from app.models.opportunity import Opportunity
from app.models.outbound_mission import MissionStatus, OutboundMission
from app.services._filters import apply_filter_specs
from app.services.campaigns.campaign_filters import apply_campaign_filters
from app.services.contacts.contact_filters import apply_contact_filters, apply_contact_list_filters
from app.services.opportunities.opportunity_filters import apply_opportunity_filters
from app.services.outbound.mission_service import (
    _DISCOVERY_JOB_FILTER_SPECS,
    _MISSION_FILTER_SPECS,
    _PROSPECT_FILTER_SPECS,
)

_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _sql(stmt: Any) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class TestContactFiltersBehaviorPreserved:
    def test_base_list_filters_are_shared(self) -> None:
        stmt = apply_contact_list_filters(
            select(Contact),
            status_filter="new",
            search="alice",
        )
        sql = _sql(stmt)
        assert "contacts.status = 'new'" in sql
        assert "%alice%" in sql
        assert "contacts.first_name ILIKE" in sql
        assert "contacts.company_name ILIKE" in sql

    def test_simple_kwargs_still_work(self) -> None:
        stmt = apply_contact_filters(
            select(Contact),
            _WORKSPACE_ID,
            lead_score_min=50,
            lead_score_max=90,
            is_qualified=True,
            source="webform",
            company_name="acme",
            enrichment_status="done",
        )
        sql = _sql(stmt)
        assert "contacts.lead_score >= 50" in sql
        assert "contacts.lead_score <= 90" in sql
        assert "contacts.is_qualified = true" in sql
        assert "contacts.source = 'webform'" in sql
        assert "%acme%" in sql
        assert "contacts.enrichment_status = 'done'" in sql

    def test_created_date_range(self) -> None:
        after = datetime(2024, 1, 1, tzinfo=UTC)
        before = datetime(2024, 12, 31, tzinfo=UTC)
        stmt = apply_contact_filters(
            select(Contact),
            _WORKSPACE_ID,
            created_after=after,
            created_before=before,
        )
        sql = _sql(stmt)
        assert "contacts.created_at >=" in sql
        assert "contacts.created_at <=" in sql

    def test_filter_rules_and_logic(self) -> None:
        stmt = apply_contact_filters(
            select(Contact),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "lead_score", "operator": "gte", "value": 75},
                {"field": "is_qualified", "operator": "is_true"},
            ],
            filter_logic="and",
        )
        sql = _sql(stmt)
        assert "contacts.lead_score >= 75" in sql
        assert "contacts.is_qualified IS true" in sql

    def test_filter_rules_or_logic(self) -> None:
        stmt = apply_contact_filters(
            select(Contact),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "source", "operator": "equals", "value": "webform"},
                {"field": "source", "operator": "equals", "value": "import"},
            ],
            filter_logic="or",
        )
        sql = _sql(stmt)
        assert " OR " in sql.upper()

    def test_filter_rules_tag_membership_extra_resolver(self) -> None:
        tag_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        stmt = apply_contact_filters(
            select(Contact),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "tags", "operator": "has_any", "value": [str(tag_id)]},
            ],
        )
        sql = _sql(stmt)
        # has_any compiles to a subquery against contact_tags
        assert "contact_tags" in sql.lower()

    def test_tags_simple_filter_any(self) -> None:
        tag_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        stmt = apply_contact_filters(
            select(Contact), _WORKSPACE_ID, tags=[tag_id], tags_match="any"
        )
        sql = _sql(stmt).lower()
        assert "contact_tags" in sql
        assert " in " in sql

    def test_tags_simple_filter_none(self) -> None:
        tag_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        stmt = apply_contact_filters(
            select(Contact), _WORKSPACE_ID, tags=[tag_id], tags_match="none"
        )
        sql = _sql(stmt).lower()
        assert "not in" in sql


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class TestCampaignFiltersBehaviorPreserved:
    def test_always_scopes_to_workspace(self) -> None:
        stmt = apply_campaign_filters(select(Campaign), _WORKSPACE_ID)
        assert "campaigns.workspace_id" in _sql(stmt)

    def test_simple_kwargs_still_work(self) -> None:
        agent_id = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
        offer_id = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
        stmt = apply_campaign_filters(
            select(Campaign),
            _WORKSPACE_ID,
            status="running",
            campaign_type="sms",
            agent_id=agent_id,
            offer_id=offer_id,
            name="onboarding",
        )
        sql = _sql(stmt)
        assert "campaigns.status = 'running'" in sql
        assert "campaigns.campaign_type = 'sms'" in sql
        assert str(agent_id) in sql
        assert str(offer_id) in sql
        assert "%onboarding%" in sql

    def test_date_ranges(self) -> None:
        stmt = apply_campaign_filters(
            select(Campaign),
            _WORKSPACE_ID,
            created_after=datetime(2024, 1, 1, tzinfo=UTC),
            created_before=datetime(2024, 12, 31, tzinfo=UTC),
            started_after=datetime(2024, 2, 1, tzinfo=UTC),
            started_before=datetime(2024, 11, 30, tzinfo=UTC),
        )
        sql = _sql(stmt)
        assert "campaigns.created_at >=" in sql
        assert "campaigns.created_at <=" in sql
        assert "campaigns.started_at >=" in sql
        assert "campaigns.started_at <=" in sql

    def test_filter_rules_supported(self) -> None:
        stmt = apply_campaign_filters(
            select(Campaign),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "status", "operator": "in", "value": ["running", "scheduled"]},
                {"field": "messages_sent", "operator": "gte", "value": 100},
            ],
            filter_logic="and",
        )
        sql = _sql(stmt)
        assert "campaigns.messages_sent >= 100" in sql
        assert "campaigns.status IN (" in sql


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


class TestOpportunityFiltersBehaviorPreserved:
    def test_always_scopes_to_workspace(self) -> None:
        stmt = apply_opportunity_filters(select(Opportunity), _WORKSPACE_ID)
        assert "opportunities.workspace_id" in _sql(stmt)

    def test_simple_kwargs_still_work(self) -> None:
        pipeline_id = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
        stage_id = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
        stmt = apply_opportunity_filters(
            select(Opportunity),
            _WORKSPACE_ID,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            status="open",
            is_active=True,
            source="campaign",
            search="acme",
            value_min=1000,
            value_max=50000,
            probability_min=20,
            probability_max=80,
        )
        sql = _sql(stmt)
        assert str(pipeline_id) in sql
        assert str(stage_id) in sql
        assert "opportunities.status = 'open'" in sql
        assert "opportunities.is_active = true" in sql
        assert "opportunities.source = 'campaign'" in sql
        assert "%acme%" in sql
        assert "opportunities.amount >= 1000" in sql
        assert "opportunities.amount <= 50000" in sql
        assert "opportunities.probability >= 20" in sql
        assert "opportunities.probability <= 80" in sql

    def test_owner_id_maps_to_assigned_user(self) -> None:
        # owner_id is a kwarg alias for assigned_user_id; the kwarg accepts
        # uuid as the existing signature does — verify the column appears.
        owner_id = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
        stmt = apply_opportunity_filters(select(Opportunity), _WORKSPACE_ID, owner_id=owner_id)
        assert "opportunities.assigned_user_id" in _sql(stmt)

    def test_filter_rules_supported(self) -> None:
        stmt = apply_opportunity_filters(
            select(Opportunity),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "status", "operator": "in", "value": ["open", "won"]},
                {"field": "amount", "operator": "gte", "value": 5000},
            ],
            filter_logic="and",
        )
        sql = _sql(stmt)
        assert "opportunities.amount >= 5000" in sql
        assert "opportunities.status IN (" in sql

    def test_filter_rules_or_logic(self) -> None:
        stmt = apply_opportunity_filters(
            select(Opportunity),
            _WORKSPACE_ID,
            filter_rules=[
                {"field": "status", "operator": "equals", "value": "won"},
                {"field": "amount", "operator": "gte", "value": 100000},
            ],
            filter_logic="or",
        )
        assert " OR " in _sql(stmt).upper()


# ---------------------------------------------------------------------------
# Outbound mission resources
# ---------------------------------------------------------------------------


class TestOutboundResourceFilterSpecs:
    def test_mission_specs_match_previous_list_filters(self) -> None:
        stmt = apply_filter_specs(
            select(OutboundMission),
            _MISSION_FILTER_SPECS,
            {
                "status_filter": MissionStatus.DRAFT,
                "objective": "book_call",
                "search": "roofing",
            },
        )
        sql = _sql(stmt)
        assert "outbound_missions.status = 'draft'" in sql
        assert "outbound_missions.objective = 'book_call'" in sql
        assert "%roofing%" in sql

    def test_prospect_specs_match_previous_list_filters(self) -> None:
        stmt = apply_filter_specs(
            select(LeadProspect),
            _PROSPECT_FILTER_SPECS,
            {
                "status_filter": ProspectStatus.ENRICHED,
                "identity_kind": ProspectIdentityKind.EMAIL,
                "source_type": "google_places",
                "min_score": 25,
                "max_score": 80,
                "has_email": True,
                "has_phone": False,
                "search": "acme",
            },
        )
        sql = _sql(stmt)
        assert "lead_prospects.status = 'enriched'" in sql
        assert "lead_prospects.identity_kind = 'email'" in sql
        assert "lead_prospects.source_type = 'google_places'" in sql
        assert "lead_prospects.lead_score >= 25" in sql
        assert "lead_prospects.lead_score <= 80" in sql
        assert "lead_prospects.email_hash IS NOT NULL" in sql
        assert "lead_prospects.phone_hash IS NULL" in sql
        assert "%acme%" in sql

    def test_discovery_job_specs_match_previous_list_filters(self) -> None:
        stmt = apply_filter_specs(
            select(LeadDiscoveryJob),
            _DISCOVERY_JOB_FILTER_SPECS,
            {
                "status_filter": DiscoveryJobStatus.SUCCEEDED,
                "source_type": DiscoverySourceType.GOOGLE_PLACES,
            },
        )
        sql = _sql(stmt)
        assert "lead_discovery_jobs.status = 'succeeded'" in sql
        assert "lead_discovery_jobs.source_type = 'google_places'" in sql
