"""HTML templates for physical postcards."""

_FRONT_STYLE = (
    "width:6in;height:4in;display:flex;align-items:center;"
    "justify-content:center;font-family:Georgia,serif;"
)
_BACK_STYLE = (
    "width:6in;height:4in;padding:0.5in;font-family:Georgia,serif;font-size:14px;color:#1f2937;"
)

CARD_TEMPLATES: dict[str, dict[str, str]] = {
    "birthday": {
        "front": (
            f'<html><body style="{_FRONT_STYLE}background:#fef3c7;">'
            '<h1 style="font-size:36px;color:#92400e;">'
            "Happy Birthday! &#127874;</h1></body></html>"
        ),
        "back": (
            f'<html><body style="{_BACK_STYLE}">'
            "<p>Happy Birthday, {first_name}!</p>"
            "<p>Wishing you a wonderful year ahead filled with "
            "joy and success.</p>"
            '<p style="margin-top:1in;">Warmly,<br/>'
            "{from_name}</p></body></html>"
        ),
    },
    "anniversary": {
        "front": (
            f'<html><body style="{_FRONT_STYLE}background:#ede9fe;">'
            '<h1 style="font-size:36px;color:#5b21b6;">'
            "Happy Anniversary! &#128141;</h1></body></html>"
        ),
        "back": (
            f'<html><body style="{_BACK_STYLE}">'
            "<p>Happy Anniversary, {first_name}!</p>"
            "<p>Here's to many more wonderful years ahead.</p>"
            '<p style="margin-top:1in;">Best wishes,<br/>'
            "{from_name}</p></body></html>"
        ),
    },
    "default": {
        "front": (
            f'<html><body style="{_FRONT_STYLE}background:#f0fdf4;">'
            '<h1 style="font-size:36px;color:#166534;">'
            "Thinking of You</h1></body></html>"
        ),
        "back": (
            f'<html><body style="{_BACK_STYLE}">'
            "<p>Hi {first_name},</p>"
            "<p>Just wanted to reach out and let you know "
            "I'm thinking of you.</p>"
            '<p style="margin-top:1in;">All the best,<br/>'
            "{from_name}</p></body></html>"
        ),
    },
}


def render_template(template_key: str, first_name: str, from_name: str) -> tuple[str, str]:
    """Render a card template with variable substitution.

    Returns (front_html, back_html).
    """
    tmpl = CARD_TEMPLATES.get(template_key, CARD_TEMPLATES["default"])
    front = tmpl["front"].format(first_name=first_name, from_name=from_name)
    back = tmpl["back"].format(first_name=first_name, from_name=from_name)
    return front, back
