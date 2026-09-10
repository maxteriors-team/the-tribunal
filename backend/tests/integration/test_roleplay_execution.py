"""No-spend F02/F03 proofs against a migrated, disposable local Postgres database.

Run with ROLEPLAY_TEST_DATABASE_URL pointing to a local database whose name
starts roleplay_test_, then pytest -m integration tests/integration/test_roleplay_execution.py.
All model calls use the real OpenAI SDK over httpx.MockTransport; notifications
are captured, never delivered. No application-wide workers are started.
"""

import asyncio
import json
import os
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.v1.roleplay import router
from app.db.tenancy import mark_session_as_system
from app.models.agent import Agent
from app.models.automation import Automation
from app.models.automation_event import AutomationEvent
from app.models.roleplay import ProspectPersona, RehearsalRun, RehearsalStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.ai.roleplay import execution
from app.services.ai.roleplay.roleplay_service import RoleplayService
from app.services.exceptions import ValidationError
from app.workers.roleplay_worker import RoleplayWorker

pytestmark = pytest.mark.integration

GRADE = {
    "overall_score": 0,
    "objection_coverage_score": 0,
    "tone_score": 0,
    "booking_attempted": False,
    "summary": "The rep met none of the rubric goals.",
}


class ControlledProvider:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.failure: tuple[str, int | str] | None = None
        self.delay = 0.0
        self.entered = asyncio.Event()

    async def respond(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        step = (
            "score"
            if "response_format" in payload
            else (
                "prospect"
                if payload["messages"][0]["content"] == "CONTROLLED_PROSPECT"
                else "agent"
            )
        )
        self.calls[step] += 1
        self.entered.set()
        if self.delay:
            await asyncio.sleep(self.delay)  # Deliberate provider latency, not a process wait.
        content = json.dumps(GRADE) if step == "score" else f"Genuine {step} reply"
        if self.failure and self.failure[0] == step:
            fault = self.failure[1]
            if isinstance(fault, int):
                return httpx.Response(fault, json={"error": {"message": "controlled rejection"}})
            if fault == "connection":
                raise httpx.ReadError("controlled lost response")
            content = fault
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-controlled",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    async def client(self, db: AsyncSession, workspace_id: uuid.UUID) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="controlled-no-spend",  # Not a credential; MockTransport never opens a socket.
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.respond)),
        )


@dataclass
class Harness:
    sessions: async_sessionmaker[AsyncSession]
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    agent_id: uuid.UUID
    persona_id: uuid.UUID
    user: User
    provider: ControlledProvider
    notifications: AsyncMock

    @asynccontextmanager
    async def db(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as db:
            mark_session_as_system(db, reason="isolated roleplay execution tests")
            yield db

    async def create(self, **overrides: object) -> RehearsalRun:
        async with self.db() as db:
            # Request validation is exercised through the real schema below.
            from app.schemas.roleplay import CreateRehearsalRequest

            data = CreateRehearsalRequest.model_validate(
                {
                    "idempotency_key": uuid.uuid4(),
                    "agent_id": self.agent_id,
                    "persona_id": self.persona_id,
                    "max_turns": 1,
                    **overrides,
                }
            )
            return await RoleplayService(db).create_run(self.workspace_id, **data.model_dump())

    async def get(self, run_id: uuid.UUID) -> RehearsalRun:
        async with self.db() as db:
            return await RoleplayService(db).get_run(run_id, self.workspace_id)

    async def claim(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        async with self.db() as db:
            return await execution.claim_runs(db, 3)

    async def execute(self, claim: tuple[uuid.UUID, uuid.UUID]) -> None:
        async with self.db() as db:
            await execution.execute_step(db, *claim)

    async def drain(self) -> None:
        for _ in range(30):
            claims = await self.claim()
            if not claims:
                return
            await asyncio.gather(*(self.execute(claim) for claim in claims))
        raise AssertionError("Rehearsal did not reach a terminal/idle state")

    async def events(self) -> int:
        async with self.db() as db:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(AutomationEvent)
                    .where(
                        AutomationEvent.workspace_id == self.workspace_id,
                    )
                )
                or 0
            )

    def app(self) -> FastAPI:
        app = FastAPI()

        async def session() -> AsyncIterator[AsyncSession]:
            async with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = session
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.include_router(router, prefix="/api/v1/workspaces/{workspace_id}/roleplay")
        return app


