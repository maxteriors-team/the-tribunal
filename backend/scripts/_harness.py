"""Shared harness for The Tribunal's operational scripts.

Every script under ``scripts/`` (repo root) and ``backend/scripts/`` uses this
module so operators get a single, predictable contract:

* ``--env {local,staging,production}`` — an explicit, required target. There is
  no implicit default: a script can never touch staging or production unless the
  operator says so out loud.
* ``--dry-run`` — added to any script that writes. In dry-run mode the script
  reports exactly what it *would* change and commits nothing.
* Production/staging confirmation — non-local targets require typed confirmation
  (or an explicit ``--yes`` for automation) before any write happens.
* Structured logging — key=value (or JSON line) records with timestamps, so the
  output is greppable and machine-parseable instead of ad-hoc ``print`` noise.
* Standard exit codes — :data:`EXIT_OK`, :data:`EXIT_FAILURE`,
  :data:`EXIT_USAGE`, :data:`EXIT_ABORTED`.

Importing this module also guarantees the backend ``app`` package is importable,
regardless of how deeply the calling script is nested, so scripts never have to
hand-roll ``sys.path`` surgery.

Database targeting
------------------

``--env`` is first and foremost a *safety and observability* gate. The actual
database a script talks to is still resolved by the backend ``Settings``
(``DATABASE_URL`` / ``backend/.env``), which is how staging/production tunnels
are wired today. If a per-environment override variable is present
(``LOCAL_DATABASE_URL`` / ``STAGING_DATABASE_URL`` / ``PRODUCTION_DATABASE_URL``)
it is promoted to ``DATABASE_URL`` *before* the backend config is imported, so it
takes effect cleanly. Call :func:`bootstrap` (or build a context with
:func:`from_args`) before importing ``app.core.config`` to use that path.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ConfigureParser = Callable[[argparse.ArgumentParser], None]
"""A callback that adds script-specific arguments to a parser."""

# ─── Exit codes ──────────────────────────────────────────────────────────────

EXIT_OK = 0
"""The script completed successfully."""

EXIT_FAILURE = 1
"""The script ran but encountered an unrecoverable error (or partial failure)."""

EXIT_USAGE = 2
"""The script was invoked incorrectly (bad arguments / environment)."""

EXIT_ABORTED = 3
"""The operator declined a confirmation prompt, or a guard refused to proceed."""


class ScriptAbortError(Exception):
    """Raised to abort a run cleanly with :data:`EXIT_ABORTED`.

    Carrying an explicit exit code keeps the abort path out of the generic
    exception handler in :func:`run`, so "operator said no" never looks like a
    crash.
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_ABORTED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class Env(StrEnum):
    """A deployment target a script may run against."""

    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_local(self) -> bool:
        """Return whether this is the developer's local environment."""
        return self is Env.LOCAL

    @property
    def requires_confirmation(self) -> bool:
        """Return whether running here demands explicit operator confirmation."""
        return self is not Env.LOCAL


ENV_CHOICES: tuple[str, ...] = tuple(member.value for member in Env)


# ─── Backend import bootstrap ────────────────────────────────────────────────


def backend_root() -> Path:
    """Return the backend project root (the directory containing ``app/``).

    This module lives at ``backend/scripts/_harness.py``, so the backend root is
    two levels up — a fixed relationship no matter where the *calling* script
    sits in the tree.
    """
    return Path(__file__).resolve().parents[1]


def ensure_backend_on_path() -> Path:
    """Make the backend ``app`` package importable and return the backend root."""
    root = backend_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def _promote_env_database_url(env: Env) -> None:
    """Promote ``<ENV>_DATABASE_URL`` to ``DATABASE_URL`` when present.

    Done before ``app.core.config`` is imported so the backend ``Settings`` pick
    up the per-environment override transparently.
    """
    override = os.environ.get(f"{env.name}_DATABASE_URL")
    if override:
        os.environ["DATABASE_URL"] = override


