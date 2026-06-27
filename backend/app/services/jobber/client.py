"""Async client for Jobber's GraphQL API.

Jobber is GraphQL-only: every request is a ``POST`` of ``{query, variables}`` to
a single endpoint with a bearer access token and a pinned schema-version header.
This client exposes just what the technician sync needs — a paginated
``iter_users()`` over the ``users`` connection — plus a low-level ``execute()``
for ad-hoc queries. It deliberately does **not** implement the OAuth2 dance:
callers supply an already-obtained access token (the CLI reads it from
``--token`` / ``JOBBER_ACCESS_TOKEN``), keeping token lifecycle out of band.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

JOBBER_GRAPHQL_URL = "https://api.getjobber.com/api/graphql"

# Page size for the ``users`` connection. Jobber rate-limits by query *cost*
# (a leaky bucket), so modest pages with cursor pagination stay well under the
# per-account point budget. 50 mirrors Jobber's own app-template default.
USERS_PAGE_SIZE = 50

# Conservative field selection. ``id`` is Jobber's stable ``EncodedId`` (our
# idempotency key); name/email/phone are nested objects in Jobber's schema.
# Kept in one constant so a schema change is a one-line edit, not a hunt.
USERS_QUERY = """
query SyncUsers($first: Int!, $after: String) {
  users(first: $first, after: $after) {
    nodes {
      id
      name { full first last }
      email { raw }
      phone { friendly }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class JobberApiError(RuntimeError):
    """Raised when Jobber returns a transport error or GraphQL ``errors``."""


class JobberClient:
    """Minimal async client over Jobber's GraphQL API."""

    def __init__(
        self,
        access_token: str,
        *,
        api_version: str,
        base_url: str = JOBBER_GRAPHQL_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not access_token:
            raise JobberApiError("a Jobber access token is required")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                # Pin the schema version so a Jobber breaking change can't
                # silently reshape responses under us.
                "X-JOBBER-GRAPHQL-VERSION": api_version,
            },
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._base_url = base_url

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one GraphQL operation and return its ``data`` payload.

        Raises :class:`JobberApiError` on HTTP failure or any GraphQL
        ``errors`` — GraphQL returns 200 with an ``errors`` array for query
        problems, so a clean status alone is not success.
        """
        try:
            resp = await self._client.post(
                self._base_url,
                json={"query": query, "variables": variables or {}},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobberApiError(
                f"Jobber API returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise JobberApiError(f"Jobber API request failed: {exc}") from exc

        payload: dict[str, Any] = resp.json()
        if payload.get("errors"):
            messages = "; ".join(str(err.get("message", err)) for err in payload["errors"])
            raise JobberApiError(f"Jobber GraphQL errors: {messages}")
        return payload.get("data") or {}

    async def iter_users(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every Jobber team-member ``user`` node, following cursors."""
        after: str | None = None
        page = 0
        while True:
            data = await self.execute(USERS_QUERY, {"first": USERS_PAGE_SIZE, "after": after})
            connection = data.get("users") or {}
            nodes = connection.get("nodes") or []
            page += 1
            logger.info("jobber_users_page", page=page, count=len(nodes))
            for node in nodes:
                yield node

            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            if not after:
                # Defensive: ``hasNextPage`` true with no cursor would loop
                # forever. Stop rather than hammer the API.
                logger.warning("jobber_users_missing_cursor", page=page)
                break

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> JobberClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