async def seed_harness(sessions: async_sessionmaker[AsyncSession]) -> Harness:
    async with sessions() as db:
        mark_session_as_system(db, reason="seed isolated roleplay test data")
        workspace = Workspace(name="Roleplay fixture", slug=f"rp-{uuid.uuid4().hex}")
        other = Workspace(name="Other fixture", slug=f"rp-{uuid.uuid4().hex}")
        user = User(email=f"{uuid.uuid4()}@example.invalid", hashed_password="not-a-login")
        db.add_all([workspace, other, user])
        await db.flush()
        agent = Agent(workspace_id=workspace.id, name="Fixture rep", system_prompt="Fixture prompt")
        persona = ProspectPersona(
            workspace_id=workspace.id,
            name="Fixture prospect",
            slug=uuid.uuid4().hex,
            persona_prompt="CONTROLLED_PROSPECT",
            opening_message="Who is this?",
        )
        db.add_all(
            [
                agent,
                persona,
                WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"),
                Automation(
                    workspace_id=workspace.id,
                    name="Completion listener",
                    trigger_type="roleplay_completed",
                ),
            ]
        )
        await db.commit()
        return Harness(
            sessions,
            workspace.id,
            other.id,
            agent.id,
            persona.id,
            user,
            ControlledProvider(),
            AsyncMock(),
        )


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    url = os.environ.get("ROLEPLAY_TEST_DATABASE_URL")
    assert url, "Set ROLEPLAY_TEST_DATABASE_URL to a migrated disposable local Postgres database"
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert (parsed.database or "").startswith("roleplay_test_")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fixture = await seed_harness(sessions)
    monkeypatch.setattr(execution, "create_workspace_openai_client", fixture.provider.client)
    monkeypatch.setattr("app.services.notifications.notify_workspace_event", fixture.notifications)
    try:
        yield fixture
    finally:
        async with fixture.db() as db:
            await db.execute(
                delete(Workspace).where(
                    Workspace.id.in_([fixture.workspace_id, fixture.other_workspace_id])
                )
            )
            await db.execute(delete(User).where(User.id == fixture.user.id))
            await db.commit()
        await engine.dispose()


async def test_http_identity_survives_31_second_provider_and_duplicate_delivery(
    harness: Harness,
) -> None:
    harness.provider.delay = 31.0
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "agent_id": str(harness.agent_id),
        "persona_id": str(harness.persona_id),
        "max_turns": 1,
    }
    path = f"/api/v1/workspaces/{harness.workspace_id}/roleplay/runs"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()), base_url="http://test"
    ) as client:
        started = time.monotonic()
        response = await asyncio.wait_for(client.post(path, json=body), timeout=2)
        assert response.status_code == 202, response.text
        assert time.monotonic() - started < 2
        run_id = uuid.UUID(response.json()["id"])
        assert response.json()["status"] == "pending"
        assert response.json()["overall_score"] is None
        assert not harness.provider.calls
        claim = (await harness.claim())[0]
        task = asyncio.create_task(harness.execute(claim))
        try:
            await asyncio.wait_for(harness.provider.entered.wait(), 2)
            repeat = await client.post(path, json=body)
            assert repeat.json()["id"] == str(run_id)
            assert (await client.get(f"{path}/{run_id}")).json()["status"] == "running"
            await harness.execute(claim)  # Duplicate internal delivery consumes no second call.
            assert await harness.claim() == []
            await asyncio.wait_for(task, 35)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert time.monotonic() - started >= 30
        assert harness.provider.calls == {"agent": 1}
        harness.provider.delay = 0
        await harness.drain()
        report = (await client.get(f"{path}/{run_id}")).json()
        assert report["status"] == "completed"
        assert report["overall_score"] == 0
        assert len(report["transcript"]) == 3
        assert harness.provider.calls == {"agent": 1, "prospect": 1, "score": 1}
        assert await harness.events() == 1
        harness.notifications.assert_awaited_once()
        assert (await client.post(path, json=body)).json()["id"] == str(run_id)
        assert (await client.post(f"{path}/{run_id}/score")).json()["status"] == "completed"
        assert await harness.claim() == []
        assert await harness.events() == 1


