"""The shared branded email shell.

Two things matter most here and both are enforcement, not appearance: marketing
mail cannot render without an opt-out, and no operator-authored string can turn
into markup or a script URL in a customer's inbox.
"""

from __future__ import annotations

import pytest

from app.services.email_layout import (
    BRAND,
    Brand,
    Button,
    Callout,
    Details,
    Divider,
    EmailCategory,
    Paragraph,
    list_unsubscribe_headers,
    render_email,
)


def _render(**overrides):
    kwargs = {
        "category": EmailCategory.TRANSACTIONAL,
        "heading": "Your appointment is confirmed",
        "blocks": [Paragraph("Thanks for booking with us.")],
    }
    kwargs.update(overrides)
    return render_email(**kwargs)


class TestUnsubscribeIsStructural:
    def test_marketing_without_unsubscribe_refuses_to_render(self):
        """The control that makes a non-compliant bulk send impossible."""
        with pytest.raises(ValueError, match="unsubscribe"):
            _render(category=EmailCategory.MARKETING)

    def test_marketing_with_blank_unsubscribe_refuses_to_render(self):
        with pytest.raises(ValueError):
            _render(category=EmailCategory.MARKETING, unsubscribe_url="   ")

    def test_marketing_with_unsubscribe_renders_the_link(self):
        result = _render(
            category=EmailCategory.MARKETING,
            unsubscribe_url="https://app.example.com/unsubscribe?token=abc",
        )
        assert "https://app.example.com/unsubscribe?token=abc" in result.html
        assert "Unsubscribe" in result.html

    def test_transactional_has_no_unsubscribe_by_default(self):
        """Offering to opt out of a receipt suppresses mail people need."""
        assert "Unsubscribe" not in _render().html

    def test_category_has_no_default(self):
        """Each caller must consciously classify its mail."""
        with pytest.raises(TypeError):
            render_email(heading="x", blocks=[])  # type: ignore[call-arg]

    def test_unsubscribe_appears_in_the_text_part_too(self):
        result = _render(
            category=EmailCategory.MARKETING,
            unsubscribe_url="https://app.example.com/u/1",
        )
        assert "https://app.example.com/u/1" in result.text


class TestEscaping:
    def test_operator_copy_cannot_inject_markup(self):
        result = _render(blocks=[Paragraph("<script>alert('xss')</script>")])
        assert "<script>" not in result.html
        assert "&lt;script&gt;" in result.html

    def test_detail_values_are_escaped(self):
        result = _render(blocks=[Details({"Name": "<b>bold</b>"})])
        assert "<b>bold</b>" not in result.html

    def test_detail_labels_are_escaped(self):
        result = _render(blocks=[Details({"<img src=x>": "value"})])
        assert "<img src=x>" not in result.html

    def test_heading_is_escaped(self):
        assert "<em>" not in _render(heading="<em>hi</em>").html

    def test_javascript_button_url_is_neutralised(self):
        """A stored template must not become a script vector."""
        result = _render(blocks=[Button("Click", "javascript:alert(1)")])
        assert "javascript:" not in result.html
        assert 'href="#"' in result.html

    def test_javascript_unsubscribe_url_is_neutralised(self):
        result = _render(
            category=EmailCategory.MARKETING,
            unsubscribe_url="javascript:alert(1)",
        )
        assert "javascript:" not in result.html

    def test_http_button_url_is_preserved(self):
        result = _render(blocks=[Button("Book", "https://cal.example.com/x")])
        assert "https://cal.example.com/x" in result.html

    def test_bare_urls_become_links(self):
        """Gmail renders a bare URL in an HTML part as dead text."""
        result = _render(blocks=[Paragraph("See https://example.com/quote for details.")])
        assert '<a href="https://example.com/quote"' in result.html

    def test_url_query_ampersand_is_encoded(self):
        result = _render(blocks=[Paragraph("https://example.com/a?x=1&y=2")])
        assert "&amp;y=2" in result.html

    def test_trailing_punctuation_is_not_part_of_the_link(self):
        result = _render(blocks=[Paragraph("Go to https://example.com.")])
        assert '<a href="https://example.com"' in result.html


class TestBranding:
    def test_uses_the_app_primary_colour(self):
        # Amber sampled from the logo, shared with the proposal page.
        assert BRAND.primary == "#fcb400"
        assert "#fcb400" in _render().html

    def test_uses_the_brand_typeface_with_a_safe_fallback(self):
        """Mail clients rarely load webfonts, so the stack must degrade sanely.

        Golos Text is named first for the clients that do have it; the rest of
        the stack is the platform grotesque, never a serif, so an unstyled send
        still looks like the same brand rather than a different document.
        """
        html = _render(blocks=[Paragraph("x"), Button("Go", "https://e.com")]).html

        assert "'Golos Text'" in html
        assert "Arial, sans-serif" in html
        # The serif pairing the proposal page dropped must not linger here.
        assert "Cormorant" not in html
        assert "serif;" not in html.replace("sans-serif;", "")

    def test_no_rgba_which_degrades_to_black_in_older_clients(self):
        assert "rgba(" not in _render().html

    def test_no_flex_or_grid_which_outlook_ignores(self):
        html = _render(
            blocks=[Paragraph("x"), Details({"a": "b"}), Button("Go", "https://e.com")]
        ).html
        assert "display:flex" not in html
        assert "display:grid" not in html

    def test_button_is_table_wrapped_for_outlook(self):
        html = _render(blocks=[Button("Book now", "https://example.com")]).html
        assert f'bgcolor="{BRAND.primary}"' in html

    def test_custom_brand_overrides_the_palette(self):
        html = _render(brand=Brand(business_name="Acme Gutters", primary="#00aaff")).html
        assert "Acme Gutters" in html
        assert "#00aaff" in html

    def test_business_name_is_escaped(self):
        html = _render(brand=Brand(business_name="<script>x</script>")).html
        assert "<script>" not in html

    def test_postal_address_renders_when_supplied(self):
        """CAN-SPAM wants a physical address in commercial mail."""
        html = _render(
            category=EmailCategory.MARKETING,
            unsubscribe_url="https://e.com/u",
            brand=Brand(postal_address="123 Main St, Austin TX"),
        ).html
        assert "123 Main St, Austin TX" in html

    def test_absent_address_is_omitted_not_invented(self):
        assert "None" not in _render().html


