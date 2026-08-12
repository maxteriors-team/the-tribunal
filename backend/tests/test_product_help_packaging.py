"""The bundled help corpus must survive packaging, and say so when it doesn't.

``search_help`` answers product questions by reading markdown off disk, so the
corpus is application data rather than documentation. That makes it uniquely
easy to lose: an ignore rule, a build stage that copies only ``app/``, or a
trimmed image drops the files, and nothing fails. The container builds, boots,
serves every endpoint, and the only symptom is the in-app assistant replying
"no matching help" to every question a customer support rep asks it.

These tests pin both halves of the guard: readiness refuses to promote such a
build, and boot names the problem in the logs without killing the process.
"""

import structlog

from app.api.v1.health import _check_product_help
from app.main import _warm_product_help_corpus
from app.services.knowledge.product_help import HELP_DOCS_DIR, ProductHelpError

log = structlog.get_logger()


def test_corpus_resolves_from_the_packaged_path() -> None:
    """The path is derived from ``__file__``, so it must hold inside an image."""
    assert HELP_DOCS_DIR.is_dir(), f"help corpus missing at {HELP_DOCS_DIR}"
    assert list(HELP_DOCS_DIR.glob("*.md")), "help corpus contains no markdown"


def test_check_reports_the_real_article_count() -> None:
    ok, articles, error = _check_product_help()

    assert ok is True
    assert error is None
    assert articles == len(list(HELP_DOCS_DIR.glob("*.md")))


def test_check_fails_closed_and_names_the_missing_directory(monkeypatch) -> None:
    def _missing() -> list[object]:
        raise ProductHelpError("Help corpus directory not found: /app/docs/help")

    monkeypatch.setattr("app.api.v1.health.load_product_help_articles", _missing)

    ok, articles, error = _check_product_help()

    assert ok is False
    assert articles == 0
    assert error is not None and "/app/docs/help" in error


def test_boot_logs_the_failure_without_crashing(monkeypatch) -> None:
    """Readiness already blocks promotion, so boot stays up to be diagnosable.

    A container that keeps answering ``/readyz`` with the failing check named
    is easier to debug than a crash loop whose only evidence is scrollback.
    """

    def _missing() -> list[object]:
        raise ProductHelpError("Help corpus directory not found: /app/docs/help")

    monkeypatch.setattr("app.main.load_product_help_articles", _missing)

    # Must not raise.
    _warm_product_help_corpus(log)
