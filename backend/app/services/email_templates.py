"""Turn a stored :class:`~app.models.email_template.EmailTemplate` into email.

The one job here is converting persisted block dicts into the block objects
:func:`app.services.email_layout.render_email` understands, substituting
``{placeholder}`` tokens on the way through.

Unknown placeholders are left visible (``{booking_url}`` renders as literal
``{booking_url}``) rather than blanked. A blank looks like intentional copy and
ships a sentence with a hole in it; the visible token looks like the mistake it
is, in the preview, before anything is sent.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from app.services.email_layout import (
    BRAND,
    Block,
    Brand,
    Button,
    Callout,
    Details,
    Divider,
    EmailCategory,
    Paragraph,
    RenderedEmail,
    render_email,
)

__all__ = ["blocks_from_stored", "render_template", "substitute"]

logger = structlog.get_logger()

# Matches {token} with no nesting or whitespace, matching the SMS/email
# renderers already in the automation worker.
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def substitute(text: str, values: dict[str, str]) -> str:
    """Replace ``{token}`` with ``values[token]``; leave unknown tokens intact."""
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        return match.group(0) if value is None else str(value)

    return _PLACEHOLDER_RE.sub(_replace, text)


def blocks_from_stored(
    stored: list[dict[str, Any]] | None,
    values: dict[str, str] | None = None,
) -> list[Block]:
    """Convert persisted block dicts into renderable blocks.

    Unknown or malformed entries are skipped with a warning rather than raising:
    a template saved by an older client must not take down the send path for
    every other template in the workspace.
    """
    if not stored:
        return []

    subs = values or {}
    blocks: list[Block] = []

    for raw in stored:
        if not isinstance(raw, dict):
            continue
        block_type = str(raw.get("type", "")).strip().lower()

        if block_type == "paragraph":
            blocks.append(
                Paragraph(
                    text=substitute(str(raw.get("text", "")), subs),
                    muted=bool(raw.get("muted", False)),
                )
            )
        elif block_type == "details":
            rows = raw.get("rows")
            if isinstance(rows, dict):
                blocks.append(
                    Details(
                        {
                            substitute(str(label), subs): substitute(str(value), subs)
                            for label, value in rows.items()
                        }
                    )
                )
        elif block_type == "button":
            blocks.append(
                Button(
                    label=substitute(str(raw.get("label", "")), subs),
                    url=substitute(str(raw.get("url", "")), subs),
                )
            )
        elif block_type == "callout":
            tone = str(raw.get("tone", "neutral")).strip().lower()
            if tone not in ("neutral", "success", "warning", "destructive"):
                tone = "neutral"
            blocks.append(
                Callout(
                    text=substitute(str(raw.get("text", "")), subs),
                    tone=tone,  # type: ignore[arg-type]
                )
            )
        elif block_type == "divider":
            blocks.append(Divider())
        else:
            logger.warning("email_template_unknown_block", block_type=block_type)

    return blocks


def render_template(
    *,
    subject: str,
    heading: str | None,
    preheader: str | None,
    blocks: list[dict[str, Any]] | None,
    category: str,
    values: dict[str, str] | None = None,
    brand: Brand | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, RenderedEmail]:
    """Render a template to ``(subject, RenderedEmail)``.

    Raises :class:`ValueError` when a marketing template has no working
    unsubscribe URL — the layout enforces that, and this deliberately does not
    catch it, so a preview surfaces the problem while the operator is still
    editing rather than at send time.
    """
    subs = values or {}
    resolved_subject = substitute(subject, subs)

    rendered = render_email(
        category=EmailCategory(category),
        heading=substitute(heading or subject, subs),
        blocks=blocks_from_stored(blocks, subs),
        brand=brand if brand is not None else BRAND,
        preheader=substitute(preheader, subs) if preheader else None,
        unsubscribe_url=unsubscribe_url,
    )
    return resolved_subject, rendered
