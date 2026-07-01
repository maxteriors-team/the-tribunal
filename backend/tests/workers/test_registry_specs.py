"""Tests for background worker registry metadata and lifecycle ordering."""

from __future__ import annotations

from app.api.v1 import health
from app.workers import (
    ALL_REGISTRIES,
    WORKER_SPECS,
    WorkerHealthMetadata,
    WorkerSpec,
    enabled_worker_specs,
    start_all_workers,
    stop_all_workers,
)
from app.workers.base import BaseWorker, WorkerRegistry


def test_worker_specs_preserve_existing_startup_order() -> None:
    """``WORKER_SPECS`` is the canonical registry and preserves legacy order."""
    assert [spec.name for spec in WORKER_SPECS] == [
        "campaign_worker",
        "voice_campaign_worker",
        "email_campaign_worker",
        "followup_worker",
        "reminder_worker",
        "message_test_worker",
        "reputation_worker",
        "enrichment_worker",
        "prompt_stats",
        "prompt_improvement",
        "outbound_improvement_suggestions",
        "experiment_evaluation",
        "automation_worker",
        "noshow_reengagement_worker",
        "review_request_worker",
        "recurring_job_worker",
        "never_booked_worker",
        "nudge_worker",
        "approval_worker",
        "drip_campaign_worker",
        "transcript_analysis_worker",
        "auth_rate_limit_cleanup",
        "ad_library_discovery_worker",
        "prospect_enrichment_worker",
        "prospect_promotion_worker",
        "ad_monitor_worker",
        "web_people_discovery_worker",
        "outbound_auto_draft_worker",
    ]
    assert [spec.registry for spec in WORKER_SPECS] == ALL_REGISTRIES


def test_worker_specs_include_health_and_dependency_metadata() -> None:
    """Every worker exposes enough metadata for operations and readiness."""
    names = [spec.name for spec in WORKER_SPECS]
    assert len(names) == len(set(names))

    for spec in WORKER_SPECS:
        assert spec.registry is not None
        assert spec.dependencies
        assert spec.health_metadata.component_name == spec.name
        assert spec.health_metadata.heartbeat_required is True
        assert spec.health_metadata.heartbeat_dependency == "redis"

    by_name = {spec.name: spec for spec in WORKER_SPECS}
    assert "redis" in by_name["campaign_worker"].dependencies
    assert "telnyx_voice" in by_name["voice_campaign_worker"].dependencies
    assert "openai" in by_name["transcript_analysis_worker"].dependencies
    assert "expo_push" in by_name["approval_worker"].dependencies


def test_enabled_worker_specs_applies_per_spec_predicate() -> None:
    """Per-worker enablement hooks can remove a spec without reordering others."""
    first = WorkerSpec(
        name="first",
        registry=WorkerRegistry(_NoopWorker),
        dependencies=("postgres",),
    )
    disabled = WorkerSpec(
        name="disabled",
        registry=WorkerRegistry(_NoopWorker),
        dependencies=("postgres",),
        enabled=_disabled,
    )
    last = WorkerSpec(
        name="last",
        registry=WorkerRegistry(_NoopWorker),
        dependencies=("redis",),
    )

    original_specs = (first, disabled, last)
    from app import workers

    previous_specs = workers.WORKER_SPECS
    try:
        workers.WORKER_SPECS = original_specs
        assert [spec.name for spec in enabled_worker_specs()] == ["first", "last"]
    finally:
        workers.WORKER_SPECS = previous_specs


async def test_start_and_stop_use_enabled_specs_in_order() -> None:
    """Lifecycle startup follows spec order and shutdown reverses it."""
    calls: list[str] = []
    first = _RecordingRegistry("first", calls)
    disabled = _RecordingRegistry("disabled", calls)
    last = _RecordingRegistry("last", calls)

    from app import workers

    previous_specs = workers.WORKER_SPECS
    try:
        workers.WORKER_SPECS = (
            WorkerSpec(name="first", registry=first, dependencies=("postgres",)),
            WorkerSpec(
                name="disabled",
                registry=disabled,
                dependencies=("postgres",),
                enabled=_disabled,
            ),
            WorkerSpec(name="last", registry=last, dependencies=("redis",)),
        )

        await start_all_workers()
        await stop_all_workers()
    finally:
        workers.WORKER_SPECS = previous_specs

    assert calls == ["start:first", "start:last", "stop:last", "stop:first"]


def test_expected_worker_labels_use_worker_spec_health_metadata() -> None:
    """Readiness heartbeat labels come from WorkerSpec health metadata."""
    running_registry = _StaticRegistry(_NoopWorker(component_name="runtime_component"))
    skipped_registry = _StaticRegistry(_NoopWorker(component_name="skipped_component"))

    previous_specs = health.WORKER_SPECS
    try:
        health.WORKER_SPECS = (
            WorkerSpec(
                name="public_label",
                registry=running_registry,
                dependencies=("redis",),
                health=WorkerHealthMetadata(component_name="public_label"),
            ),
            WorkerSpec(
                name="no_heartbeat",
                registry=skipped_registry,
                dependencies=("postgres",),
                health=WorkerHealthMetadata(
                    component_name="no_heartbeat",
                    heartbeat_required=False,
                ),
            ),
            WorkerSpec(
                name="not_running",
                registry=WorkerRegistry(_NoopWorker),
                dependencies=("postgres",),
            ),
        )

        assert health._expected_worker_labels() == ["public_label"]
    finally:
        health.WORKER_SPECS = previous_specs


class _NoopWorker(BaseWorker):
    """Minimal worker used by registry metadata tests."""

    COMPONENT_NAME = "noop_worker"

    def __init__(self, *, component_name: str | None = None) -> None:
        super().__init__()
        if component_name is not None:
            self._worker_label = component_name

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False

    async def _process_items(self) -> None:
        return None


class _StaticRegistry(WorkerRegistry[_NoopWorker]):
    """Registry double that exposes a pre-started worker instance."""

    def __init__(self, instance: _NoopWorker) -> None:
        super().__init__(_NoopWorker)
        self.instance = instance

    async def start(self) -> _NoopWorker:
        return self.instance

    async def stop(self) -> None:
        self.instance.running = False

    def get(self) -> _NoopWorker | None:
        return self.instance


class _RecordingRegistry(WorkerRegistry[_NoopWorker]):
    """Registry double that records lifecycle calls without spawning tasks."""

    def __init__(self, name: str, calls: list[str]) -> None:
        super().__init__(_NoopWorker)
        self.name = name
        self.calls = calls
        self.worker = _NoopWorker(component_name=name)

    async def start(self) -> _NoopWorker:
        self.calls.append(f"start:{self.name}")
        self._instance = self.worker
        return self.worker

    async def stop(self) -> None:
        self.calls.append(f"stop:{self.name}")
        self._instance = None

    def get(self) -> _NoopWorker | None:
        return self._instance


def _disabled(_settings: object) -> bool:
    return False