@pytest.mark.parametrize(
    "step,fault",
    [
        ("agent", 429),
        ("prospect", 503),
        ("prospect", ""),
        ("score", 503),
        ("score", "not json"),
        ("score", "{}"),
        ("score", "connection"),
    ],
)
async def test_provider_failures_are_unscored_without_completion_side_effects(
    harness: Harness,
    step: str,
    fault: int | str,
) -> None:
    harness.provider.failure = (step, fault)
    run = await harness.create()
    await harness.drain()
    result = await harness.get(run.id)
    assert result.status == RehearsalStatus.FAILED
    assert result.pending_action == step
    assert result.overall_score is None and result.booking_attempted is None
    assert result.tone_score is None and result.objection_coverage is None
    assert result.scores == {} and result.summary is None
    assert result.error and "unscored" in result.error or result.error == execution.INTERRUPTED
    assert harness.provider.calls[step] == 1  # SDK auto-retries really are disabled.
    assert all(
        turn["content"] in {"Who is this?", "Genuine agent reply", "Genuine prospect reply"}
        for turn in result.transcript
    )
    assert len(result.transcript) == {"agent": 1, "prospect": 2, "score": 3}[step]
    assert await harness.events() == 0
    harness.notifications.assert_not_awaited()


async def test_failed_score_retry_resumes_only_score_and_old_retry_is_deduplicated(
    harness: Harness,
) -> None:
    harness.provider.failure = ("score", "invalid JSON")
    run = await harness.create()
    await harness.drain()
    failed = await harness.get(run.id)
    assert failed.retryable

    async def retry() -> RehearsalRun:
        async with harness.db() as db:
            return await RoleplayService(db).retry_run(
                run.id, harness.workspace_id, failed.attempt_count
            )

    await asyncio.gather(retry(), retry())
    await harness.drain()  # Second scoring attempt also fails.
    assert harness.provider.calls == {"agent": 1, "prospect": 1, "score": 2}
    await retry()  # A lost retry response cannot retry the newer failure.
    assert await harness.claim() == []
    harness.provider.failure = None
    current = await harness.get(run.id)
    async with harness.db() as db:
        await RoleplayService(db).retry_run(run.id, harness.workspace_id, current.attempt_count)
    await harness.drain()
    result = await harness.get(run.id)
    assert result.status == RehearsalStatus.COMPLETED and result.overall_score == 0
    assert result.transcript == failed.transcript
    assert harness.provider.calls == {"agent": 1, "prospect": 1, "score": 3}
    assert await harness.events() == 1
    harness.notifications.assert_awaited_once()


async def test_concurrent_creation_keys_conflicts_workspace_scope_and_deleted_identity(
    harness: Harness,
) -> None:
    key = uuid.uuid4()
    runs = await asyncio.gather(*(harness.create(idempotency_key=key) for _ in range(6)))
    assert len({run.id for run in runs}) == 1
    assert not harness.provider.calls
    with pytest.raises(ValidationError, match="different rehearsal settings"):
        await harness.create(idempotency_key=key, max_turns=2)
    first, second = await asyncio.gather(harness.claim(), harness.claim())
    assert len(first) + len(second) == 1
    await harness.execute((first + second)[0])
    await harness.drain()
    path = f"/api/v1/workspaces/{harness.other_workspace_id}/roleplay/runs/{runs[0].id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 404
        assert (
            await client.post(path + "/retry", json={"expected_attempt_count": 1})
        ).status_code == 404
    async with harness.db() as db:
        await RoleplayService(db).delete_run(runs[0].id, harness.workspace_id)
    with pytest.raises(ValidationError, match="deleted"):
        await harness.create(idempotency_key=key)
    assert harness.provider.calls == {"agent": 1, "prospect": 1, "score": 1}


async def test_human_turn_and_score_requests_are_queued_and_deduplicated(harness: Harness) -> None:
    run = await harness.create(rehearsee="human")
    assert run.status == RehearsalStatus.RUNNING and not harness.provider.calls
    path = f"/api/v1/workspaces/{harness.workspace_id}/roleplay/runs/{run.id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()), base_url="http://test"
    ) as client:
        body = {"message": "Here is my real reply", "expected_turn_count": 1}
        a, b = await asyncio.gather(*(client.post(path + "/turn", json=body) for _ in range(2)))
        assert a.status_code == b.status_code == 202
        assert len(a.json()["transcript"]) == 2
        assert not harness.provider.calls
        assert (await client.post(path + "/score")).status_code == 400
        await harness.drain()
        assert (await client.post(path + "/turn", json=body)).status_code == 202
        conflict = {**body, "message": "Different text"}
        assert (await client.post(path + "/turn", json=conflict)).status_code == 400
        assert harness.provider.calls == {"prospect": 1}
        a, b = await asyncio.gather(*(client.post(path + "/score") for _ in range(2)))
        assert a.status_code == b.status_code == 202
        await harness.drain()
        assert harness.provider.calls == {"prospect": 1, "score": 1}
        assert (await harness.get(run.id)).overall_score == 0
        assert await harness.events() == 1


