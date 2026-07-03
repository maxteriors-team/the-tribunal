"""Integration endpoint package.

Exposes the credential-management router as ``router`` for backward
compatibility with existing imports.
"""

from app.api.v1.integrations.credentials import router

__all__ = ["router"]
