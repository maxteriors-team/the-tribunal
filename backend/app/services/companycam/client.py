"""Thin async client for the CompanyCam v2 REST API.

Docs: https://docs.companycam.com/reference. Auth is a bearer access token
stored per-workspace in ``workspace_integrations`` (type ``companycam``).

Matching strategy (see :func:`find_projects_for_contact`): CompanyCam's
``/projects?query=`` searches project *name and address* (not phone), and
projects carry a ``primary_contact`` with phone/email. So we search by the
contact's name (and street address as a fallback) and then keep results whose
primary contact phone/email matches — or whose project name equals the
contact's full name when the project has no primary contact to check.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

API_BASE = "https://api.companycam.com/v2"
_TIMEOUT = 15.0

# Cap how many matched projects we pull photos for in one contact view.
MAX_PROJECTS_PER_CONTACT = 5
# Thumbnails per project shown in the sidebar gallery.
MAX_PHOTOS_PER_PROJECT = 24


class CompanyCamApiError(Exception):
    """CompanyCam returned a non-success response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"CompanyCam API error {status_code}: {message}")


def _digits(value: str | None) -> str:
    """Reduce a phone to digits only, dropping a leading US country code."""
    d = re.sub(r"\D", "", value or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


class CompanyCamClient:
    """Minimal CompanyCam API wrapper for the contact-photos surface."""

    def __init__(self, access_token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{API_BASE}{path}", params=params, headers=self._headers)
        if response.status_code != 200:
            raise CompanyCamApiError(response.status_code, response.text[:200])
        return response.json()

    async def get_current_user(self) -> dict[str, Any]:
        """Return the token's user — used to verify a pasted token."""
        data = await self._get("/users/current")
        return data if isinstance(data, dict) else {}

    async def search_projects(self, query: str, per_page: int = 25) -> list[dict[str, Any]]:
        """Search projects by name/address substring."""
        if not query.strip():
            return []
        data = await self._get("/projects", params={"query": query.strip(), "per_page": per_page})
        return data if isinstance(data, list) else []

    async def list_project_photos(
        self, project_id: str, per_page: int = MAX_PHOTOS_PER_PROJECT
    ) -> list[dict[str, Any]]:
        """Return photos for one project (newest first per API default)."""
        data = await self._get(f"/projects/{project_id}/photos", params={"per_page": per_page})
        return data if isinstance(data, list) else []


def _project_matches_contact(
    project: dict[str, Any],
    *,
    full_name: str,
    phone_digits: str,
    email: str,
) -> bool:
    """Decide whether a searched project belongs to this CRM contact."""
    primary = project.get("primary_contact") or {}
    if phone_digits and _digits(primary.get("phone_number")) == phone_digits:
        return True
    primary_email = (primary.get("email") or "").strip().lower()
    if email and primary_email == email:
        return True
    # Name-only fallback: search already narrowed by name/address; accept an
    # exact (case-insensitive) project-name match when there's no contact info
    # on the project to contradict it.
    project_name = (project.get("name") or "").strip().lower()
    has_contact_info = bool(primary.get("phone_number") or primary.get("email"))
    return bool(full_name) and project_name == full_name and not has_contact_info


async def find_projects_for_contact(
    client: CompanyCamClient,
    *,
    first_name: str,
    last_name: str | None,
    phone_number: str | None,
    email: str | None,
    address_line1: str | None,
) -> list[dict[str, Any]]:
    """Search + filter CompanyCam projects that belong to a CRM contact."""
    full_name = " ".join(p for p in (first_name, last_name) if p).strip()
    phone_digits = _digits(phone_number)
    email_normalized = (email or "").strip().lower()

    candidates: dict[str, dict[str, Any]] = {}
    for query in (full_name, address_line1 or ""):
        if not query.strip():
            continue
        for project in await client.search_projects(query):
            project_id = str(project.get("id") or "")
            if project_id:
                candidates.setdefault(project_id, project)

    matched = [
        project
        for project in candidates.values()
        if _project_matches_contact(
            project,
            full_name=full_name.lower(),
            phone_digits=phone_digits,
            email=email_normalized,
        )
    ]
    # Newest work first; created_at is an integer epoch.
    matched.sort(key=lambda p: p.get("created_at") or 0, reverse=True)
    return matched[:MAX_PROJECTS_PER_CONTACT]
