"""Calendar utilities for Cal.com integration."""

from urllib.parse import urlencode

import structlog

logger = structlog.get_logger()


def generate_booking_url(
    event_type_id: int,
    contact_email: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    workspace_slug: str | None = None,
) -> str:
    """Generate a Cal.com booking URL with pre-filled contact information.

    Args:
        event_type_id: Cal.com event type ID
        contact_email: Contact's email for pre-filling
        contact_name: Contact's name for pre-filling
        contact_phone: Contact's phone number for pre-filling
        workspace_slug: Cal.com workspace slug (defaults to 'cal.com')

    Returns:
        Cal.com public booking URL with pre-filled parameters

    Example:
        >>> url = generate_booking_url(
        ...     event_type_id=123456,
        ...     contact_email="john@example.com",
        ...     contact_name="John Doe",
        ...     contact_phone="+15551234567",
        ... )
        >>> url
        'https://cal.com/event/123456?email=john%40example.com&name=John+Doe&phone=%2B15551234567'
    """
    if workspace_slug and workspace_slug != "cal":
        # Use workspace-specific booking page
        base_url = f"https://cal.com/{workspace_slug}/{event_type_id}"
    else:
        # Use public event type ID-based booking
        base_url = f"https://cal.com/event/{event_type_id}"

    # Build query parameters
    params: dict[str, str] = {}

    if contact_email:
        params["email"] = contact_email

    if contact_name:
        params["name"] = contact_name

    if contact_phone:
        params["phone"] = contact_phone

    # Add parameters to URL if any exist
    if params:
        query_string = urlencode(params)
        return f"{base_url}?{query_string}"

    return base_url
