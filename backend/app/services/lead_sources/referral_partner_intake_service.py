"""Public referral-partner intake capabilities, profile updates, and logos."""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, undefer

from app.core.config import settings
from app.models.referral_partner import (
    ReferralPartner,
    ReferralPartnerIntakeStatus,
)
from app.models.referral_partner_intake import ReferralPartnerIntakeLink
from app.models.referral_partner_logo import (
    MAX_REFERRAL_PARTNER_LOGO_BYTES,
    ReferralPartnerLogo,
)
from app.schemas.referral_partner import (
    PublicReferralPartnerIntake,
    PublicReferralPartnerIntakeSubmit,
    ReferralPartnerIntakeLinkResponse,
    ReferralPartnerLogoResponse,
)

INTAKE_LINK_LIFETIME = timedelta(days=30)
_FILENAME_SANITIZE_RE = re.compile(r"[^\w.\- ()]", flags=re.ASCII)


class ReferralPartnerIntakeNotFoundError(Exception):
    """The capability is unusable or the scoped partner does not exist."""


class ReferralPartnerLogoValidationError(Exception):
    """The upload is empty, unsupported, or has mismatched declared content."""


class ReferralPartnerLogoTooLargeError(ReferralPartnerLogoValidationError):
    """The upload exceeds the persisted logo size limit."""


def intake_token_digest(token: str) -> str:
    """Return the lookup/rate-limit digest without persisting the bearer value."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def detect_raster_type(data: bytes) -> str | None:
    """Detect only the three raster formats accepted for partner logos."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize_logo_filename(raw: str | None, content_type: str) -> str:
    """Remove path/header characters and give the file its detected extension."""
    name = (raw or "logo").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = _FILENAME_SANITIZE_RE.sub("_", name)
    stem = name.rsplit(".", 1)[0].strip(". ") or "logo"
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    return f"{stem[: 255 - len(extension)]}{extension}"


