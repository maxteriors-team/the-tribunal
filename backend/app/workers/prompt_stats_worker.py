"""Prompt stats aggregation worker.

Aggregates daily statistics from CallOutcome records into PromptVersionStats
for efficient dashboard queries and trend analysis.
"""

from datetime import date, timedelta

from sqlalchemy import Date, Numeric, and_, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.call_outcome import CallOutcome, OutcomeType
from app.models.prompt_version_stats import PromptVersionStats
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class PromptStatsWorker(RetryableWorker, BaseWorker):
    """Aggregates daily stats for prompt versions.

    Runs hourly to aggregate yesterday's call outcomes into
    PromptVersionStats records for efficient querying.
    """

    POLL_INTERVAL_SECONDS = 3600  # Hourly
    COMPONENT_NAME = "prompt_stats"
    # Single daily aggregation per cycle — no parallel fan-out.
    MAX_CONCURRENCY = 1
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Process daily aggregation for all prompt versions."""
        async with AsyncSessionLocal() as db:
            # Aggregate yesterday's data by default
            yesterday = date.today() - timedelta(days=1)
            await self.execute_with_retry(
                self._aggregate_and_commit,
                db,
                yesterday,
                item_key=f"aggregate:{yesterday.isoformat()}",
            )

    async def _aggregate_and_commit(self, db: AsyncSession, stat_date: date) -> int:
        """Aggregate for a date and commit; raises on failure to trigger retry."""
        processed = await self._aggregate_for_date(db, stat_date)
        await db.commit()
        return processed

    async def _aggregate_for_date(
        self,
        db: AsyncSession,
        stat_date: date,
    ) -> int:
        """Aggregate stats for a specific date.

        Args:
            db: Database session
            stat_date: Date to aggregate

        Returns:
            Number of versions processed
        """
        log = self.logger.bind(stat_date=str(stat_date))
        log.info("Starting stats aggregation")

        # Get all prompt versions with outcomes on this date
        # Group by prompt_version_id and aggregate
        aggregation_query = (
            select(
                CallOutcome.prompt_version_id,
                func.count(CallOutcome.id).label("total_calls"),
                func.count(CallOutcome.id)
                .filter(
                    CallOutcome.outcome_type.in_(
                        [
                            OutcomeType.COMPLETED.value,
                            OutcomeType.APPOINTMENT_BOOKED.value,
                            OutcomeType.LEAD_QUALIFIED.value,
                        ]
                    )
                )
                .label("completed_calls"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.FAILED.value)
                .label("failed_calls"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.APPOINTMENT_BOOKED.value)
                .label("appointments_booked"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.LEAD_QUALIFIED.value)
                .label("leads_qualified"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.NO_ANSWER.value)
                .label("no_answer_count"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.REJECTED.value)
                .label("rejected_count"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.outcome_type == OutcomeType.VOICEMAIL.value)
                .label("voicemail_count"),
                # Duration from signals JSON
                func.avg(
                    cast(
                        CallOutcome.signals["duration_seconds"].astext,
                        Numeric,
                    )
                ).label("avg_duration"),
                func.sum(
                    cast(
                        func.coalesce(CallOutcome.signals["duration_seconds"].astext, "0"),
                        Numeric,
                    )
                ).label("total_duration"),
                # Quality score from signals
                func.avg(
                    cast(
                        CallOutcome.signals["quality_score"].astext,
                        Numeric,
                    )
                ).label("avg_quality"),
                func.count(CallOutcome.id)
                .filter(CallOutcome.signals["quality_score"].isnot(None))
                .label("feedback_count"),
                func.count(CallOutcome.id)
                .filter(cast(CallOutcome.signals["quality_score"].astext, Numeric) >= 4)
                .label("positive_feedback_count"),
            )
            .where(
                and_(
                    CallOutcome.prompt_version_id.isnot(None),
                    cast(CallOutcome.created_at, Date) == stat_date,
                )
            )
            .group_by(CallOutcome.prompt_version_id)
        )

        result = await db.execute(aggregation_query)
        rows = result.all()

        if not rows:
            log.debug("No outcomes found for date")
            return 0

        processed = 0
        for row in rows:
            if row.prompt_version_id is None:
                continue

            total = row.total_calls or 0
            completed = row.completed_calls or 0
            appointments = row.appointments_booked or 0

            # Compute rates
            booking_rate = (appointments / completed) if completed > 0 else None
            qual_rate = (row.leads_qualified or 0) / completed if completed > 0 else None
            completion_rate = completed / total if total > 0 else None

            # Upsert stats record
            stmt = insert(PromptVersionStats).values(
                prompt_version_id=row.prompt_version_id,
                stat_date=stat_date,
                total_calls=total,
                completed_calls=completed,
                failed_calls=row.failed_calls or 0,
                appointments_booked=appointments,
                leads_qualified=row.leads_qualified or 0,
                no_answer_count=row.no_answer_count or 0,
                rejected_count=row.rejected_count or 0,
                voicemail_count=row.voicemail_count or 0,
                avg_duration_seconds=float(row.avg_duration) if row.avg_duration else None,
                total_duration_seconds=int(row.total_duration or 0),
                avg_quality_score=float(row.avg_quality) if row.avg_quality else None,
                feedback_count=row.feedback_count or 0,
                positive_feedback_count=row.positive_feedback_count or 0,
                booking_rate=booking_rate,
                qualification_rate=qual_rate,
                completion_rate=completion_rate,
            )

            # On conflict, update existing record
            stmt = stmt.on_conflict_do_update(
                constraint="uq_prompt_version_stats_date",
                set_={
                    "total_calls": stmt.excluded.total_calls,
                    "completed_calls": stmt.excluded.completed_calls,
                    "failed_calls": stmt.excluded.failed_calls,
                    "appointments_booked": stmt.excluded.appointments_booked,
                    "leads_qualified": stmt.excluded.leads_qualified,
                    "no_answer_count": stmt.excluded.no_answer_count,
                    "rejected_count": stmt.excluded.rejected_count,
                    "voicemail_count": stmt.excluded.voicemail_count,
                    "avg_duration_seconds": stmt.excluded.avg_duration_seconds,
                    "total_duration_seconds": stmt.excluded.total_duration_seconds,
                    "avg_quality_score": stmt.excluded.avg_quality_score,
                    "feedback_count": stmt.excluded.feedback_count,
                    "positive_feedback_count": stmt.excluded.positive_feedback_count,
                    "booking_rate": stmt.excluded.booking_rate,
                    "qualification_rate": stmt.excluded.qualification_rate,
                    "completion_rate": stmt.excluded.completion_rate,
                },
            )

            await db.execute(stmt)
            processed += 1

        log.info("Stats aggregation complete", versions_processed=processed)
        return processed

    async def backfill(
        self,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        """Backfill stats for a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive, defaults to yesterday)

        Returns:
            Total number of stats records created/updated
        """
        if end_date is None:
            end_date = date.today() - timedelta(days=1)

        self.logger.info(
            "Starting backfill",
            start_date=str(start_date),
            end_date=str(end_date),
        )

        total_processed = 0
        current_date = start_date

        async with AsyncSessionLocal() as db:
            while current_date <= end_date:
                processed = await self._aggregate_for_date(db, current_date)
                total_processed += processed
                current_date += timedelta(days=1)

            await db.commit()

        self.logger.info("Backfill complete", total_processed=total_processed)
        return total_processed


# Singleton registry
_registry = WorkerRegistry(PromptStatsWorker)
start_prompt_stats_worker = _registry.start
stop_prompt_stats_worker = _registry.stop
get_prompt_stats_worker = _registry.get
