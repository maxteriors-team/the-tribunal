"""Cal.com integration service for appointment booking and syncing.

Handles:
- Fetching available time slots from Cal.com
- Creating appointments via Cal.com API
- Syncing appointment status changes
- Error handling and retry logic with exponential backoff
"""

from datetime import datetime, timedelta
from typing import Any, cast

import httpx
import structlog

from app.services.providers.http import (
    AsyncProviderHTTPClient,
    HTTPMethod,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRetryPolicy,
    ProviderTransportError,
    parse_retry_after,
)

logger = structlog.get_logger()

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30
_ALLOWED_METHODS = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})


def _parse_retry_after(value: str | None, fallback: float) -> float:
    """Backward-compatible wrapper around the shared Retry-After parser."""
    return parse_retry_after(value, fallback=fallback)


class CalComError(Exception):
    """Base exception for Cal.com API errors."""

    pass


class CalComAuthError(CalComError):
    """Authentication error with Cal.com API."""

    pass


class CalComNotFoundError(CalComError):
    """Resource not found on Cal.com."""

    pass


class CalComRateLimitError(CalComError):
    """Rate limit exceeded on Cal.com API."""

    pass


class CalComService:
    """Cal.com appointment booking and sync service."""

    def __init__(self, api_key: str) -> None:
        """Initialize Cal.com service.

        Args:
            api_key: Cal.com API key for authentication
        """
        self.api_key = api_key
        self.base_url = "https://api.cal.com/v2"
        self.logger = logger.bind(component="calcom_service")
        self._client: AsyncProviderHTTPClient | None = None

    def _build_client(
        self,
        raw_client: httpx.AsyncClient | None = None,
    ) -> AsyncProviderHTTPClient:
        """Build the shared provider HTTP client for Cal.com."""
        return AsyncProviderHTTPClient(
            provider="calcom",
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "cal-api-version": "2024-08-13",
            },
            retry_policy=ProviderRetryPolicy(
                max_attempts=MAX_RETRIES,
                initial_backoff_seconds=float(INITIAL_BACKOFF_SECONDS),
                max_backoff_seconds=float(MAX_BACKOFF_SECONDS),
            ),
            logger=self.logger,
            client=raw_client,
        )

    async def get_client(self) -> AsyncProviderHTTPClient:
        """Get or create the shared provider HTTP client."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_availability(
        self,
        event_type_id: int,
        start_date: datetime,
        end_date: datetime,
        timezone: str = "America/New_York",
    ) -> list[dict[str, Any]]:
        """Get available slots for an event type.

        Args:
            event_type_id: Cal.com event type ID
            start_date: Start of date range for availability
            end_date: End of date range for availability
            timezone: Timezone for availability (IANA format)

        Returns:
            List of available slot dictionaries with 'date' and 'time' keys

        Raises:
            CalComError: If API call fails
        """
        log = self.logger.bind(
            operation="get_availability",
            event_type_id=event_type_id,
            timezone=timezone,
        )

        try:
            # Cal.com API v2 /slots/available expects YYYY-MM-DD for startTime/endTime
            # IMPORTANT: endTime must be > startTime (at least next day) or API returns empty
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            # If same day, extend end to next day (Cal.com quirk)
            if start_str == end_str:
                next_day = end_date + timedelta(days=1)
                end_str = next_day.strftime("%Y-%m-%d")

            params = {
                "eventTypeId": event_type_id,
                "startTime": start_str,
                "endTime": end_str,
                "timeZone": timezone,
            }

            log.info(
                "fetching_availability",
                start=start_str,
                end=end_str,
            )

            response = await self._request_with_retry(
                "GET",
                "/slots/available",
                params=params,
            )

            # Cal.com v2 response structure:
            # {"data": {"slots": {"2024-01-15": [{"time": "2024-01-15T15:00:00.000Z"}, ...]}}}
            slots_data = response.get("data", {}).get("slots", {})

            # Convert to list of slot dicts with date and time
            slots: list[dict[str, Any]] = []
            if isinstance(slots_data, dict):
                for date_key, time_list in slots_data.items():
                    if not isinstance(time_list, list):
                        continue
                    for slot_obj in time_list:
                        # Each slot is {"time": "2024-01-15T15:00:00.000Z"}
                        if isinstance(slot_obj, dict) and "time" in slot_obj:
                            # Parse ISO time to extract date and time components
                            iso_time = slot_obj["time"]
                            # Format: "2024-01-15T15:00:00.000Z"
                            slots.append(
                                {
                                    "date": date_key,
                                    "time": iso_time[11:16],  # Extract "15:00" from ISO
                                    "iso": iso_time,
                                }
                            )
                        elif isinstance(slot_obj, str):
                            # Fallback if it's just a time string
                            slots.append(
                                {
                                    "date": date_key,
                                    "time": slot_obj,
                                }
                            )

            log.info("availability_fetched", slot_count=len(slots))
            return slots

        except CalComError as e:
            log.error("get_availability_failed", error=str(e))
            raise
        except Exception as e:
            log.error("get_availability_unexpected_error", error=str(e))
            raise CalComError(f"Failed to get availability: {str(e)}") from e

    async def create_booking(
        self,
        event_type_id: int,
        contact_email: str,
        contact_name: str,
        start_time: datetime | None = None,
        duration_minutes: int = 30,
        metadata: dict[str, Any] | None = None,
        timezone: str = "America/New_York",
        language: str = "en",
        phone_number: str | None = None,
        start_time_iso: str | None = None,
    ) -> dict[str, Any]:
        """Create an appointment booking on Cal.com.

        Args:
            event_type_id: Cal.com event type ID
            contact_email: Attendee email address
            contact_name: Attendee name
            start_time: Appointment start time as datetime (should be in UTC)
            duration_minutes: Duration in minutes (default 30)
            metadata: Optional metadata to attach to booking
            timezone: Attendee timezone in IANA format (default America/New_York)
            language: Attendee language code (default en)
            phone_number: Optional phone number for SMS reminders
            start_time_iso: Appointment start time as ISO string (used directly,
                takes precedence over start_time)

        Returns:
            Booking confirmation with Cal.com IDs and details

        Raises:
            CalComError: If booking creation fails
        """
        log = self.logger.bind(
            operation="create_booking",
            event_type_id=event_type_id,
            contact_email=contact_email,
        )

        try:
            # Build attendee object with required fields
            attendee: dict[str, Any] = {
                "name": contact_name,
                "email": contact_email,
                "timeZone": timezone,
                "language": language,
            }

            # Add phone number if provided (required for SMS reminders)
            if phone_number:
                attendee["phoneNumber"] = phone_number

            # Resolve start time: prefer ISO string, fall back to datetime
            if start_time_iso:
                start_utc = start_time_iso
            elif start_time:
                start_utc = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            else:
                raise CalComError("Either start_time or start_time_iso is required")

            payload: dict[str, Any] = {
                "eventTypeId": event_type_id,
                "start": start_utc,
                "attendee": attendee,
                "metadata": metadata or {},
            }

            response = await self._request_with_retry(
                "POST",
                "/bookings",
                json=payload,
            )

            log.info(
                "booking_created",
                booking_id=response.get("id"),
                uid=response.get("uid"),
            )

            return response

        except CalComError as e:
            log.error("create_booking_failed", error=str(e), error_type=type(e).__name__)
            raise
        except Exception as e:
            log.error("create_booking_unexpected_error", error=str(e))
            raise CalComError(f"Failed to create booking: {str(e)}") from e

    async def get_booking(self, booking_uid: str) -> dict[str, Any]:
        """Get booking details by UID.

        Args:
            booking_uid: Cal.com booking UID (unique identifier)

        Returns:
            Booking details

        Raises:
            CalComError: If booking fetch fails
        """
        log = self.logger.bind(operation="get_booking", booking_uid=booking_uid)

        try:
            response = await self._request_with_retry(
                "GET",
                f"/bookings/{booking_uid}",
            )

            log.info("booking_fetched", booking_id=response.get("id"))
            return response

        except CalComError as e:
            log.error("get_booking_failed", error=str(e))
            raise
        except Exception as e:
            log.error("get_booking_unexpected_error", error=str(e))
            raise CalComError(f"Failed to get booking: {str(e)}") from e

    async def cancel_booking(self, booking_uid: str, reason: str = "Cancelled by customer") -> bool:
        """Cancel a booking on Cal.com.

        Args:
            booking_uid: Cal.com booking UID
            reason: Cancellation reason

        Returns:
            True if cancellation successful

        Raises:
            CalComError: If cancellation fails
        """
        log = self.logger.bind(operation="cancel_booking", booking_uid=booking_uid)

        try:
            payload = {"reason": reason}

            await self._request_with_retry(
                "DELETE",
                f"/bookings/{booking_uid}",
                json=payload,
            )

            log.info("booking_cancelled")
            return True

        except CalComError as e:
            log.error("cancel_booking_failed", error=str(e))
            raise
        except Exception as e:
            log.error("cancel_booking_unexpected_error", error=str(e))
            raise CalComError(f"Failed to cancel booking: {str(e)}") from e

    def generate_booking_url(
        self,
        event_type_id: int,
        contact_email: str,
        contact_name: str,
        contact_phone: str | None = None,
    ) -> str:
        """Generate a Cal.com booking URL with pre-filled attendee data.

        Args:
            event_type_id: Cal.com event type ID
            contact_email: Attendee email address
            contact_name: Attendee full name
            contact_phone: Optional phone number

        Returns:
            Cal.com booking URL with pre-filled data
        """
        log = self.logger.bind(
            operation="generate_booking_url",
            event_type_id=event_type_id,
            contact_email=contact_email,
        )

        try:
            # Cal.com public booking URL format
            base_url = f"https://cal.com/event/{event_type_id}"

            # Build query parameters for pre-filling
            params = [
                f"name={contact_name}",
                f"email={contact_email}",
            ]

            if contact_phone:
                # Clean phone number - remove common formatting
                phone_clean = "".join(c for c in contact_phone if c.isdigit() or c in "+-")
                params.append(f"phone={phone_clean}")

            url = f"{base_url}?{'&'.join(params)}"
            log.info("booking_url_generated")

            return url

        except Exception as e:
            log.error("generate_url_failed", error=str(e))
            raise CalComError(f"Failed to generate booking URL: {str(e)}") from e

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        client: AsyncProviderHTTPClient | httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a Cal.com HTTP request through the shared provider client.

        ``client`` remains optional for older tests that pre-wire a mock
        ``httpx.AsyncClient``; service methods use the lazily-created shared
        client directly.
        """
        provider_client = await self._coerce_provider_client(client)
        http_method = self._coerce_method(method)
        try:
            return await provider_client.request_json(http_method, url, **kwargs)
        except ProviderAuthError as exc:
            raise CalComAuthError("Invalid API key or authentication failed") from exc
        except ProviderNotFoundError as exc:
            raise CalComNotFoundError("Resource not found on Cal.com") from exc
        except ProviderRateLimitError as exc:
            raise CalComRateLimitError("Rate limit exceeded, max retries reached") from exc
        except ProviderTransportError as exc:
            if exc.code == "timeout":
                raise CalComError(f"Request timeout after {MAX_RETRIES} attempts") from exc
            raise CalComError(f"Network error after {MAX_RETRIES} attempts") from exc
        except ProviderHTTPError as exc:
            raise CalComError(f"API error: {exc.message}") from exc

    async def _coerce_provider_client(
        self,
        client: AsyncProviderHTTPClient | httpx.AsyncClient | None,
    ) -> AsyncProviderHTTPClient:
        """Return a provider client, wrapping raw httpx clients for tests."""
        if client is None:
            return await self.get_client()
        if isinstance(client, AsyncProviderHTTPClient):
            return client
        return self._build_client(raw_client=client)

    @staticmethod
    def _coerce_method(method: str) -> HTTPMethod:
        """Validate and narrow an HTTP method string for the provider client."""
        normalized = method.upper()
        if normalized not in _ALLOWED_METHODS:
            msg = f"Unsupported Cal.com HTTP method: {method}"
            raise CalComError(msg)
        return cast(HTTPMethod, normalized)
