"""Transcript analysis worker.

Polls voice call messages with a transcript but no sentiment analysis,
runs them through the transcript analysis service, and merges results
into the linked CallOutcome.signals dict.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import system_session
from app.models.call_outcome import CallOutcome
from app.models.conversation import Message
from app.services.ai.contact_ai_memory_service import (
    refresh_contact_ai_memory_from_voice_analysis,
)
from app.services.ai.transcript_analysis import analyze_transcript
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

BATCH_SIZE = 10


class TranscriptAnalysisWorker(RetryableWorker, BaseWorker):
    """Background worker that analyzes voice call transcripts."""

    POLL_INTERVAL_SECONDS = 30
    COMPONENT_NAME = "transcript_analysis_worker"
    # Each cycle pulls up to BATCH_SIZE messages and runs them through the
    # transcript analysis service concurrently; cap matches BATCH_SIZE so a
    # full batch can fan out without bursting beyond the OpenAI rate budget.
    MAX_CONCURRENCY = BATCH_SIZE
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        await self.execute_with_retry(self._process_batch, item_key="transcript_batch")

    async def _process_batch(self) -> None:
        async with system_session("transcript_analysis_worker sweeps every workspace") as db:
            # Claim the ``CallOutcome`` rows this batch will write back to,
            # ``SKIP LOCKED`` so a second replica takes a different batch instead
            # of paying OpenAI twice to analyze the same transcripts. ``of=`` keeps
            # the lock off ``messages``, which is only read here.
            result = await db.execute(
                select(Message)
                .join(CallOutcome, CallOutcome.message_id == Message.id)
                .options(
                    selectinload(Message.call_outcome),
                    selectinload(Message.conversation),
                )
                .where(
                    Message.channel == "voice",
                    Message.transcript.is_not(None),
                    CallOutcome.signals["analyzed"].astext.is_(None),
                )
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True, of=CallOutcome)
            )
            items: list[tuple[Message, CallOutcome, str]] = [
                (m, m.call_outcome, m.transcript)
                for m in result.scalars().all()
                if m.call_outcome is not None and m.transcript
            ]

            if not items:
                return

            self.logger.info("transcript_analysis_batch", count=len(items))

            analyses = await asyncio.gather(
                *(analyze_transcript(transcript) for _, _, transcript in items),
                return_exceptions=True,
            )

            for (msg, outcome, _), analysis in zip(items, analyses, strict=True):
                log = self.logger.bind(message_id=str(msg.id))
                current: dict[str, object] = dict(outcome.signals or {})
                memory_analysis: dict[str, object] = {}
                if isinstance(analysis, BaseException):
                    log.error(
                        "transcript_analysis_failed",
                        error_type=type(analysis).__name__,
                    )
                    current["analyzed"] = "error"
                else:
                    current.update(analysis)
                    current["analyzed"] = True
                    memory_analysis.update(analysis)
                    log.info("transcript_analyzed", sentiment=analysis.get("sentiment"))
                memory_analysis["call_outcome"] = str(
                    getattr(outcome.outcome_type, "value", outcome.outcome_type)
                )
                try:
                    async with db.begin_nested():
                        await refresh_contact_ai_memory_from_voice_analysis(
                            db,
                            workspace_id=msg.conversation.workspace_id,
                            message_id=msg.id,
                            analysis=memory_analysis,
                            provenance_event_id=f"call-outcome:{outcome.id}",
                        )
                except Exception as exc:  # noqa: BLE001 - outcome must still persist
                    log.warning(
                        "contact_ai_memory_voice_refresh_failed",
                        outcome_id=str(outcome.id),
                        error_type=type(exc).__name__,
                    )
                outcome.signals = current

            await db.commit()


_registry = WorkerRegistry(TranscriptAnalysisWorker)
start_transcript_analysis_worker = _registry.start
stop_transcript_analysis_worker = _registry.stop
get_transcript_analysis_worker = _registry.get
