"""Render the signed agreement PDF from the shared email template.

**One source of truth for layout.** The agreement is composed as the same
:class:`~app.services.email_layout.Block` list the confirmation email uses and
rendered through the same :func:`~app.services.email_layout.render_email` shell,
so the document the customer receives as an attachment and the mail it arrives
in cannot drift apart. Only print chrome — page size, margins, and the per-page
legal footer, none of which exist in email — is added here, as an extra
stylesheet layered over that HTML.

**Escaping.** Every block type in ``email_layout`` HTML-escapes its own content,
so the customer's typed name and the operator's terms text reach this module as
data and cannot inject markup into the document. Nothing here concatenates raw
input into HTML; the only interpolation is into the CSS footer string, which is
built from a module constant.

**Import cost.** ``weasyprint`` pulls Pango through CFFI at import time (~0.5s,
and it raises ``OSError`` outright when the system libraries are missing), so it
is imported lazily inside :func:`render_pdf` rather than at module scope. That
keeps the API's cold start and, more importantly, keeps a library-less
environment from breaking imports for every caller that never renders a PDF.
"""

from __future__ import annotations

import structlog

from app.services.email_layout import Block, Brand, EmailCategory, render_email

__all__ = ["ESIGN_FOOTER_TEXT", "AgreementRenderError", "render_pdf"]

logger = structlog.get_logger()

# Printed at the foot of every page. The E-SIGN Act (15 U.S.C. ch. 96) is
# federal; Michigan's UETA is the Uniform Electronic Transactions Act as adopted
# at MCL 450.831 et seq. Both are named because E-SIGN defers to a conforming
# state act, and this business operates in Michigan.
ESIGN_FOOTER_TEXT = "Signed electronically under the E-SIGN Act and Michigan UETA."


class AgreementRenderError(RuntimeError):
    """Rendering the agreement PDF failed.

    Raised for a missing system library as well as a malformed document, so the
    approval flow has exactly one exception type to treat as non-fatal.
    """


# Print-only stylesheet. `@bottom-center` is a CSS Paged Media margin box: it
# repeats on every generated page, which a `<footer>` element in the body cannot
# do. Content is a CSS string literal, so the quote/backslash escape below is
# what keeps it from terminating the declaration early.
def _print_css(footer_text: str) -> str:
    escaped = footer_text.replace("\\", "\\\\").replace('"', '\\"')
    return f"""
    @page {{
        size: Letter;
        margin: 18mm 16mm 22mm 16mm;
        @bottom-center {{
            content: "{escaped}";
            font-family: Helvetica, Arial, sans-serif;
            font-size: 8pt;
            color: #71717a;
            padding-top: 6mm;
        }}
        @bottom-right {{
            content: counter(page) " / " counter(pages);
            font-family: Helvetica, Arial, sans-serif;
            font-size: 8pt;
            color: #71717a;
            padding-top: 6mm;
        }}
    }}
    /* The email shell centres a fixed-width table against a tinted page
       background. On paper that reads as a screenshot of an email, so the
       background is dropped and the container is allowed to use the page. */
    body {{ background: #ffffff !important; }}
    table[role="presentation"] {{ max-width: 100% !important; }}
    /* Keep a section heading attached to what it introduces: a heading stranded
       at the foot of a page makes the certificate hard to read as evidence. */
    h1, h2, h3 {{ break-after: avoid; }}
    /* Deliberately NO blanket `tr {{ break-inside: avoid }}`. The email shell
       nests the entire content card inside one table row, so that rule turns the
       whole document into a single unbreakable block: it gets pushed to a fresh
       page (leaving page 1 blank) and overflows anyway.

       Instead only a Details label row is pinned to the value row that follows
       it, so a break never lands between a field name and its value. */
    tr.detail-label {{ break-after: avoid; }}
    p {{ orphans: 2; widows: 2; }}
    """


def render_pdf(*, heading: str, blocks: list[Block], brand: Brand) -> bytes:
    """Render agreement blocks to PDF bytes through the shared email template.

    Args:
        heading: The document's h1.
        blocks: Agreement content, already escaped by the block types.
        brand: The workspace's palette, so the PDF and the proposal page the
            customer accepted on carry one identity.

    Returns:
        The complete PDF file as bytes.

    Raises:
        AgreementRenderError: If WeasyPrint's system libraries are unavailable
            or the render fails. Callers treat this as non-fatal — see
            :mod:`app.services.quotes.agreement_document`.
    """
    try:
        # Imported lazily on purpose -- see the module docstring.
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as exc:
        # OSError here is the missing-Pango case, which looks like a code bug but
        # is a deployment one. Name it explicitly so the log points at the fix.
        raise AgreementRenderError(
            "WeasyPrint is unavailable; check the Pango/HarfBuzz system libraries "
            "in backend/Dockerfile and backend/nixpacks.toml"
        ) from exc

    rendered = render_email(
        category=EmailCategory.TRANSACTIONAL,
        heading=heading,
        blocks=blocks,
        brand=brand,
        # The shell falls back to the first paragraph for the mail preview line;
        # a PDF has no preview, and leaving it to guess puts stray copy in the
        # document's own metadata.
        preheader=heading,
    )

    try:
        # base_url=None: the document must not be able to fetch anything. The
        # markup is ours and references no external assets, and refusing to
        # resolve relative URLs keeps a future template edit from turning PDF
        # generation into an outbound request from the API host.
        document = HTML(string=rendered.html, base_url=None)
        pdf = document.write_pdf(stylesheets=[CSS(string=_print_css(ESIGN_FOOTER_TEXT))])
    # Broad by design: WeasyPrint raises a wide range of exception types and
    # every one of them must surface as AgreementRenderError.
    except Exception as exc:
        raise AgreementRenderError(f"agreement render failed: {exc}") from exc

    if not pdf:
        raise AgreementRenderError("agreement render produced no bytes")
    return bytes(pdf)
