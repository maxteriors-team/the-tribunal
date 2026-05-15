"""Structlog configuration with sensitive-key redaction.

Provides a processor that walks each event dict (and nested mappings/sequences)
replacing values for known-sensitive keys with ``"[REDACTED]"`` before any
renderer emits the log line. Wire-up runs at import time via
:func:`configure_logging`, which is idempotent.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Final

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED: Final[str] = "[REDACTED]"

# Keys whose values must never appear in log output. Match is
# case-insensitive on the exact key name (not substring) so we don't
# accidentally redact unrelated fields like ``phone_country_code``.
SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "phone",
        "phone_number",
        "email",
        "full_name",
        "password",
        "token",
        "secret",
        "authorization",
        "api_key",
        "webhook_secret",
    }
)


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys inside ``value``.

    Mappings are copied (never mutated in place) so callers retain their
    originals. Lists/tuples are walked element-wise. Scalars pass through
    unchanged.
    """
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, sub in value.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(sub)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive_keys(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor: redact sensitive keys at any nesting depth.

    Top-level keys are rewritten in place on the supplied ``event_dict``
    (structlog expects the same object back); nested containers are rebuilt
    via :func:`_redact`.
    """
    mutable: MutableMapping[str, Any] = event_dict
    for key in list(mutable.keys()):
        if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
            mutable[key] = REDACTED
            continue
        sub = mutable[key]
        if isinstance(sub, Mapping):
            mutable[key] = _redact(sub)
        elif isinstance(sub, list | tuple) and not isinstance(sub, str | bytes):
            assert isinstance(sub, Sequence)
            mutable[key] = _redact(sub)
    return event_dict


def _build_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive_keys,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog with the redaction processor wired in.

    Safe to call multiple times; structlog's ``configure`` replaces prior
    configuration atomically.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    structlog.configure(
        processors=_build_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
