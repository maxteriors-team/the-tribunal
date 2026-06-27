"""Jobber integration: pull team members into CRM technicians.

Jobber's API is GraphQL-only and models people as ``users`` — it has **no**
native "crew" concept, so crews remain CRM-managed. This package therefore
syncs technicians from Jobber ``users`` and only *ensures* a local default crew
exists to slot new technicians into; it never creates or deletes crews from
Jobber data.

Modules:

- :mod:`app.services.jobber.client` — async GraphQL client (auth, pagination).
- :mod:`app.services.jobber.mapping` — pure Jobber-user → technician mapping.
- :mod:`app.services.jobber.sync` — idempotent, workspace-scoped upsert.
- :mod:`app.services.jobber.cli` — ``jobber-sync`` command entrypoint.
"""

from app.services.jobber.client import JobberApiError, JobberClient
from app.services.jobber.mapping import EXTERNAL_SOURCE, jobber_user_to_technician_data
from app.services.jobber.sync import JobberSyncResult, JobberTechnicianSync

__all__ = [
    "EXTERNAL_SOURCE",
    "JobberApiError",
    "JobberClient",
    "JobberSyncResult",
    "JobberTechnicianSync",
    "jobber_user_to_technician_data",
]