# ─── Structured logging ──────────────────────────────────────────────────────


class _KeyValueFormatter(logging.Formatter):
    """Render ``timestamp level logger: message key=value`` records."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = getattr(record, "context", None)
        if context:
            base = f"{base} {_render_context(context)}"
        return base


class _JsonFormatter(logging.Formatter):
    """Render one JSON object per log line for machine ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, Mapping):
            for key, value in context.items():
                payload.setdefault(str(key), value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


def _render_context(context: Mapping[str, object]) -> str:
    """Render a context mapping as deterministic ``key=value`` pairs."""
    parts: list[str] = []
    for key in sorted(context):
        value = context[key]
        text = str(value)
        if any(ch.isspace() for ch in text):
            text = json.dumps(text)
        parts.append(f"{key}={text}")
    return " ".join(parts)


def setup_logging(*, level: int = logging.INFO, json_logs: bool = False) -> None:
    """Configure root logging for a script run.

    Idempotent: repeated calls replace the handler rather than stacking, so a
    script that imports another script's helpers does not double-log.
    """
    handler = logging.StreamHandler(stream=sys.stderr)
    if json_logs:
        handler.setFormatter(_JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
    else:
        handler.setFormatter(
            _KeyValueFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_event(logger: logging.Logger, level: int, message: str, /, **context: object) -> None:
    """Emit a structured log record with arbitrary ``key=value`` context."""
    logger.log(level, message, extra={"context": context} if context else None)


# ─── Execution context ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Resolved, validated runtime parameters shared by every script."""

    env: Env
    dry_run: bool
    assume_yes: bool
    logger: logging.Logger

    @property
    def is_production(self) -> bool:
        """Return whether this run targets production."""
        return self.env is Env.PRODUCTION

    def writes_enabled(self) -> bool:
        """Return whether the script may actually persist changes."""
        return not self.dry_run

    def announce(self, action: str, /, **context: object) -> None:
        """Log the run's intent, including environment and dry-run posture."""
        log_event(
            self.logger,
            logging.INFO,
            action,
            env=self.env.value,
            dry_run=self.dry_run,
            **context,
        )
        if self.dry_run:
            log_event(
                self.logger,
                logging.WARNING,
                "dry-run active: no changes will be committed",
                env=self.env.value,
            )

    def confirm(self, action: str) -> None:
        """Require operator confirmation before mutating a non-local target.

        * ``local`` never prompts.
        * ``--yes`` skips the prompt but logs a loud warning (for automation).
        * A non-interactive shell without ``--yes`` is refused outright.
        * Otherwise the operator must type the environment name exactly.

        Raises :class:`ScriptAbortError` when the operator declines or the run
        cannot be safely confirmed.
        """
        if not self.env.requires_confirmation:
            return

        if self.dry_run:
            # Nothing will be written, so a dry-run never needs confirmation.
            return

        if self.assume_yes:
            log_event(
                self.logger,
                logging.WARNING,
                "proceeding without interactive confirmation (--yes)",
                env=self.env.value,
                action=action,
            )
            return

        if not sys.stdin.isatty():
            raise ScriptAbortError(
                f"refusing to {action} against {self.env.value} non-interactively without --yes",
                exit_code=EXIT_ABORTED,
            )

        log_event(
            self.logger,
            logging.WARNING,
            "about to perform a destructive action",
            env=self.env.value,
            action=action,
        )
        prompt = (
            f"\n  ⚠  This will {action} against {self.env.value.upper()}.\n"
            f"  Type '{self.env.value}' to proceed (anything else aborts): "
        )
        reply = input(prompt).strip()
        if reply != self.env.value:
            raise ScriptAbortError("confirmation did not match — aborted", exit_code=EXIT_ABORTED)


# ─── Argument wiring ─────────────────────────────────────────────────────────


def add_standard_arguments(
    parser: argparse.ArgumentParser,
    *,
    writes: bool = True,
    default_env: str | None = None,
) -> None:
    """Add the harness's standard flags to an existing parser.

    Parameters
    ----------
    writes:
        Whether the script mutates state. Read-only scripts pass ``writes=False``
        and do not get a ``--dry-run`` flag.
    default_env:
        Optional default for ``--env``. Leave ``None`` to force the operator to
        state the target explicitly (recommended for anything that writes).
    """
    group = parser.add_argument_group("environment")
    group.add_argument(
        "--env",
        choices=ENV_CHOICES,
        default=default_env,
        required=default_env is None,
        help="Target environment. Required and explicit — there is no implicit default.",
    )
    group.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation for staging/production (for automation).",
    )
    group.add_argument(
        "--json-logs",
        action="store_true",
        help="Emit one JSON object per log line instead of key=value text.",
    )
    group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    if writes:
        group.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without committing any writes.",
        )


def from_args(
    args: argparse.Namespace,
    *,
    logger_name: str = "script",
) -> ExecutionContext:
    """Build an :class:`ExecutionContext` from parsed arguments.

    Configures logging, promotes any per-environment ``DATABASE_URL`` override,
    and returns the validated context. Call this before importing
    ``app.core.config`` if you rely on the override behaviour.
    """
    env = Env(args.env)
    json_logs = bool(getattr(args, "json_logs", False))
    verbose = bool(getattr(args, "verbose", False))
    dry_run = bool(getattr(args, "dry_run", False))
    assume_yes = bool(getattr(args, "yes", False))

    setup_logging(level=logging.DEBUG if verbose else logging.INFO, json_logs=json_logs)
    _promote_env_database_url(env)
    ensure_backend_on_path()

    return ExecutionContext(
        env=env,
        dry_run=dry_run,
        assume_yes=assume_yes,
        logger=logging.getLogger(logger_name),
    )


def bootstrap(
    *,
    description: str,
    writes: bool = True,
    default_env: str | None = None,
    logger_name: str = "script",
    argv: Sequence[str] | None = None,
    configure: ConfigureParser | None = None,
) -> tuple[ExecutionContext, argparse.Namespace]:
    """One-call setup for the common case.

    Builds a parser with the standard flags (plus any script-specific flags added
    by ``configure``), parses ``argv``, and returns the resolved context and the
    parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_standard_arguments(parser, writes=writes, default_env=default_env)
    if configure is not None:
        configure(parser)
    args = parser.parse_args(argv)
    ctx = from_args(args, logger_name=logger_name)
    return ctx, args


def run(main: Callable[[], int]) -> int:
    """Execute ``main`` with uniform error handling and exit codes.

    Returns an exit code suitable for ``sys.exit``/``raise SystemExit``:

    * the value ``main`` returns (defaulting to :data:`EXIT_OK` for ``None``),
    * :data:`EXIT_ABORTED` for :class:`ScriptAbortError`,
    * :data:`EXIT_FAILURE` for any other exception (logged with traceback).
    """
    logger = logging.getLogger("script")
    try:
        result = main()
    except ScriptAbortError as abort:
        logger.warning("%s", abort)
        return abort.exit_code
    except KeyboardInterrupt:
        logger.warning("interrupted")
        return EXIT_ABORTED
    except Exception:  # noqa: BLE001 — top-level boundary: log and convert to exit code.
        logger.exception("unhandled error")
        return EXIT_FAILURE
    if result is None:
        return EXIT_OK
    return int(result)


__all__ = [
    "ENV_CHOICES",
    "EXIT_ABORTED",
    "EXIT_FAILURE",
    "EXIT_OK",
    "EXIT_USAGE",
    "ConfigureParser",
    "Env",
    "ExecutionContext",
    "ScriptAbortError",
    "add_standard_arguments",
    "backend_root",
    "bootstrap",
    "ensure_backend_on_path",
    "from_args",
    "log_event",
    "run",
    "setup_logging",
]
