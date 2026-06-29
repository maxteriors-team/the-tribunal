"""Async client for Jobber's GraphQL API.

Jobber is GraphQL-only: every request is a ``POST`` of ``{query, variables}`` to
a single endpoint with a bearer access token and a pinned schema-version header.
This client exposes paginated iterators over the connections the CRM imports —
``iter_users()`` (team members), ``iter_clients()`` (customers + their
properties), ``iter_jobs()`` (work orders), and ``iter_invoices()`` (billing) —
plus a low-level ``execute()`` for ad-hoc queries. It deliberately does **not**
implement the OAuth2 dance: callers supply an already-obtained access token (the
CLI reads it from ``--token`` / ``JOBBER_ACCESS_TOKEN``), keeping token lifecycle
out of band.
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

# Page size shared by the import connections (clients/jobs/invoices). Jobber
# rate-limits by query *cost*, and these nodes are heavier than ``users`` (they
# embed nested connections), so a modest page keeps each request well under the
# per-account point budget.
IMPORT_PAGE_SIZE = 25

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

# Clients are Jobber's customers. ``clientProperties`` embeds each client's job
# sites so contacts + their service-locations import in one pass. Email/phone are
# connections in Jobber's schema; the primary entry is flagged with ``primary``.
CLIENTS_QUERY = """
query SyncClients($first: Int!, $after: String, $propertyFirst: Int!) {
  clients(first: $first, after: $after) {
    nodes {
      id
      name
      firstName
      lastName
      companyName
      isCompany
      emails { primary address description }
      phones { primary number description }
      billingAddress { street1 street2 city province postalCode country }
      clientProperties(first: $propertyFirst) {
        nodes {
          id
          address {
            street1 street2 city province postalCode country latitude longitude
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

# Jobs are work orders. ``client``/``property`` carry the Jobber ids we resolve
# to already-imported contacts/service-locations; ``assignedUsers`` carry the
# technician ids (matched to previously-synced ``Technician.external_id``).
JOBS_QUERY = """
query SyncJobs($first: Int!, $after: String, $assignedFirst: Int!) {
  jobs(first: $first, after: $after) {
    nodes {
      id
      jobNumber
      title
      instructions
      jobStatus
      startAt
      endAt
      client { id }
      property { id }
      assignedUsers(first: $assignedFirst) { nodes { id } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

# Invoices are imported as historical/AR records only (never re-billed).
# ``amounts`` holds the money; ``invoiceStatus`` maps to our status set.
INVOICES_QUERY = """
query SyncInvoices($first: Int!, $after: String) {
  invoices(first: $first, after: $after) {
    nodes {
      id
      invoiceNumber
      invoiceStatus
      issuedDate
      dueDate
      subject
      message
      client { id }
      amounts { total subtotal taxAmount discountAmount paymentsTotal invoiceBalance }
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

    async def _iter_connection(
        self,
        query: str,
        connection_key: str,
        *,
        extra_variables: dict[str, Any] | None = None,
        page_size: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every node of a top-level Jobber connection, following cursors.

        ``connection_key`` is the response field that holds the connection (e.g.
        ``"users"``, ``"clients"``). ``extra_variables`` are merged into every
        page request (e.g. nested-connection page sizes). Shared by all the
        ``iter_*`` methods so cursor handling lives in exactly one place.
        """
        after: str | None = None
        page = 0
        while True:
            variables: dict[str, Any] = {"first": page_size, "after": after}
            if extra_variables:
                variables.update(extra_variables)
            data = await self.execute(query, variables)
            connection = data.get(connection_key) or {}
            nodes = connection.get("nodes") or []
            page += 1
            logger.info(
                "jobber_connection_page", connection=connection_key, page=page, count=len(nodes)
            )
            for node in nodes:
                yield node

            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            if not after:
                # Defensive: ``hasNextPage`` true with no cursor would loop
                # forever. Stop rather than hammer the API.
                logger.warning(
                    "jobber_connection_missing_cursor", connection=connection_key, page=page
                )
                break

    def iter_users(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every Jobber team-member ``user`` node, following cursors."""
        return self._iter_connection(USERS_QUERY, "users", page_size=USERS_PAGE_SIZE)

    def iter_clients(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every Jobber ``client`` node (with nested ``clientProperties``)."""
        return self._iter_connection(
            CLIENTS_QUERY,
            "clients",
            extra_variables={"propertyFirst": IMPORT_PAGE_SIZE},
            page_size=IMPORT_PAGE_SIZE,
        )

    def iter_jobs(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every Jobber ``job`` node (with client/property/assignees)."""
        return self._iter_connection(
            JOBS_QUERY,
            "jobs",
            extra_variables={"assignedFirst": IMPORT_PAGE_SIZE},
            page_size=IMPORT_PAGE_SIZE,
        )

    def iter_invoices(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every Jobber ``invoice`` node (historical/AR import)."""
        return self._iter_connection(INVOICES_QUERY, "invoices", page_size=IMPORT_PAGE_SIZE)

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> JobberClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
