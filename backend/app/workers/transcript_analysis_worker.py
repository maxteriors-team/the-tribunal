"""Transcript analysis worker.

Polls voice call messages with a transcript but no sentiment analysis,
runs them through the transcript analysis service, and merges results
into the linked CallOutcome.signals dict.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.call_outcome import CallOutcome
from app.models.conversation import Message
from app.services.ai.transcript_analysis import analyze_transcript
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

BATCH_SIZE = 10


class TranscriptAnalysisWorker(RetryableWorker, BaseWorker):
    """Background worker that analyzes voice call transcripts."""

    POLL_INTERVAL_SECONDS = 30
    COMPONENT_NAME = "transcript_analysis_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        await self.execute_with_retry(
            self._process_batch, item_key="transcript_batch"
        )

    async def _process_batch(self) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message)
                .join(CallOutcome, CallOutcome.message_id == Message.id)
                .options(selectinload(Message.call_outcome))
                .where(
                    Message.channel == "voice",
                    Message.transcript.is_not(None),
                    CallOutcome.signals["analyzed"].astext.is_(None),
                )
                .limit(BATCH_SIZE)
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
                if isinstance(analysis, BaseException):
                    log.exception(
                        "transcript_analysis_failed", exc_info=analysis
                    )
                    current["analyzed"] = "error"
                else:
                    current.update(analysis)
                    current["analyzed"] = True
                    log.info(
                        "transcript_analyzed", sentiment=analysis.get("sentiment")
                    )
                outcome.signals = current

            await db.commit()


_registry = WorkerRegistry(TranscriptAnalysisWorker)
start_transcript_analysis_worker = _registry.start
stop_transcript_analysis_worker = _registry.stop
get_transcript_analysis_worker = _registry.get
