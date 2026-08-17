"""Privacy-safe structured observability for AI context and actions.

The helpers in this module intentionally accept text only to count tokens. Event
payloads contain no text, tool arguments/results, raw record IDs, or raw PII.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

import structlog
import tiktoken

Freshness = Literal["current", "recent", "stale", "unknown"]

_CURRENT_SECONDS = 24 * 60 * 60
_RECENT_SECONDS = 30 * _CURRENT_SECONDS
_HASH_NAMESPACE = b"the-tribunal:ai-context-observability:v1"
_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")

# Use an unbound logger so caller-bound raw IDs cannot leak into privacy events.
observability_logger = structlog.get_logger("ai_observability")


@dataclass(frozen=True, slots=True)
class ContextChunk:
    """One prompt chunk and its source metadata; ``text`` is never emitted."""

    source_type: str
    source_ids: tuple[str, ...]
    text: str = field(repr=False)
    observed_at: datetime | None = None
    record_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextProvenanceSummary:
    """Collapsed source IDs/timestamps extracted from one typed context object."""

    source_ids: tuple[str, ...]
    earliest_observed_at: datetime | None
    earliest_record_updated_at: datetime | None


def collect_context_provenance(value: Any) -> ContextProvenanceSummary:
    """Collect typed ``source/source_id`` provenance without reading value fields."""

    discovered: dict[str, tuple[datetime | None, datetime | None]] = {}

    def walk(node: Any) -> None:
        if hasattr(node, "model_dump"):
            walk(node.model_dump(mode="python"))
            return
        if isinstance(node, dict):
            source = node.get("source")
            source_id = node.get("source_id")
            observed_at = node.get("observed_at")
            updated_at = node.get("updated_at")
            if (
                isinstance(source, str)
                and isinstance(source_id, str)
                and isinstance(observed_at, datetime)
            ):
                key = f"{source}:{source_id}"
                prior = discovered.get(key)
                candidate = (
                    observed_at,
                    updated_at if isinstance(updated_at, datetime) else observed_at,
                )
                if prior is None:
                    discovered[key] = candidate
                else:
                    discovered[key] = (
                        min(prior[0], candidate[0]) if prior[0] is not None else candidate[0],
                        min(prior[1], candidate[1]) if prior[1] is not None else candidate[1],
                    )
            for child in node.values():
                walk(child)
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)
    values = tuple(discovered.values())
    return ContextProvenanceSummary(
        source_ids=tuple(sorted(discovered)),
        earliest_observed_at=min((item[0] for item in values if item[0] is not None), default=None),
        earliest_record_updated_at=min(
            (item[1] for item in values if item[1] is not None),
            default=None,
        ),
    )


@lru_cache(maxsize=1)
def _tokenizer() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count prompt tokens locally without retaining or logging the text."""

    if not text:
        return 0
    return len(_tokenizer().encode(text, disallowed_special=()))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((_as_utc(now) - _as_utc(value)).total_seconds()))


def _freshness(age_seconds: int | None) -> Freshness:
    if age_seconds is None:
        return "unknown"
    if age_seconds <= _CURRENT_SECONDS:
        return "current"
    if age_seconds <= _RECENT_SECONDS:
        return "recent"
    return "stale"


def _default_hash_key() -> str:
    # Lazy import keeps this module usable in isolated mechanics tests.
    from app.core.config import settings

    return settings.secret_key


def _derived_hash_key(hash_key: str) -> bytes:
    return hmac.new(hash_key.encode("utf-8"), _HASH_NAMESPACE, hashlib.sha256).digest()


def pseudonymous_ref(source_type: str, raw_id: str, *, hash_key: str | None = None) -> str:
    """Return a stable, non-reversible reference for one internal source ID."""

    key = _derived_hash_key(hash_key or _default_hash_key())
    digest = hmac.new(key, f"{source_type}:{raw_id}".encode(), hashlib.sha256).hexdigest()
    return f"ctx_{digest[:16]}"


