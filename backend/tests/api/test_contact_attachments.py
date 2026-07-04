"""Tests for contact Files & Media attachments.

Pure-helper tests (filename sanitizing, inline/attachment disposition) plus
mocked-DB route tests for upload validation and the not-found paths.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import contact_attachments as module
from app.api.v1.contact_attachments import (
    MAX_ATTACHMENT_BYTES,
    content_disposition,
    sanitize_filename,
)

WS_ID = uuid.uuid4()


class TestSanitizeFilename:
    def test_strips_path_segments(self) -> None:
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("C:\\Users\\evil\\doc.pdf") == "doc.pdf"

    def test_replaces_header_hostile_chars(self) -> None:
        assert sanitize_filename('roof "before".jpg') == "roof _before_.jpg"

    def test_empty_and_dotfile(self) -> None:
        assert sanitize_filename(None) == "file"
        assert sanitize_filename("") == "file"
        assert sanitize_filename(".env") == "file.env"

    def test_truncates_long_names(self) -> None:
        assert len(sanitize_filename("a" * 300 + ".jpg")) == 255


class TestContentDisposition:
    def test_images_and_pdf_inline(self) -> None:
        assert content_disposition("a.jpg", "image/jpeg").startswith("inline")
        assert content_disposition("a.pdf", "application/pdf").startswith("inline")

    def test_html_svg_and_unknown_forced_to_attachment(self) -> None:
        assert content_disposition("a.html", "text/html").startswith("attachment")
        assert content_disposition("a.svg", "image/svg+xml").startswith("attachment")
        assert content_disposition("a.bin", "application/octet-stream").startswith("attachment")

    def test_filename_included(self) -> None:
        assert content_disposition("photo.png", "image/png") == 'inline; filename="photo.png"'


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_app(mock_db: AsyncMock) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(module.router, prefix="/api/v1/workspaces/{workspace_id}")

    workspace = MagicMock()
    workspace.id = WS_ID
    user = MagicMock()
    user.id = 1
    user.is_active = True

    async def override_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_workspace] = lambda: workspace
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def _db_returning(scalar_results: list[object]) -> AsyncMock:
    """Mock DB whose successive ``execute`` calls yield the given scalars."""
    db = AsyncMock()
    results = []
    for value in scalar_results:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


@pytest.fixture
def contact() -> MagicMock:
    c = MagicMock()
    c.id = 7
    c.workspace_id = WS_ID
    return c


async def test_upload_rejects_oversized_file(contact: MagicMock) -> None:
    db = _db_returning([contact])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts/7/attachments",
            files={"file": ("big.jpg", b"x" * (MAX_ATTACHMENT_BYTES + 1), "image/jpeg")},
        )
    assert response.status_code == 413
    db.add.assert_not_called()


async def test_upload_rejects_empty_file(contact: MagicMock) -> None:
    db = _db_returning([contact])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts/7/attachments",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
    assert response.status_code == 422
    db.add.assert_not_called()


async def test_upload_404_when_contact_not_in_workspace() -> None:
    db = _db_returning([None])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts/999/attachments",
            files={"file": ("a.jpg", b"data", "image/jpeg")},
        )
    assert response.status_code == 404


async def test_download_404_when_attachment_missing() -> None:
    db = _db_returning([None])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/contacts/7/attachments/{uuid.uuid4()}/download"
        )
    assert response.status_code == 404


async def test_download_serves_bytes_with_nosniff() -> None:
    attachment = MagicMock()
    attachment.data = b"\x89PNG fake"
    attachment.content_type = "image/png"
    attachment.filename = "roof.png"
    db = _db_returning([attachment])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/contacts/7/attachments/{uuid.uuid4()}/download"
        )
    assert response.status_code == 200
    assert response.content == b"\x89PNG fake"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'inline; filename="roof.png"'


async def test_delete_404_when_missing() -> None:
    db = _db_returning([None])
    app = _make_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.delete(
            f"/api/v1/workspaces/{WS_ID}/contacts/7/attachments/{uuid.uuid4()}"
        )
    assert response.status_code == 404
