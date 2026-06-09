"""Business logic for the Reviews & Reputation engine.

Covers the full lifecycle:

* per-workspace reputation settings (stored in ``workspace.settings``)
* creating + dispatching review-request SMS (with opt-out + from-number rules,
  reusing the Telnyx send path and automatic short-link tracking)
* the public rating gate (high → public review URL, low → private feedback)
* aggregate reputation metrics for the dashboard

The service is deliberately framework-light: it raises ``HTTPException`` only
for genuine request errors and otherwise returns plain data so both the
authenticated router and the no-auth public router can share it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.review import (
    Review,
    ReviewSentiment,
    ReviewSource,
    ReviewStatus,
)
from app.models.review_request import (
    ReviewRequest,
    ReviewRequestChannel,
    ReviewRequestStatus,
)
from app.models.workspace import Workspace
from app.schemas.review import (
    PaginatedReviewRequests,
    PaginatedReviews,
    PublicRatingResult,
    PublicReviewRequest,
    RatingBucket,
    ReputationSummary,
    ReviewRequestResponse,
    ReviewRequestSendResult,
    ReviewRequestStatusSchema,
    ReviewResponse,
    ReviewSettings,
)
from app.services.automations.events import (
    EVENT_REVIEW_RECEIVED,
    EVENT_REVIEW_REQUEST_RESPONSE,
    emit_automation_event,
)
from app.services.calendar.reminder_service import resolve_from_number
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()

_SETTINGS_KEY = "review_settings"

_DEFAULT_TEMPLATE = (
    "Hi {first_name}, thanks for choosing {business_name}! "
    "How did we do? Tap to leave a quick rating: {link}"
)


def _sentiment_for_rating(rating: int) -> ReviewSentiment:
    """Bucket a 1-5 rating into a coarse sentiment."""
    if rating >= 4:
        return ReviewSentiment.POSITIVE
    if rating <= 2:
        return ReviewSentiment.NEGATIVE
    return ReviewSentiment.NEUTRAL


def _public_review_url(review_settings: ReviewSettings) -> str | None:
    """Return the configured public review destination, preferring Google."""
    return review_settings.google_review_url or review_settings.facebook_review_url


class ReviewService:
    """Service for review requests, reviews, the rating gate, and reputation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="review_service")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_settings(self, workspace: Workspace) -> ReviewSettings:
        """Return reputation settings for a workspace (defaults when unset)."""
        raw = (workspace.settings or {}).get(_SETTINGS_KEY, {})
        review_settings = ReviewSettings(**raw)
        if not review_settings.business_name:
            review_settings.business_name = workspace.name
        return review_settings

    async def update_settings(
        self,
        workspace: Workspace,
        update_data: dict[str, Any],
    ) -> ReviewSettings:
        """Merge a partial update into workspace reputation settings."""
        current = dict(workspace.settings or {})
        review_settings = dict(current.get(_SETTINGS_KEY, {}))
        review_settings.update(update_data)
        current[_SETTINGS_KEY] = review_settings
        workspace.settings = current
        await self.db.commit()
        await self.db.refresh(workspace)
        return self.get_settings(workspace)

    # ------------------------------------------------------------------
    # Review requests
    # ------------------------------------------------------------------

    async def list_requests(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
    ) -> PaginatedReviewRequests:
        """List review requests for a workspace."""
        query = (
            apply_workspace_scope(select(ReviewRequest), ReviewRequest, workspace_id)
            .options(selectinload(ReviewRequest.contact))
            .order_by(ReviewRequest.created_at.desc())
        )
        if status_filter:
            query = query.where(ReviewRequest.status == status_filter)

        result = await paginate(self.db, query, page=page, page_size=page_size, unique=True)
        return PaginatedReviewRequests(
            items=[self._request_to_response(r) for r in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )

    async def enqueue_for_appointment(
        self,
        appointment: Appointment,
    ) -> ReviewRequest | None:
        """Create a PENDING review request for a completed appointment.

        Idempotent: returns ``None`` when the workspace has the engine or the
        auto-trigger disabled, or when a review request already exists for this
        appointment. The actual SMS is dispatched later by the review-request
        worker once ``request_delay_minutes`` has elapsed, so happy customers
        aren't texted the instant a meeting ends.
        """
        log = self.log.bind(appointment_id=appointment.id)
        workspace = await self._load_workspace(appointment.workspace_id)
        review_settings = self.get_settings(workspace)
        if not review_settings.enabled or not review_settings.auto_request_on_completion:
            return None

        existing = await self.db.execute(
            select(ReviewRequest).where(
                ReviewRequest.appointment_id == appointment.id,
                ReviewRequest.workspace_id == workspace.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            log.info("review_request_already_exists")
            return None

        contact = await self._load_contact_optional(workspace.id, appointment.contact_id)
        if contact is None or not contact.phone_number:
            log.info("review_request_skipped_no_contact_phone")
            return None

        review_request = ReviewRequest(
            workspace_id=workspace.id,
            contact_id=appointment.contact_id,
            appointment_id=appointment.id,
            agent_id=appointment.agent_id,
            channel=ReviewRequestChannel.SMS,
            status=ReviewRequestStatus.PENDING,
        )
        self.db.add(review_request)
        await self.db.commit()
        await self.db.refresh(review_request)
        log.info("review_request_enqueued", review_request_id=str(review_request.id))
        return review_request

    async def find_due_pending_requests(
        self,
        limit: int,
    ) -> list[tuple[ReviewRequest, Workspace, Contact]]:
        """Return PENDING requests whose configured send delay has elapsed.

        Joins each request to its workspace + contact and filters by the
        per-workspace ``request_delay_minutes`` measured from request creation.
        """
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(ReviewRequest, Workspace, Contact)
            .join(Workspace, ReviewRequest.workspace_id == Workspace.id)
            .join(Contact, ReviewRequest.contact_id == Contact.id)
            .where(ReviewRequest.status == ReviewRequestStatus.PENDING.value)
            .order_by(ReviewRequest.created_at)
            .limit(limit * 4)
        )
        due: list[tuple[ReviewRequest, Workspace, Contact]] = []
        for review_request, workspace, contact in result.all():
            review_settings = self.get_settings(workspace)
            if not review_settings.enabled:
                continue
            delay = timedelta(minutes=review_settings.request_delay_minutes)
            created = review_request.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created + delay <= now:
                due.append((review_request, workspace, contact))
            if len(due) >= limit:
                break
        return due

    async def create_request(
        self,
        workspace: Workspace,
        contact_id: int,
        appointment_id: int | None,
        send_now: bool,
    ) -> ReviewRequestSendResult:
        """Create a review request and optionally dispatch it immediately."""
        contact = await self._load_contact(workspace.id, contact_id)

        agent_id: uuid.UUID | None = None
        if appointment_id is not None:
            appointment = await self._load_appointment(workspace.id, appointment_id)
            agent_id = appointment.agent_id

        review_request = ReviewRequest(
            workspace_id=workspace.id,
            contact_id=contact.id,
            appointment_id=appointment_id,
            agent_id=agent_id,
            channel=ReviewRequestChannel.SMS,
            status=ReviewRequestStatus.PENDING,
        )
        self.db.add(review_request)
        await self.db.flush()

        if not send_now:
            await self.db.commit()
            await self.db.refresh(review_request)
            return ReviewRequestSendResult(
                success=True,
                review_request_id=review_request.id,
                status=ReviewRequestStatusSchema.PENDING,
                message="Review request created (not sent).",
            )

        return await self.dispatch_request(workspace, review_request, contact)

    async def dispatch_request(
        self,
        workspace: Workspace,
        review_request: ReviewRequest,
        contact: Contact,
    ) -> ReviewRequestSendResult:
        """Send the review-request SMS, honoring opt-out + from-number rules.

        Never raises on SMS-level problems — records the failure on the request
        and returns a structured result so callers (API + webhook trigger) stay
        resilient.
        """
        log = self.log.bind(review_request_id=str(review_request.id), contact_id=contact.id)
        review_settings = self.get_settings(workspace)

        telnyx_key = settings.telnyx_api_key
        if not telnyx_key:
            return await self._fail_request(
                review_request, "Telnyx not configured", log, "telnyx_not_configured"
            )

        if not contact.phone_number:
            return await self._fail_request(
                review_request, "Contact has no phone number", log, "no_phone"
            )

        opt_out_manager = OptOutManager()
        is_opted_out = await opt_out_manager.check_opt_out(
            workspace.id, contact.phone_number, self.db
        )
        if is_opted_out:
            return await self._fail_request(
                review_request, "Contact has opted out", log, "opted_out"
            )

        from_number = await resolve_from_number(
            self.db, contact.id, workspace.id, review_request.agent_id
        )
        if not from_number:
            return await self._fail_request(
                review_request, "No available from-number", log, "no_from_number"
            )

        body = self._render_request_body(review_settings, contact, review_request.token)

        sms_service = TelnyxSMSService(telnyx_key)
        try:
            idempotency_key = derive_outbound_key("review_request", review_request.id)
            message = await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=from_number,
                body=body,
                db=self.db,
                workspace_id=workspace.id,
                agent_id=review_request.agent_id,
                idempotency_key=idempotency_key,
            )
            review_request.message_id = message.id
            review_request.status = ReviewRequestStatus.SENT
            review_request.sent_at = datetime.now(UTC)
            review_request.error = None
            await self.db.commit()
            await self.db.refresh(review_request)
            log.info("review_request_sent", message_id=str(message.id))
            return ReviewRequestSendResult(
                success=True,
                review_request_id=review_request.id,
                status=ReviewRequestStatusSchema.SENT,
                message="Review request sent.",
            )
        except Exception as exc:  # noqa: BLE001 — resilient send path
            log.exception("review_request_send_failed", error=str(exc))
            return await self._fail_request(review_request, str(exc), log, "send_exception")
        finally:
            await sms_service.close()

    async def _fail_request(
        self,
        review_request: ReviewRequest,
        detail: str,
        log: Any,
        reason: str,
    ) -> ReviewRequestSendResult:
        """Mark a review request failed and persist the reason."""
        review_request.status = ReviewRequestStatus.FAILED
        review_request.error = detail
        await self.db.commit()
        await self.db.refresh(review_request)
        log.info("review_request_not_sent", reason=reason)
        return ReviewRequestSendResult(
            success=False,
            review_request_id=review_request.id,
            status=ReviewRequestStatusSchema.FAILED,
            message="Review request could not be sent.",
            detail=detail,
        )

    def _render_request_body(
        self,
        review_settings: ReviewSettings,
        contact: Contact,
        token: str,
    ) -> str:
        """Render the review-request SMS body with placeholders.

        The landing-page URL is included verbatim; the Telnyx send path rewrites
        it into a tracked short link automatically.
        """
        template = review_settings.request_message_template or _DEFAULT_TEMPLATE
        business_name = review_settings.business_name or "us"
        link = f"{settings.frontend_url.rstrip('/')}/p/reviews/{token}"
        replacements = {
            "{first_name}": contact.first_name or "there",
            "{business_name}": business_name,
            "{link}": link,
        }
        body = template
        for placeholder, value in replacements.items():
            body = body.replace(placeholder, value)
        # Guarantee the link is present even if a custom template omitted it.
        if link not in body:
            body = f"{body.rstrip()} {link}"
        return body

    # ------------------------------------------------------------------
    # Public rating gate
    # ------------------------------------------------------------------

    async def get_public_request(self, token: str) -> PublicReviewRequest:
        """Return public landing-page data for a review-request token."""
        review_request = await self._load_request_by_token(token)
        workspace = await self._load_workspace(review_request.workspace_id)
        review_settings = self.get_settings(workspace)
        contact = await self._load_contact(review_request.workspace_id, review_request.contact_id)

        # Mark the click the first time the page is opened.
        if review_request.status == ReviewRequestStatus.SENT:
            review_request.status = ReviewRequestStatus.CLICKED
            review_request.clicked_at = datetime.now(UTC)
            await self.db.commit()

        already_submitted = review_request.status in (
            ReviewRequestStatus.RATED,
            ReviewRequestStatus.COMPLETED,
        )
        return PublicReviewRequest(
            token=review_request.token,
            status=review_request.status,  # type: ignore[arg-type]
            rating=review_request.rating,
            business_name=review_settings.business_name,
            contact_first_name=contact.first_name,
            positive_threshold=review_settings.positive_threshold,
            already_submitted=already_submitted,
        )

    async def submit_rating(self, token: str, rating: int) -> PublicRatingResult:
        """Apply the rating gate for a recipient's star rating.

        High ratings (>= threshold) route to the public review URL; low ratings
        capture a private feedback row and surface the feedback form.
        """
        review_request = await self._load_request_by_token(token)
        workspace = await self._load_workspace(review_request.workspace_id)
        review_settings = self.get_settings(workspace)

        is_positive = rating >= review_settings.positive_threshold

        # Idempotent: if already rated, recompute routing from the stored rating
        # without creating duplicate reviews.
        if review_request.rating is None:
            review_request.rating = rating
            review_request.rated_at = datetime.now(UTC)
            review_request.status = (
                ReviewRequestStatus.COMPLETED if is_positive else ReviewRequestStatus.RATED
            )
            await self._upsert_review_for_request(
                workspace_id=workspace.id,
                review_request=review_request,
                rating=rating,
                is_public=is_positive,
            )
            # Fire automation triggers: a review/rating just came in.
            event_payload = {
                "rating": rating,
                "is_positive": is_positive,
                "review_request_id": str(review_request.id),
            }
            await emit_automation_event(
                self.db,
                workspace_id=workspace.id,
                event_type=EVENT_REVIEW_REQUEST_RESPONSE,
                contact_id=review_request.contact_id,
                payload=event_payload,
            )
            await emit_automation_event(
                self.db,
                workspace_id=workspace.id,
                event_type=EVENT_REVIEW_RECEIVED,
                contact_id=review_request.contact_id,
                payload=event_payload,
            )
            await self._notify_review(
                workspace=workspace,
                rating=rating,
                is_positive=is_positive,
                dedupe_key=str(review_request.id),
            )
            await self.db.commit()
        else:
            # Re-derive routing from the original rating.
            rating = review_request.rating
            is_positive = rating >= review_settings.positive_threshold

        redirect_url = _public_review_url(review_settings) if is_positive else None
        if is_positive:
            message = (
                "Thanks! Redirecting you to leave a public review."
                if redirect_url
                else "Thank you for the great rating!"
            )
            return PublicRatingResult(
                success=True,
                rating=rating,
                is_positive=True,
                redirect_url=redirect_url,
                show_feedback_form=False,
                message=message,
            )

        return PublicRatingResult(
            success=True,
            rating=rating,
            is_positive=False,
            redirect_url=None,
            show_feedback_form=True,
            message="Thanks for your honesty. Please tell us how we can do better.",
        )

    async def submit_feedback(
        self,
        token: str,
        body: str,
        reviewer_name: str | None,
    ) -> None:
        """Attach private feedback text to a low-rating review (firewall path)."""
        review_request = await self._load_request_by_token(token)

        review = await self._load_review_for_request(review_request.id)
        if review is None:
            # Defensive: rating step should have created it, but tolerate a
            # direct feedback submission by creating the private review now.
            rating = review_request.rating or 1
            review = await self._upsert_review_for_request(
                workspace_id=review_request.workspace_id,
                review_request=review_request,
                rating=rating,
                is_public=False,
            )

        review.body = body
        if reviewer_name:
            review.reviewer_name = reviewer_name
        review_request.status = ReviewRequestStatus.COMPLETED
        await self.db.commit()

    async def _upsert_review_for_request(
        self,
        workspace_id: uuid.UUID,
        review_request: ReviewRequest,
        rating: int,
        is_public: bool,
    ) -> Review:
        """Create (or return existing) Review tied to a review request."""
        existing = await self._load_review_for_request(review_request.id)
        if existing is not None:
            existing.rating = rating
            existing.is_public = is_public
            existing.sentiment = _sentiment_for_rating(rating)
            return existing

        contact = await self._load_contact_optional(workspace_id, review_request.contact_id)
        review = Review(
            workspace_id=workspace_id,
            contact_id=review_request.contact_id,
            review_request_id=review_request.id,
            rating=rating,
            source=ReviewSource.SMS_REQUEST,
            sentiment=_sentiment_for_rating(rating),
            status=ReviewStatus.NEW,
            is_public=is_public,
            reviewer_name=contact.first_name if contact else None,
        )
        self.db.add(review)
        await self.db.flush()
        return review

    # ------------------------------------------------------------------
    # Reviews (operator-facing)
    # ------------------------------------------------------------------

    async def list_reviews(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        is_public: bool | None = None,
        sentiment: str | None = None,
    ) -> PaginatedReviews:
        """List reviews for a workspace with optional filters."""
        query = (
            apply_workspace_scope(select(Review), Review, workspace_id)
            .options(selectinload(Review.contact))
            .order_by(Review.created_at.desc())
        )
        if status_filter:
            query = query.where(Review.status == status_filter)
        if is_public is not None:
            query = query.where(Review.is_public.is_(is_public))
        if sentiment:
            query = query.where(Review.sentiment == sentiment)

        result = await paginate(self.db, query, page=page, page_size=page_size, unique=True)
        return PaginatedReviews(
            items=[self._review_to_response(r) for r in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )

    async def get_review(self, workspace_id: uuid.UUID, review_id: uuid.UUID) -> Review:
        """Fetch a single review, scoped to the workspace."""
        result = await self.db.execute(
            apply_workspace_scope(
                select(Review).options(selectinload(Review.contact)),
                Review,
                workspace_id,
            ).where(Review.id == review_id)
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found",
            )
        return review

    async def create_review(
        self,
        workspace_id: uuid.UUID,
        rating: int,
        body: str | None,
        reviewer_name: str | None,
        contact_id: int | None,
        source: str,
        is_public: bool,
    ) -> Review:
        """Manually create a review (operator entry)."""
        review = Review(
            workspace_id=workspace_id,
            contact_id=contact_id,
            rating=rating,
            body=body,
            reviewer_name=reviewer_name,
            source=ReviewSource(source),
            sentiment=_sentiment_for_rating(rating),
            status=ReviewStatus.NEW,
            is_public=is_public,
        )
        self.db.add(review)
        await self.db.flush()
        await emit_automation_event(
            self.db,
            workspace_id=workspace_id,
            event_type=EVENT_REVIEW_RECEIVED,
            contact_id=contact_id,
            payload={"rating": rating, "source": source, "is_public": is_public},
        )
        workspace = await self._load_workspace(workspace_id)
        await self._notify_review(
            workspace=workspace,
            rating=rating,
            is_positive=rating >= 4,
            dedupe_key=str(review.id),
        )
        await self.db.commit()
        await self.db.refresh(review)
        return review

    async def _notify_review(
        self,
        *,
        workspace: Workspace,
        rating: int,
        is_positive: bool,
        dedupe_key: str,
    ) -> None:
        """Push + email workspace members about a new review/rating (best-effort)."""
        from app.services.notifications import notify_workspace_event

        business = workspace.name
        sentiment = "positive" if is_positive else "needs attention"
        title = f"New {rating}\u2605 review"
        body = f"{business} received a {rating}-star review ({sentiment})."
        try:
            await notify_workspace_event(
                self.db,
                workspace_id=workspace.id,
                notification_type="review",
                title=title,
                body=body,
                data={"type": "review", "rating": rating, "screen": "/(tabs)/reviews"},
                channel_id="reviews",
                email_subject=title,
                email_heading="New Review Received",
                email_intro=body,
                email_details={
                    "Rating": f"{rating} / 5",
                    "Sentiment": sentiment,
                    "Business": business,
                },
                dedupe_key=dedupe_key,
            )
        except Exception:
            self.log.warning("review_notification_failed", dedupe_key=dedupe_key)

    async def update_review(
        self,
        workspace_id: uuid.UUID,
        review_id: uuid.UUID,
        update_data: dict[str, Any],
    ) -> Review:
        """Update a review's triage state or reply draft."""
        review = await self.get_review(workspace_id, review_id)
        reply_sent = update_data.pop("reply_sent", None)
        for field, value in update_data.items():
            setattr(review, field, value)
        if reply_sent:
            review.reply_sent = True
            review.replied_at = datetime.now(UTC)
            if review.status == ReviewStatus.NEW:
                review.status = ReviewStatus.REPLIED
        await self.db.commit()
        await self.db.refresh(review)
        return review

    # ------------------------------------------------------------------
    # Reputation dashboard
    # ------------------------------------------------------------------

    async def get_summary(self, workspace_id: uuid.UUID) -> ReputationSummary:
        """Compute aggregate reputation metrics for the dashboard."""
        review_row = (
            await self.db.execute(
                apply_workspace_scope(
                    select(
                        func.count(Review.id),
                        func.coalesce(func.avg(Review.rating), 0.0),
                        func.count(Review.id).filter(Review.is_public.is_(True)),
                        func.count(Review.id).filter(Review.is_public.is_(False)),
                        func.count(Review.id).filter(Review.status == ReviewStatus.NEW.value),
                    ),
                    Review,
                    workspace_id,
                )
            )
        ).one()
        total_reviews = int(review_row[0] or 0)
        average_rating = round(float(review_row[1] or 0.0), 2)
        public_reviews = int(review_row[2] or 0)
        private_feedback = int(review_row[3] or 0)
        new_count = int(review_row[4] or 0)

        dist_rows = (
            await self.db.execute(
                apply_workspace_scope(
                    select(Review.rating, func.count(Review.id)),
                    Review,
                    workspace_id,
                ).group_by(Review.rating)
            )
        ).all()
        counts_by_rating = {int(r[0]): int(r[1]) for r in dist_rows}
        rating_distribution = [
            RatingBucket(rating=star, count=counts_by_rating.get(star, 0))
            for star in range(5, 0, -1)
        ]

        request_row = (
            await self.db.execute(
                apply_workspace_scope(
                    select(
                        func.count(ReviewRequest.id).filter(
                            ReviewRequest.status.in_(
                                [
                                    ReviewRequestStatus.SENT.value,
                                    ReviewRequestStatus.CLICKED.value,
                                    ReviewRequestStatus.RATED.value,
                                    ReviewRequestStatus.COMPLETED.value,
                                ]
                            )
                        ),
                        func.count(ReviewRequest.id).filter(ReviewRequest.rating.is_not(None)),
                    ),
                    ReviewRequest,
                    workspace_id,
                )
            )
        ).one()
        requests_sent = int(request_row[0] or 0)
        requests_rated = int(request_row[1] or 0)
        response_rate = round(requests_rated / requests_sent * 100, 1) if requests_sent > 0 else 0.0

        return ReputationSummary(
            average_rating=average_rating,
            total_reviews=total_reviews,
            public_reviews=public_reviews,
            private_feedback=private_feedback,
            new_count=new_count,
            reputation_score=self._reputation_score(average_rating, total_reviews),
            rating_distribution=rating_distribution,
            requests_sent=requests_sent,
            requests_rated=requests_rated,
            response_rate=response_rate,
        )

    @staticmethod
    def _reputation_score(average_rating: float, total_reviews: int) -> int:
        """Map average rating + volume to a 0-100 reputation score.

        Base score scales the 1-5 average onto 0-100. A small volume penalty
        dampens scores for workspaces with very few reviews so a single 5-star
        rating doesn't read as a perfect reputation.
        """
        if total_reviews == 0:
            return 0
        base = (average_rating / 5.0) * 100.0
        # Confidence factor approaches 1.0 as volume grows (10 reviews ≈ 0.91).
        confidence = total_reviews / (total_reviews + 1.0)
        return round(base * confidence)

    # ------------------------------------------------------------------
    # Loaders + serialization
    # ------------------------------------------------------------------

    async def _load_contact(self, workspace_id: uuid.UUID, contact_id: int) -> Contact:
        contact = await self._load_contact_optional(workspace_id, contact_id)
        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )
        return contact

    async def _load_contact_optional(
        self, workspace_id: uuid.UUID, contact_id: int
    ) -> Contact | None:
        result = await self.db.execute(
            apply_workspace_scope(select(Contact), Contact, workspace_id).where(
                Contact.id == contact_id
            )
        )
        return result.scalar_one_or_none()

    async def _load_appointment(self, workspace_id: uuid.UUID, appointment_id: int) -> Appointment:
        result = await self.db.execute(
            apply_workspace_scope(select(Appointment), Appointment, workspace_id).where(
                Appointment.id == appointment_id
            )
        )
        appointment = result.scalar_one_or_none()
        if appointment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found",
            )
        return appointment

    async def _load_workspace(self, workspace_id: uuid.UUID) -> Workspace:
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found",
            )
        return workspace

    async def _load_request_by_token(self, token: str) -> ReviewRequest:
        result = await self.db.execute(select(ReviewRequest).where(ReviewRequest.token == token))
        review_request = result.scalar_one_or_none()
        if review_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review request not found",
            )
        return review_request

    async def _load_review_for_request(self, review_request_id: uuid.UUID) -> Review | None:
        result = await self.db.execute(
            select(Review).where(Review.review_request_id == review_request_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _review_to_response(review: Review) -> ReviewResponse:
        contact = review.contact if "contact" in review.__dict__ else None
        return ReviewResponse(
            id=review.id,
            workspace_id=review.workspace_id,
            contact_id=review.contact_id,
            review_request_id=review.review_request_id,
            rating=review.rating,
            body=review.body,
            reviewer_name=review.reviewer_name,
            source=review.source,  # type: ignore[arg-type]
            sentiment=review.sentiment,  # type: ignore[arg-type]
            status=review.status,  # type: ignore[arg-type]
            is_public=review.is_public,
            reply_draft=review.reply_draft,
            reply_sent=review.reply_sent,
            replied_at=review.replied_at,
            created_at=review.created_at,
            updated_at=review.updated_at,
            contact_name=contact.full_name if contact else None,
        )

    @staticmethod
    def _request_to_response(review_request: ReviewRequest) -> ReviewRequestResponse:
        contact = review_request.contact if "contact" in review_request.__dict__ else None
        return ReviewRequestResponse(
            id=review_request.id,
            workspace_id=review_request.workspace_id,
            contact_id=review_request.contact_id,
            appointment_id=review_request.appointment_id,
            agent_id=review_request.agent_id,
            token=review_request.token,
            channel=review_request.channel,
            status=review_request.status,  # type: ignore[arg-type]
            rating=review_request.rating,
            sent_at=review_request.sent_at,
            clicked_at=review_request.clicked_at,
            rated_at=review_request.rated_at,
            error=review_request.error,
            created_at=review_request.created_at,
            updated_at=review_request.updated_at,
            contact_name=contact.full_name if contact else None,
        )