def build_context_event(
    *,
    surface: Literal["sms", "voice", "crm_assistant"],
    invocation_id: str,
    chunks: Sequence[ContextChunk],
    model: str | None = None,
    temperature: float | None = None,
    now: datetime | None = None,
    hash_key: str | None = None,
) -> dict[str, Any]:
    """Build a body-free event describing context provenance and prompt size."""

    observed_now = _as_utc(now or datetime.now(UTC))
    key = hash_key or _default_hash_key()
    safe_sources: list[dict[str, Any]] = []
    total_tokens = 0

    for chunk in chunks:
        token_count = count_tokens(chunk.text)
        total_tokens += token_count
        record_age = _age_seconds(chunk.record_updated_at, observed_now)
        safe_sources.append(
            {
                "source_type": chunk.source_type,
                "source_refs": [
                    pseudonymous_ref(chunk.source_type, source_id, hash_key=key)
                    for source_id in chunk.source_ids
                ],
                "freshness": _freshness(record_age),
                "observed_age_seconds": _age_seconds(chunk.observed_at, observed_now),
                "record_age_seconds": record_age,
                "token_count": token_count,
            }
        )

    return {
        "surface": surface,
        "invocation_ref": pseudonymous_ref("invocation", invocation_id, hash_key=key),
        "source_count": len(safe_sources),
        "context_token_count": total_tokens,
        "context_sources": safe_sources,
        "model": model,
        "temperature": temperature,
    }


def observe_context(log: Any, **kwargs: Any) -> dict[str, Any]:
    """Emit and return a privacy-safe ``ai_context_observed`` event."""

    event = build_context_event(**kwargs)
    log.info("ai_context_observed", **event)
    return event


def observe_tool_call(
    log: Any,
    *,
    surface: Literal["sms", "voice", "crm_assistant"],
    invocation_id: str,
    tool_call_id: str,
    tool_name: str,
    status: Literal["requested", "completed", "pending_approval", "blocked", "failed"],
    success: bool | None = None,
    hash_key: str | None = None,
) -> dict[str, Any]:
    """Emit tool metadata without arguments, results, exception text, or raw IDs."""

    key = hash_key or _default_hash_key()
    event = {
        "surface": surface,
        "invocation_ref": pseudonymous_ref("invocation", invocation_id, hash_key=key),
        "tool_call_ref": pseudonymous_ref("tool_call", tool_call_id, hash_key=key),
        "tool_name": (tool_name if _SAFE_TOOL_NAME.fullmatch(tool_name) else "invalid_tool_name"),
        "status": status,
        "success": success,
    }
    log.info("ai_tool_call_observed", **event)
    return event


def observe_human_correction(
    log: Any,
    *,
    workspace_id: str,
    contact_id: str,
    operator_id: str,
    correction_id: str,
    correction_kind: Literal["summary", "fact"],
    action: Literal["replaced", "removed"],
    hash_key: str | None = None,
) -> dict[str, Any]:
    """Emit correction categories and pseudonymous refs, never corrected values."""

    key = hash_key or _default_hash_key()
    event = {
        "workspace_ref": pseudonymous_ref("workspace", workspace_id, hash_key=key),
        "contact_ref": pseudonymous_ref("contact", contact_id, hash_key=key),
        "operator_ref": pseudonymous_ref("operator", operator_id, hash_key=key),
        "correction_ref": pseudonymous_ref("correction", correction_id, hash_key=key),
        "correction_kind": correction_kind,
        "action": action,
    }
    log.info("ai_human_correction_observed", **event)
    return event


def observe_model_route(
    log: Any,
    *,
    invocation_id: str,
    mode: Literal["off", "shadow", "active"],
    recommended_tier: Literal["cheap", "strong"],
    recommended_model: str,
    recommended_temperature: float,
    selected_model: str,
    selected_temperature: float,
    reason_codes: Sequence[str],
    hash_key: str | None = None,
) -> dict[str, Any]:
    """Emit SMS route metadata without retaining the turn used to classify it."""

    key = hash_key or _default_hash_key()
    event = {
        "surface": "sms",
        "invocation_ref": pseudonymous_ref("invocation", invocation_id, hash_key=key),
        "mode": mode,
        "recommended_tier": recommended_tier,
        "recommended_model": recommended_model,
        "recommended_temperature": recommended_temperature,
        "selected_model": selected_model,
        "selected_temperature": selected_temperature,
        "reason_codes": sorted(set(reason_codes)),
    }
    log.info("ai_model_route_observed", **event)
    return event