class ReferralPartnerIntakeService:
    """Workspace-safe staff controls and token-only anonymous intake operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _scoped_partner(
        self, partner_id: uuid.UUID, workspace_id: uuid.UUID, *, lock: bool = False
    ) -> ReferralPartner:
        query = select(ReferralPartner).where(
            ReferralPartner.id == partner_id,
            ReferralPartner.workspace_id == workspace_id,
        )
        if lock:
            query = query.with_for_update()
        partner = (await self.db.execute(query)).scalar_one_or_none()
        if partner is None:
            raise ReferralPartnerIntakeNotFoundError()
        return partner

    async def _resolve_token(self, token: str) -> tuple[ReferralPartnerIntakeLink, ReferralPartner]:
        """Resolve an active capability while inferring tenant scope from its digest."""
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(ReferralPartnerIntakeLink, ReferralPartner)
            .join(
                ReferralPartner,
                and_(
                    ReferralPartner.id == ReferralPartnerIntakeLink.referral_partner_id,
                    ReferralPartner.workspace_id == ReferralPartnerIntakeLink.workspace_id,
                ),
            )
            .where(
                ReferralPartnerIntakeLink.token_digest == intake_token_digest(token),
                ReferralPartnerIntakeLink.revoked_at.is_(None),
                ReferralPartnerIntakeLink.expires_at > now,
                ReferralPartner.is_active.is_(True),
            )
        )
        row = result.one_or_none()
        if row is None:
            raise ReferralPartnerIntakeNotFoundError()
        return row[0], row[1]

    @staticmethod
    def _link_response(
        link: ReferralPartnerIntakeLink, status: ReferralPartnerIntakeStatus
    ) -> ReferralPartnerIntakeLinkResponse:
        base = settings.frontend_url.rstrip("/")
        return ReferralPartnerIntakeLinkResponse(
            intake_url=f"{base}/p/referral-partners/intake#token={link.token}",
            created_at=link.created_at,
            expires_at=link.expires_at,
            status=status,
        )

    async def issue_link(
        self, partner_id: uuid.UUID, workspace_id: uuid.UUID, *, rotate: bool = False
    ) -> ReferralPartnerIntakeLinkResponse:
        """Create or reuse an active high-entropy capability for one scoped partner."""
        partner = await self._scoped_partner(partner_id, workspace_id, lock=True)
        if not partner.is_active:
            raise ReferralPartnerIntakeNotFoundError()

        now = datetime.now(UTC)
        active_links = list(
            (
                await self.db.execute(
                    select(ReferralPartnerIntakeLink)
                    .where(
                        ReferralPartnerIntakeLink.workspace_id == workspace_id,
                        ReferralPartnerIntakeLink.referral_partner_id == partner_id,
                        ReferralPartnerIntakeLink.revoked_at.is_(None),
                        ReferralPartnerIntakeLink.expires_at > now,
                    )
                    .order_by(ReferralPartnerIntakeLink.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if active_links and not rotate:
            return self._link_response(active_links[0], partner.intake_status)

        for active_link in active_links:
            active_link.revoked_at = now

        token = secrets.token_urlsafe(32)
        link = ReferralPartnerIntakeLink(
            workspace_id=workspace_id,
            referral_partner_id=partner_id,
            token_digest=intake_token_digest(token),
            token=token,
            created_at=now,
            expires_at=now + INTAKE_LINK_LIFETIME,
        )
        self.db.add(link)
        partner.intake_status = ReferralPartnerIntakeStatus.PENDING
        partner.intake_link_created_at = now
        partner.intake_revoked_at = None
        await self.db.flush()
        return self._link_response(link, partner.intake_status)

    async def revoke_link(self, partner_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        """Revoke every live capability for the scoped partner."""
        partner = await self._scoped_partner(partner_id, workspace_id, lock=True)
        now = datetime.now(UTC)
        links = (
            (
                await self.db.execute(
                    select(ReferralPartnerIntakeLink).where(
                        ReferralPartnerIntakeLink.workspace_id == workspace_id,
                        ReferralPartnerIntakeLink.referral_partner_id == partner_id,
                        ReferralPartnerIntakeLink.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            link.revoked_at = now
        partner.intake_status = ReferralPartnerIntakeStatus.REVOKED
        partner.intake_revoked_at = now
        await self.db.flush()

    async def public_prefill(self, token: str) -> PublicReferralPartnerIntake:
        """Return only partner-editable fields; no workspace, CRM, or contact IDs."""
        _, partner = await self._resolve_token(token)
        has_logo = (
            await self.db.scalar(
                select(ReferralPartnerLogo.id).where(
                    ReferralPartnerLogo.workspace_id == partner.workspace_id,
                    ReferralPartnerLogo.referral_partner_id == partner.id,
                )
            )
            is not None
        )
        data = PublicReferralPartnerIntake.model_validate(partner, from_attributes=True)
        return data.model_copy(update={"has_logo": has_logo})

    async def submit(
        self, token: str, payload: PublicReferralPartnerIntakeSubmit
    ) -> PublicReferralPartnerIntake:
        """Update the existing partner in place; repeated submissions are intentional."""
        _, partner = await self._resolve_token(token)
        for key, value in payload.model_dump(mode="python").items():
            setattr(partner, key, value)
        partner.intake_status = ReferralPartnerIntakeStatus.SUBMITTED
        partner.intake_submitted_at = datetime.now(UTC)
        await self.db.flush()
        return await self.public_prefill(token)

    async def upload_logo(
        self, token: str, *, filename: str | None, declared_type: str | None, data: bytes
    ) -> ReferralPartnerLogoResponse:
        """Replace the same partner's logo after auth and strict raster validation."""
        # Resolve first so direct service callers cannot make invalid capabilities
        # spend work on attacker-controlled bytes.
        _, partner = await self._resolve_token(token)
        if not data:
            raise ReferralPartnerLogoValidationError("Uploaded image is empty")
        if len(data) > MAX_REFERRAL_PARTNER_LOGO_BYTES:
            raise ReferralPartnerLogoTooLargeError("Logo exceeds the 2 MB limit")
        content_type = detect_raster_type(data)
        if content_type is None:
            raise ReferralPartnerLogoValidationError("Use a PNG, JPEG, or WebP logo")
        if (declared_type or "").lower() != content_type:
            raise ReferralPartnerLogoValidationError(
                "Declared image type does not match file contents"
            )
        logo = (
            await self.db.execute(
                select(ReferralPartnerLogo)
                .options(
                    load_only(
                        ReferralPartnerLogo.id,
                        ReferralPartnerLogo.filename,
                        ReferralPartnerLogo.content_type,
                        ReferralPartnerLogo.size_bytes,
                        ReferralPartnerLogo.sha256,
                        ReferralPartnerLogo.created_at,
                        ReferralPartnerLogo.updated_at,
                    )
                )
                .where(
                    ReferralPartnerLogo.workspace_id == partner.workspace_id,
                    ReferralPartnerLogo.referral_partner_id == partner.id,
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        values = {
            "filename": sanitize_logo_filename(filename, content_type),
            "content_type": content_type,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "data": data,
            "updated_at": now,
        }
        if logo is None:
            logo = ReferralPartnerLogo(
                workspace_id=partner.workspace_id,
                referral_partner_id=partner.id,
                created_at=now,
                **values,
            )
            self.db.add(logo)
        else:
            for key, value in values.items():
                setattr(logo, key, value)
        await self.db.flush()
        return ReferralPartnerLogoResponse.model_validate(logo)

    async def public_logo(self, token: str) -> ReferralPartnerLogo:
        """Load logo bytes only after the bearer capability is validated."""
        _, partner = await self._resolve_token(token)
        logo = (
            await self.db.execute(
                select(ReferralPartnerLogo)
                .options(undefer(ReferralPartnerLogo.data))
                .where(
                    ReferralPartnerLogo.workspace_id == partner.workspace_id,
                    ReferralPartnerLogo.referral_partner_id == partner.id,
                )
            )
        ).scalar_one_or_none()
        if logo is None:
            raise ReferralPartnerIntakeNotFoundError()
        return logo

    async def authenticated_logo(
        self, partner_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> ReferralPartnerLogo:
        """Load one logo with both partner and logo constrained to the caller's tenant."""
        await self._scoped_partner(partner_id, workspace_id)
        logo = (
            await self.db.execute(
                select(ReferralPartnerLogo)
                .options(undefer(ReferralPartnerLogo.data))
                .where(
                    ReferralPartnerLogo.workspace_id == workspace_id,
                    ReferralPartnerLogo.referral_partner_id == partner_id,
                )
            )
        ).scalar_one_or_none()
        if logo is None:
            raise ReferralPartnerIntakeNotFoundError()
        return logo
