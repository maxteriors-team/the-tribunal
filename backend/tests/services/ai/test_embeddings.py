"""Tests for workspace-scoped embedding credential resolution."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai import embeddings


@pytest.mark.asyncio
async def test_workspace_embedder_uses_workspace_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    db = AsyncMock()
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.2, 0.3]),
                SimpleNamespace(index=0, embedding=[0.0, 0.1]),
            ]
        )
    )
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    resolve_client = AsyncMock(return_value=client)
    monkeypatch.setattr(embeddings, "create_workspace_openai_client", resolve_client)

    embedder = await embeddings.create_workspace_embedder(db, workspace_id)
    result = await embedder(["first", "second"])

    resolve_client.assert_awaited_once_with(db, workspace_id)
    create.assert_awaited_once_with(
        model=embeddings.EMBEDDING_MODEL,
        input=["first", "second"],
        dimensions=embeddings.EMBEDDING_DIM,
    )
    assert result.ok is True
    assert result.embeddings == [[0.0, 0.1], [0.2, 0.3]]


@pytest.mark.asyncio
async def test_workspace_credential_failure_returns_log_safe_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = AsyncMock(side_effect=RuntimeError("secret provider detail"))
    monkeypatch.setattr(embeddings, "create_workspace_openai_client", resolve_client)

    embedder = await embeddings.create_workspace_embedder(AsyncMock(), uuid.uuid4())
    result = await embedder(["pricing"])

    assert result.ok is False
    assert result.error == "Embedding request failed."