async def test_worker_restart_keeps_queued_work_and_fails_uncertain_claim(harness: Harness) -> None:
    queued = await harness.create()
    claims = await harness.claim()
    async with harness.db() as db:
        await db.execute(
            RehearsalRun.__table__.update()
            .where(RehearsalRun.id == queued.id)
            .values(processing_started_at=datetime.now(UTC) - timedelta(minutes=4))
        )
        await db.commit()
    async with harness.db() as db:
        assert await execution.recover_stale_runs(db) == 1
    await harness.execute(claims[0])  # Late worker cannot overwrite failure or spend.
    failed = await harness.get(queued.id)
    assert failed.status == RehearsalStatus.FAILED and not failed.retryable
    assert not harness.provider.calls and await harness.events() == 0
    async with harness.db() as db:
        with pytest.raises(ValidationError, match="duplicate provider work"):
            await RoleplayService(db).retry_run(
                queued.id, harness.workspace_id, failed.attempt_count
            )
    resumed = await harness.create()
    # A replacement worker/session sees persisted pending work without an in-memory task.
    await harness.drain()
    assert (await harness.get(resumed.id)).status == RehearsalStatus.COMPLETED


async def test_cancellation_keeps_partial_dialogue_and_no_success(harness: Harness) -> None:
    run = await harness.create()
    harness.provider.delay = 60
    task = asyncio.create_task(harness.execute((await harness.claim())[0]))
    await asyncio.wait_for(harness.provider.entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await harness.get(run.id)
    assert result.status == RehearsalStatus.FAILED and not result.retryable
    assert result.transcript == run.transcript and result.overall_score is None
    assert await harness.events() == 0
    harness.notifications.assert_not_awaited()


async def test_polling_worker_is_bounded_and_does_not_block_heartbeat(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await asyncio.gather(*(harness.create() for _ in range(5)))
    harness.provider.delay = 60

    @asynccontextmanager
    async def session(reason: str) -> AsyncIterator[AsyncSession]:
        async with harness.db() as db:
            yield db

    monkeypatch.setattr("app.workers.roleplay_worker.system_session", session)
    worker = RoleplayWorker()
    try:
        await asyncio.wait_for(worker._process_items(), 2)
        await asyncio.wait_for(harness.provider.entered.wait(), 2)
        assert len(worker._inflight) == worker.MAX_CONCURRENCY
        await asyncio.wait_for(worker._process_items(), 2)
        assert len(worker._inflight) == worker.MAX_CONCURRENCY
    finally:
        tasks = list(worker._inflight)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_opening_failure_still_has_a_durable_identity(harness: Harness) -> None:
    async with harness.db() as db:
        persona = await db.get(ProspectPersona, harness.persona_id)
        assert persona is not None
        persona.opening_message = None
        await db.commit()
    key = uuid.uuid4()
    run = await harness.create(idempotency_key=key, rehearsee="human")
    assert run.status == RehearsalStatus.PENDING and run.transcript == []
    assert not harness.provider.calls
    harness.provider.failure = ("prospect", 429)
    await harness.drain()
    failed = await harness.get(run.id)
    assert failed.status == RehearsalStatus.FAILED and failed.overall_score is None
    assert failed.transcript == []
    assert (await harness.create(idempotency_key=key, rehearsee="human")).id == run.id
    assert harness.provider.calls == {"prospect": 1}
    assert await harness.events() == 0
    harness.notifications.assert_not_awaited()


async def test_expired_owner_cannot_checkpoint_a_late_provider_reply(harness: Harness) -> None:
    run = await harness.create()
    harness.provider.delay = 0.2
    task = asyncio.create_task(harness.execute((await harness.claim())[0]))
    await asyncio.wait_for(harness.provider.entered.wait(), 2)
    async with harness.db() as db:
        stored = await db.get(RehearsalRun, run.id)
        assert stored is not None
        stored.processing_started_at = datetime.now(UTC) - timedelta(minutes=4)
        await db.commit()
        assert await execution.recover_stale_runs(db) == 1
    await task
    result = await harness.get(run.id)
    assert result.status == RehearsalStatus.FAILED and not result.retryable
    assert result.transcript == run.transcript and result.overall_score is None
    assert harness.provider.calls == {"agent": 1}
    assert await harness.claim() == []
    assert await harness.events() == 0
    harness.notifications.assert_not_awaited()
