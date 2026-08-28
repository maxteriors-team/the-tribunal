"""Branded HTML email layout — one shell every outbound email is rendered into.

Before this module each sender in :mod:`app.services.email` hand-rolled its own
markup, so the product's email looked like six different companies: generic
greys (``#333`` on white, ``#1a1a1a`` links, ``#eee`` rules) that matched
neither the dashboard nor each other, with no plain-text part and no shared
notion of a footer. This renders every message from the same tokens as the
frontend (``frontend/src/app/globals.css``): amber ``#ffb90a`` on near-black
``#0a0a0a``.

Why the markup looks dated
--------------------------
Email clients are not browsers. Outlook renders through Word, Gmail strips
``<style>`` blocks in some contexts, and neither flexbox nor grid can be relied
on. So: **tables for layout, inline CSS for everything, opaque hex only**. The
design tokens are ``rgba()`` in the app and are flattened to their composited
hex here, because ``rgba()`` silently degrades to black in older clients.

Categories are a compliance boundary, not a style
-------------------------------------------------
:class:`EmailCategory` decides whether a footer carries an unsubscribe link, and
:func:`render_email` **refuses to render** a marketing email without one. That
is deliberate: CAN-SPAM requires a working opt-out in commercial mail, and a
multi-step nurture sequence is commercial in substance no matter which internal
service sends it. It is equally deliberate that transactional mail does *not*
get one — offering to unsubscribe from a booking confirmation or a password
reset is both wrong and confusing, and can suppress mail the customer needs.
The category is therefore a required argument with no default; picking one is a
decision each caller has to make consciously.

Not legal advice — an engineering control on the path that sends the mail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from html import escape as html_escape
from typing import Literal

__all__ = [
    "BRAND",
    "Brand",
    "Button",
    "Callout",
    "Details",
    "Divider",
    "EmailCategory",
    "Paragraph",
    "RenderedEmail",
    "list_unsubscribe_headers",
    "render_email",
]


class EmailCategory(StrEnum):
    """Whether a message is a service message or a commercial one.

    ``TRANSACTIONAL`` is mail the customer's own action asked for: a booking
    confirmation, a receipt, a password reset, an invoice. ``MARKETING`` is mail
    the business decided to send: nurture sequences, reactivation campaigns,
    offers, anything a workflow fires at a list.
    """

    TRANSACTIONAL = "transactional"
    MARKETING = "marketing"


@dataclass(frozen=True)
class Brand:
    """Palette and identity for one workspace's mail.

    Defaults mirror ``globals.css``. ``rgba()`` tokens are pre-flattened against
    the page background: ``--border: rgba(10,10,10,0.1)`` over ``#fafafa``
    composites to ``#e2e2e2``, and ``--card: rgba(255,255,255,0.9)`` to
    effectively white.
    """

    business_name: str = "Maxteriors"
    # --primary / --primary-foreground. The amber is sampled from the logo
    # (maxteriorslighting.com), so mail, the proposal page and the mark agree.
    primary: str = "#fcb400"
    on_primary: str = "#0a0a0a"
    # --background / --foreground
    background: str = "#fafafa"
    foreground: str = "#0a0a0a"
    # --card (flattened)
    surface: str = "#ffffff"
    # --muted-foreground
    muted_foreground: str = "#71717a"
    # --border (flattened)
    border: str = "#e2e2e2"
    # --success / --destructive / --warning
    success: str = "#0fa66e"
    destructive: str = "#f24d4d"
    warning: str = "#d97706"
    # Optional identity shown in the footer. CAN-SPAM requires a physical
    # postal address in commercial mail; when absent the footer simply omits
    # the line rather than inventing one.
    postal_address: str | None = None
    website_url: str | None = None
    logo_url: str | None = None


BRAND = Brand()

# --radius: 0.625rem
RADIUS = "10px"
CONTENT_WIDTH = "600px"

# Webfonts do not load reliably in mail clients, so the brand face is named
# first and falls back to the platform UI stack that most closely matches.
# Golos Text is a geometric grotesque, so the fallbacks are the closest
# always-present equivalents rather than a serif that would reflow the layout.
_FONT_BODY = (
    "'Golos Text', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
# One family for both roles, matching the app and the proposal page: weight
# carries the display/UI distinction, not a second typeface.
_FONT_HEADING = _FONT_BODY

# Mirrors app.services.email._BARE_URL_RE — the character class excludes the
# quote/angle characters that could otherwise close an href early.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"'`]+")
_URL_TRAILING_PUNCT = ".,;:!?)]}'\""


# --------------------------------------------------------------------------- #
# Content blocks                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Paragraph:
    """A run of operator or system copy. Escaped; bare URLs become links."""

    text: str
    muted: bool = False


@dataclass(frozen=True)
class Details:
    """Label/value rows — appointment facts, lead details, invoice lines."""

    rows: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Button:
    """A single call to action. Rendered table-based so Outlook honours it."""

    label: str
    url: str


@dataclass(frozen=True)
class Callout:
    """A tinted panel for the one thing that matters (a code, a total)."""

    text: str
    tone: Literal["neutral", "success", "warning", "destructive"] = "neutral"


@dataclass(frozen=True)
class Divider:
    """A horizontal rule."""


Block = Paragraph | Details | Button | Callout | Divider


@dataclass(frozen=True)
class RenderedEmail:
    """Both MIME parts of a message.

    A plain-text alternative is not optional in practice: sending HTML alone is
    a well-known spam signal and leaves text-only clients with an empty message.
    Nothing in this product produced one before.
    """

    html: str
    text: str


# --------------------------------------------------------------------------- #
# Escaping helpers                                                             #
# --------------------------------------------------------------------------- #


def _linkify(text: str, *, color: str) -> str:
    """HTML-escape copy and turn bare URLs into anchors.

    Every segment is escaped, so operator text can never inject markup and a
    URL's ``&`` becomes ``&amp;`` inside the href — valid HTML the client
    decodes back to a single ``&``.
    """
    parts: list[str] = []
    cursor = 0
    for match in _BARE_URL_RE.finditer(text):
        parts.append(html_escape(text[cursor : match.start()]))
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _URL_TRAILING_PUNCT:
            trailing = url[-1] + trailing
            url = url[:-1]
        if url:
            safe_url = html_escape(url, quote=True)
            parts.append(
                f'<a href="{safe_url}" style="color:{color};text-decoration:underline;">'
                f"{safe_url}</a>"
            )
        parts.append(html_escape(trailing))
        cursor = match.end()
    parts.append(html_escape(text[cursor:]))
    return "".join(parts)


def _safe_url(url: str) -> str:
    """Escape a URL for an ``href``, rejecting non-HTTP schemes.

    Operator-authored and template-substituted URLs reach this. Anything that is
    not http(s) — ``javascript:`` above all — is replaced with ``#`` rather than
    rendered, so a stored template cannot become a script vector in whichever
    webmail client happens to allow it.
    """
    cleaned = (url or "").strip()
    if not cleaned.lower().startswith(("http://", "https://")):
        return "#"
    return html_escape(cleaned, quote=True)


# --------------------------------------------------------------------------- #
# Block rendering                                                              #
# --------------------------------------------------------------------------- #


def _render_paragraph(block: Paragraph, brand: Brand) -> str:
    color = brand.muted_foreground if block.muted else brand.foreground
    size = "14px" if block.muted else "16px"
    body = _linkify(block.text, color=brand.foreground).replace("\n", "<br>")
    return (
        f'<p style="margin:0 0 16px;font-family:{_FONT_BODY};font-size:{size};'
        f'line-height:1.6;color:{color};">{body}</p>'
    )


def _render_details(block: Details, brand: Brand) -> str:
    if not block.rows:
        return ""
    rows = []
    for label, value in block.rows.items():
        rows.append(
            "<tr>"
            f'<td style="padding:0 0 4px;font-family:{_FONT_BODY};font-size:12px;'
            f"font-weight:600;letter-spacing:0.04em;text-transform:uppercase;"
            f'color:{brand.muted_foreground};">{html_escape(str(label))}</td>'
            "</tr>"
            "<tr>"
            f'<td style="padding:0 0 16px;font-family:{_FONT_BODY};font-size:16px;'
            f'line-height:1.5;color:{brand.foreground};">'
            f"{_linkify(str(value), color=brand.foreground)}</td>"
            "</tr>"
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background-color:{brand.background};border:1px solid '
        f'{brand.border};border-radius:{RADIUS};margin:0 0 20px;">'
        '<tr><td style="padding:20px 20px 4px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
        f"{''.join(rows)}"
        "</table></td></tr></table>"
    )


def _render_button(block: Button, brand: Brand) -> str:
    # Table-wrapped rather than a styled <a>: Outlook's Word renderer drops
    # padding on inline elements, which collapses the button to bare text.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 20px;"><tr>'
        f'<td align="center" bgcolor="{brand.primary}" style="border-radius:{RADIUS};">'
        f'<a href="{_safe_url(block.url)}" '
        f'style="display:inline-block;padding:13px 28px;font-family:{_FONT_HEADING};'
        f"font-size:15px;font-weight:700;line-height:1;color:{brand.on_primary};"
        f'text-decoration:none;border-radius:{RADIUS};">{html_escape(block.label)}</a>'
        "</td></tr></table>"
    )


def _render_callout(block: Callout, brand: Brand) -> str:
    accent = {
        "neutral": brand.primary,
        "success": brand.success,
        "warning": brand.warning,
        "destructive": brand.destructive,
    }[block.tone]
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background-color:{brand.background};border-left:3px solid '
        f'{accent};border-radius:{RADIUS};margin:0 0 20px;"><tr>'
        f'<td style="padding:16px 18px;font-family:{_FONT_BODY};font-size:16px;'
        f'line-height:1.5;color:{brand.foreground};">'
        f"{_linkify(block.text, color=brand.foreground)}</td>"
        "</tr></table>"
    )


def _render_divider(brand: Brand) -> str:
    return (
        f'<div style="border-top:1px solid {brand.border};font-size:0;line-height:0;'
        'margin:0 0 20px;">&nbsp;</div>'
    )


def _render_block(block: Block, brand: Brand) -> str:
    if isinstance(block, Paragraph):
        return _render_paragraph(block, brand)
    if isinstance(block, Details):
        return _render_details(block, brand)
    if isinstance(block, Button):
        return _render_button(block, brand)
    if isinstance(block, Callout):
        return _render_callout(block, brand)
    return _render_divider(brand)


# --------------------------------------------------------------------------- #
# Plain-text rendering                                                         #
# --------------------------------------------------------------------------- #


def _block_to_text(block: Block) -> str:
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Details):
        return "\n".join(f"{label}: {value}" for label, value in block.rows.items())
    if isinstance(block, Button):
        return f"{block.label}: {block.url}"
    if isinstance(block, Callout):
        return block.text
    return "---"


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def list_unsubscribe_headers(unsubscribe_url: str) -> dict[str, str]:
    """``List-Unsubscribe`` headers for a marketing send.

    Gmail and Yahoo require one-click unsubscribe for bulk senders, and the
    header is what puts the native "Unsubscribe" control next to the sender
    name. ``One-Click`` tells the mailbox provider it may POST the URL without
    the customer confirming, so the endpoint must treat a POST as a real
    opt-out.
    """
    return {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def render_email(
    *,
    category: EmailCategory,
    heading: str,
    blocks: list[Block],
    brand: Brand = BRAND,
    preheader: str | None = None,
    unsubscribe_url: str | None = None,
    footer_note: str | None = None,
) -> RenderedEmail:
    """Render one email into the shared branded shell.

    Args:
        category: Service message or commercial message. Marketing mail
            **must** supply ``unsubscribe_url``.
        heading: The h1 shown above the content.
        blocks: Body content, rendered in order.
        brand: Palette and identity; defaults to the product's own.
        preheader: The grey preview line mail clients show after the subject.
            Falls back to the first paragraph, because leaving it empty makes
            clients scrape raw markup into the preview instead.
        unsubscribe_url: One-click opt-out link. Required for marketing.
        footer_note: Extra line above the footer rule (e.g. why they got this).

    Raises:
        ValueError: If a marketing email has no unsubscribe URL. Failing the
            send is the intended behaviour — the alternative is quietly
            shipping non-compliant commercial mail to a customer list.
    """
    if category is EmailCategory.MARKETING and not (unsubscribe_url or "").strip():
        raise ValueError(
            "Marketing email requires an unsubscribe_url (CAN-SPAM). "
            "Use EmailCategory.TRANSACTIONAL for service messages such as "
            "receipts, booking confirmations and password resets."
        )

    # Preview text: first paragraph unless the caller wrote one.
    if preheader is None:
        preheader = next(
            (b.text for b in blocks if isinstance(b, Paragraph) and b.text.strip()),
            "",
        )

    body_html = "".join(_render_block(block, brand) for block in blocks)

    # The header band has to contrast with the logo drawn on it. Ours is built
    # for dark surfaces — amber wordmark over white "EXTERIOR LIGHTING" — so a
    # white band swallows half of it and the primary yellow band swallows the
    # other half. The ink band matches the client proposal page these emails
    # link to (`--black: #0a0a0a`), with the primary kept as the rule beneath.
    # Without a logo the wordmark is set in text on the primary band as before.
    logo_html = ""
    header_background = brand.primary
    header_rule = ""
    if brand.logo_url:
        header_background = brand.foreground
        header_rule = f"border-bottom:4px solid {brand.primary};"
        logo_html = (
            f'<img src="{_safe_url(brand.logo_url)}" alt="{html_escape(brand.business_name)}" '
            'height="34" style="display:block;border:0;height:34px;max-height:34px;">'
        )
    else:
        logo_html = (
            f'<span style="font-family:{_FONT_HEADING};font-size:18px;font-weight:800;'
            f'letter-spacing:-0.01em;color:{brand.on_primary};">'
            f"{html_escape(brand.business_name)}</span>"
        )

    footer_lines: list[str] = []
    if footer_note:
        footer_lines.append(html_escape(footer_note))
    if brand.postal_address:
        footer_lines.append(html_escape(brand.postal_address))
    if brand.website_url:
        safe_site = _safe_url(brand.website_url)
        footer_lines.append(
            f'<a href="{safe_site}" style="color:{brand.muted_foreground};">'
            f"{html_escape(brand.website_url)}</a>"
        )
    if unsubscribe_url:
        safe_unsub = _safe_url(unsubscribe_url)
        footer_lines.append(
            "Don't want these emails? "
            f'<a href="{safe_unsub}" style="color:{brand.muted_foreground};'
            'text-decoration:underline;">Unsubscribe</a>.'
        )

    footer_html = (
        f'<p style="margin:0;font-family:{_FONT_BODY};font-size:12px;line-height:1.6;'
        f'color:{brand.muted_foreground};">{"<br>".join(footer_lines)}</p>'
        if footer_lines
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{html_escape(heading)}</title>
</head>
<body style="margin:0;padding:0;width:100%;background-color:{brand.background};">
<div style="display:none;font-size:1px;color:{brand.background};line-height:1px;\
max-height:0;max-width:0;opacity:0;overflow:hidden;">{html_escape(preheader)}\
{"&#847;&zwnj;&nbsp;" * 40}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" \
style="background-color:{brand.background};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" \
style="max-width:{CONTENT_WIDTH};">

<tr><td style="padding:0 0 16px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" \
style="background-color:{header_background};border-radius:{RADIUS};{header_rule}">
<tr><td style="padding:16px 20px;">{logo_html}</td></tr>
</table>
</td></tr>

<tr><td style="background-color:{brand.surface};border:1px solid {brand.border};\
border-radius:{RADIUS};padding:28px 24px 12px;">
<h1 style="margin:0 0 16px;font-family:{_FONT_HEADING};font-size:22px;line-height:1.3;\
font-weight:800;letter-spacing:-0.02em;color:{brand.foreground};">{html_escape(heading)}</h1>
{body_html}
</td></tr>

<tr><td style="padding:20px 20px 0;">
{footer_html}
</td></tr>

</table>
</td></tr></table>
</body>
</html>"""

    # Joined with a blank line between parts, so empties are dropped rather than
    # used as spacers — an empty block (e.g. Details({})) would otherwise open a
    # ragged gap in the plain-text part.
    text_parts = [heading]
    text_parts.extend(_block_to_text(block) for block in blocks)
    if footer_note:
        text_parts.append(footer_note)
    if brand.postal_address:
        text_parts.append(brand.postal_address)
    if unsubscribe_url:
        text_parts.append(f"Unsubscribe: {unsubscribe_url}")
    text = "\n\n".join(part.strip() for part in text_parts if part and part.strip()) + "\n"

    return RenderedEmail(html=html, text=text)