class TestPreheader:
    def test_defaults_to_the_first_paragraph(self):
        result = _render(blocks=[Paragraph("Your quote is ready to view.")])
        assert "Your quote is ready to view." in result.html

    def test_explicit_preheader_wins(self):
        result = _render(preheader="Custom preview", blocks=[Paragraph("Body copy")])
        assert "Custom preview" in result.html

    def test_preheader_is_escaped(self):
        assert "<script>" not in _render(preheader="<script>x</script>").html


class TestPlainTextPart:
    def test_text_part_is_produced(self):
        """HTML-only sending is a spam signal and breaks text-only clients."""
        result = _render(blocks=[Paragraph("Hello there")])
        assert "Hello there" in result.text
        assert "<" not in result.text

    def test_text_part_includes_heading_and_button_url(self):
        result = _render(
            heading="Quote ready",
            blocks=[Button("View quote", "https://example.com/q/1")],
        )
        assert "Quote ready" in result.text
        assert "https://example.com/q/1" in result.text

    def test_text_part_includes_detail_rows(self):
        result = _render(blocks=[Details({"When": "Monday at 2 PM"})])
        assert "When: Monday at 2 PM" in result.text


class TestBlocks:
    def test_all_block_types_render(self):
        html = _render(
            blocks=[
                Paragraph("intro"),
                Details({"Service": "Gutter clean"}),
                Callout("Total: $450", tone="success"),
                Divider(),
                Button("Approve", "https://example.com/a"),
                Paragraph("Sent by your team", muted=True),
            ]
        ).html
        for expected in ("intro", "Gutter clean", "Total: $450", "Approve"):
            assert expected in html

    def test_empty_details_renders_nothing(self):
        assert _render(blocks=[Details({})]).html.count("<table") == 3

    def test_callout_tone_selects_the_accent_colour(self):
        assert BRAND.destructive in _render(blocks=[Callout("Failed", tone="destructive")]).html


class TestListUnsubscribeHeaders:
    def test_headers_are_wrapped_in_angle_brackets(self):
        headers = list_unsubscribe_headers("https://e.com/u?t=1")
        assert headers["List-Unsubscribe"] == "<https://e.com/u?t=1>"

    def test_one_click_post_header_is_present(self):
        headers = list_unsubscribe_headers("https://e.com/u")
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


class TestHeaderLogo:
    """The header band must never hide the logo it is drawn behind.

    The logo is built for dark surfaces: an amber wordmark above white
    "EXTERIOR LIGHTING". A primary-yellow band swallows the amber, and a white
    band swallows the white line — either way the send looks broken rather than
    branded, so the band is the brand's ink.
    """

    def _header(self, html: str) -> str:
        """Just the masthead. Asserting against the whole document is useless:

        `#ffffff` also appears in the card below, so an unscoped substring check
        passes even when the band is the wrong colour.
        """
        return html.split('<tr><td style="padding:16px 20px;">')[0]

    def test_logo_gets_an_ink_band_with_a_primary_rule(self):
        brand = Brand(logo_url="https://go.example.com/static/brand/maxteriors-logo.png")
        html = _render(brand=brand).html
        header = self._header(html)

        assert f"background-color:{brand.foreground}" in header
        assert f"border-bottom:4px solid {brand.primary}" in header
        # The image itself sits in the cell just past the band markup.
        assert 'src="https://go.example.com/static/brand/maxteriors-logo.png"' in html

    def test_logo_band_is_never_white(self):
        """The white line in the logo would be invisible on a white band."""
        brand = Brand(logo_url="https://go.example.com/static/brand/maxteriors-logo.png")
        header = self._header(_render(brand=brand).html)

        assert f"background-color:{brand.surface}" not in header

    def test_logo_is_never_drawn_on_the_primary_band(self):
        brand = Brand(logo_url="https://go.example.com/static/brand/maxteriors-logo.png")
        html = _render(brand=brand).html

        header = html.split('<tr><td style="padding:16px 20px;">')[0]
        assert f"background-color:{brand.primary}" not in header

    def test_without_a_logo_the_wordmark_keeps_the_primary_band(self):
        brand = Brand(business_name="Maxteriors")
        html = _render(brand=brand).html

        assert f"background-color:{brand.primary}" in html
        assert "Maxteriors" in html

    def test_logo_alt_text_names_the_business(self):
        """An image-blocking client must still show who sent it."""
        brand = Brand(
            business_name="Maxteriors",
            logo_url="https://go.example.com/static/brand/maxteriors-logo.png",
        )
        assert 'alt="Maxteriors"' in _render(brand=brand).html
