"""Tests for outbound campaign reply classification and side effects."""

from datetime import UTC, datetime
from uuid import uuid4

from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus
from app.models.drip_campaign import ResponseCategory
from app.services.campaigns.reply_handler import (
    _recommended_action,
    _update_campaign_contact,
)
from app.services.reactivation.response_classifier import classify_by_keywords


def _campaign_contact() -> tuple[Campaign, CampaignContact]:
    campaign = Campaign(
        id=uuid4(),
        workspace_id=uuid4(),
        name="Spring Sellers",
        from_phone_number="+15555550100",
        replies_received=0,
        contacts_qualified=0,
        contacts_opted_out=0,
        appointments_booked=0,
    )
    campaign_contact = CampaignContact(
        id=uuid4(),
        campaign_id=campaign.id,
        contact_id=123,
        status=CampaignContactStatus.DELIVERED,
        messages_received=0,
        is_qualified=False,
        opted_out=False,
    )
    return campaign, campaign_contact


class TestCampaignReplyKeywordClassification:
    """Keyword classifier recognizes the campaign reply taxonomy."""

    def test_interested_reply(self) -> None:
        assert classify_by_keywords("Yes please send me more info") == ResponseCategory.INTERESTED

    def test_objection_reply(self) -> None:
        assert (
            classify_by_keywords("No thanks, I already have an agent")
            == ResponseCategory.OBJECTION
        )

    def test_question_reply(self) -> None:
        assert classify_by_keywords("How much is my home worth?") == ResponseCategory.QUESTION

    def test_not_now_reply(self) -> None:
        assert classify_by_keywords("Maybe later, check back next year") == ResponseCategory.NOT_NOW

    def test_wrong_person_reply(self) -> None:
        assert classify_by_keywords("Sorry wrong number") == ResponseCategory.WRONG_PERSON

    def test_opt_out_reply(self) -> None:
        assert classify_by_keywords("Please STOP texting me") == ResponseCategory.OPT_OUT

    def test_angry_reply(self) -> None:
        assert classify_by_keywords("This is harassment and I will sue") == ResponseCategory.ANGRY

    def test_booked_reply(self) -> None:
        assert classify_by_keywords("Can we schedule a call?") == ResponseCategory.BOOKED


class TestCampaignReplyStatusUpdates:
    """Campaign contact status updates match classified reply intent."""

    def test_interested_reply_qualifies_contact(self) -> None:
        campaign, campaign_contact = _campaign_contact()
        now = datetime.now(UTC)

        _update_campaign_contact(campaign_contact, campaign, ResponseCategory.INTERESTED, now)

        assert campaign.replies_received == 1
        assert campaign.contacts_qualified == 1
        assert campaign_contact.status == CampaignContactStatus.QUALIFIED
        assert campaign_contact.is_qualified is True
        assert campaign_contact.qualified_at == now
        assert campaign_contact.messages_received == 1
        assert campaign_contact.next_follow_up_at is None

    def test_opt_out_reply_opts_out_contact(self) -> None:
        campaign, campaign_contact = _campaign_contact()
        now = datetime.now(UTC)

        _update_campaign_contact(campaign_contact, campaign, ResponseCategory.OPT_OUT, now)

        assert campaign.replies_received == 1
        assert campaign.contacts_opted_out == 1
        assert campaign_contact.status == CampaignContactStatus.OPTED_OUT
        assert campaign_contact.opted_out is True
        assert campaign_contact.opted_out_at == now

    def test_question_reply_marks_replied_without_qualification(self) -> None:
        campaign, campaign_contact = _campaign_contact()
        now = datetime.now(UTC)

        _update_campaign_contact(campaign_contact, campaign, ResponseCategory.QUESTION, now)

        assert campaign.replies_received == 1
        assert campaign.contacts_qualified == 0
        assert campaign_contact.status == CampaignContactStatus.REPLIED
        assert campaign_contact.is_qualified is None or campaign_contact.is_qualified is False

    def test_booked_reply_counts_appointment(self) -> None:
        campaign, campaign_contact = _campaign_contact()
        now = datetime.now(UTC)

        _update_campaign_contact(campaign_contact, campaign, ResponseCategory.BOOKED, now)

        assert campaign.appointments_booked == 1
        assert campaign.contacts_qualified == 1
        assert campaign_contact.status == CampaignContactStatus.QUALIFIED

    def test_handoff_recommendations_cover_required_categories(self) -> None:
        for category in (
            ResponseCategory.INTERESTED,
            ResponseCategory.OBJECTION,
            ResponseCategory.QUESTION,
            ResponseCategory.NOT_NOW,
            ResponseCategory.WRONG_PERSON,
            ResponseCategory.OPT_OUT,
            ResponseCategory.ANGRY,
            ResponseCategory.BOOKED,
            ResponseCategory.HUMAN_NEEDED,
        ):
            assert _recommended_action(category)
