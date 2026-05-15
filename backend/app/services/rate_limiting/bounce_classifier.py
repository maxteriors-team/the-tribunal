"""Classify Telnyx error codes into bounce types."""

from app.models.conversation import BounceType


class BounceClassifier:
    """Classify carrier error codes into bounce categories.

    Telnyx error codes are mapped to:
    - hard: Permanent failures (invalid number, carrier block)
    - soft: Temporary failures (queue overflow, timeout)
    - spam_complaint: Spam-related blocks
    """

    # Telnyx error codes for hard bounces (permanent failures)
    HARD_BOUNCE_CODES: set[str] = {
        "30004",  # Invalid phone number
        "30006",  # Landline or unreachable carrier
        "30007",  # Carrier violation
        "30008",  # Unknown error (often invalid number)
        "40002",  # Opted out / unsubscribed
        "40301",  # Number ported away
    }

    # Soft bounce codes (temporary failures)
    SOFT_BOUNCE_CODES: set[str] = {
        "30001",  # Queue overflow
        "30002",  # Account suspended
        "30003",  # Unreachable destination
        "30005",  # Unknown destination
        "40101",  # Message blocked (temporary)
        "40201",  # Carrier timeout
    }

    # Spam complaint indicators
    SPAM_COMPLAINT_CODES: set[str] = {
        "40001",  # Spam block
        "40003",  # Spam reported
    }

    # Category descriptions for human-readable categorization
    ERROR_CATEGORIES: dict[str, str] = {
        "30004": "invalid_number",
        "30006": "landline_unreachable",
        "30007": "carrier_violation",
        "30008": "unknown_error",
        "40001": "spam_block",
        "40002": "opted_out",
        "40003": "spam_reported",
        "40301": "number_ported",
        "30001": "queue_overflow",
        "30002": "account_suspended",
        "30003": "unreachable",
        "30005": "unknown_destination",
        "40101": "blocked_temporary",
        "40201": "carrier_timeout",
    }

    @classmethod
    def classify_error(  # noqa: PLR0911
        cls,
        error_code: str | None,
        error_message: str | None = None,
    ) -> tuple[BounceType | None, str]:
        """Classify error code into bounce type and category.

        Args:
            error_code: Telnyx error code (e.g., "30004")
            error_message: Optional error message for additional context

        Returns:
            Tuple of (bounce_type, bounce_category)
            - bounce_type: "hard", "soft", "spam_complaint", or None
            - bounce_category: Human-readable category name
        """
        if not error_code:
            return None, "unknown"

        # Normalize error code (strip whitespace)
        error_code = error_code.strip()

        # Check spam complaints first (most severe)
        if error_code in cls.SPAM_COMPLAINT_CODES:
            return BounceType.SPAM_COMPLAINT, cls._get_category(error_code)

        # Check hard bounces
        if error_code in cls.HARD_BOUNCE_CODES:
            return BounceType.HARD, cls._get_category(error_code)

        # Check soft bounces
        if error_code in cls.SOFT_BOUNCE_CODES:
            return BounceType.SOFT, cls._get_category(error_code)

        # Check error message for additional classification hints
        if error_message:
            error_lower = error_message.lower()
            if "spam" in error_lower or "block" in error_lower:
                return BounceType.SPAM_COMPLAINT, "content_filtered"
            if "invalid" in error_lower or "not found" in error_lower:
                return BounceType.HARD, "invalid_number"
            if "timeout" in error_lower or "retry" in error_lower:
                return BounceType.SOFT, "temporary_failure"

        # Unknown error
        return None, "unknown"

    @classmethod
    def _get_category(cls, error_code: str) -> str:
        """Map error code to human-readable category.

        Args:
            error_code: Telnyx error code

        Returns:
            Human-readable category name
        """
        return cls.ERROR_CATEGORIES.get(error_code, "unknown")

    @classmethod
    def is_hard_bounce(cls, error_code: str | None) -> bool:
        """Check if error code represents a hard bounce.

        Args:
            error_code: Telnyx error code

        Returns:
            True if hard bounce
        """
        if not error_code:
            return False
        return error_code.strip() in cls.HARD_BOUNCE_CODES

    @classmethod
    def is_spam_complaint(cls, error_code: str | None) -> bool:
        """Check if error code represents a spam complaint.

        Args:
            error_code: Telnyx error code

        Returns:
            True if spam complaint
        """
        if not error_code:
            return False
        return error_code.strip() in cls.SPAM_COMPLAINT_CODES
