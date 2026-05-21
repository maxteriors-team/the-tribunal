"""Shared campaign message template rendering."""

import re

import structlog

from app.models.contact import Contact
from app.models.offer import Offer

logger = structlog.get_logger()


def render_campaign_message(
    template: str,
    contact: Contact,
    offer: Offer | None = None,
) -> str:
    """Render campaign copy with the same placeholders used by campaign workers."""
    try:
        message = template
        full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""

        replacements: dict[str, str] = {
            "first_name": contact.first_name or "",
            "last_name": contact.last_name or "",
            "full_name": full_name,
            "company_name": contact.company_name or "",
            "email": contact.email or "",
        }

        if offer:
            try:
                replacements.update(
                    {
                        "offer_name": offer.name or "",
                        "offer_discount": _format_offer_discount(offer),
                        "offer_description": offer.description or "",
                        "offer_terms": offer.terms or "",
                    }
                )
            except Exception as exc:
                logger.error(
                    "offer_interpolation_error",
                    error=str(exc),
                    offer_id=str(offer.id) if hasattr(offer, "id") else "unknown",
                )

        for placeholder, value in replacements.items():
            try:
                pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
                message = pattern.sub(value, message)
            except Exception as exc:
                logger.warning(
                    "placeholder_replacement_error",
                    placeholder=placeholder,
                    error=str(exc),
                )

        return message
    except Exception as exc:
        logger.error(
            "template_rendering_failed",
            error=str(exc),
            template_length=len(template) if template else 0,
        )
        return template


def _format_offer_discount(offer: Offer) -> str:
    if offer.discount_type == "percentage":
        return f"{offer.discount_value}% off"
    if offer.discount_type == "fixed":
        return f"${offer.discount_value} off"
    if offer.discount_type == "free_service":
        return "Free service"

    logger.warning(
        "unknown_discount_type",
        offer_id=str(offer.id) if hasattr(offer, "id") else "unknown",
        discount_type=offer.discount_type,
    )
    return ""
