#!/usr/bin/env python3
"""
Script to populate your calendar with fake Cal.com bookings for marketing screenshots.

Creates realistic-looking Cal.com video call events that sync to your Google Calendar.

Prerequisites:
- CALCOM_API_KEY environment variable set
- Your Cal.com event type ID

Usage:
    python fake_calendar_bookings.py --event-type-id 123456 [--count 20] [--days 7]
    python fake_calendar_bookings.py --event-type-id 123456 --clear  # Remove fake bookings
"""

import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx

# Realistic names for fake bookings
FIRST_NAMES = [
    "James", "Sarah", "Michael", "Emily", "David", "Jessica", "Robert", "Ashley",
    "William", "Amanda", "Christopher", "Stephanie", "Daniel", "Nicole", "Matthew",
    "Jennifer", "Anthony", "Elizabeth", "Mark", "Megan", "Steven", "Rachel", "Andrew",
    "Lauren", "Joshua", "Samantha", "Kevin", "Katherine", "Brian", "Brittany",
    "Ryan", "Christina", "Jason", "Heather", "Jeffrey", "Michelle", "Eric", "Amber",
    "Carlos", "Maria", "Diego", "Sofia", "Marcus", "Olivia", "Tyler", "Hannah",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]

COMPANIES = [
    "TechFlow Inc", "Apex Solutions", "Quantum Dynamics", "Stellar Systems",
    "Nova Enterprises", "Vertex Labs", "Horizon Digital", "Catalyst Group",
    "Pinnacle Tech", "Summit Partners", "Nexus Corp", "Prime Innovations",
    "Atlas Ventures", "Elevate Co", "Spark Digital", "Maven Solutions",
    "Growth Hub", "Ignite Media", "Thrive Digital", "Pulse Marketing",
]

# Email domains for fake emails
EMAIL_DOMAINS = [
    "gmail.com", "outlook.com", "yahoo.com", "company.com", "business.org",
    "corporate.io", "startup.co", "enterprise.net", "work.email",
]

# Phone number prefixes for fake phones
PHONE_PREFIXES = [
    "+1212", "+1310", "+1415", "+1512", "+1617", "+1713", "+1818", "+1305",
    "+1404", "+1602", "+1720", "+1206", "+1503", "+1619", "+1702", "+1480",
]


class CalComBookingGenerator:
    """Generate fake Cal.com bookings."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.cal.com/v2"
        self.created_booking_uids: list[str] = []

    async def get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "cal-api-version": "2024-08-13",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def generate_fake_attendee(self) -> dict:
        """Generate a realistic fake attendee."""
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        domain = random.choice(EMAIL_DOMAINS)

        # Create email from name
        email_formats = [
            f"{first_name.lower()}.{last_name.lower()}@{domain}",
            f"{first_name.lower()}{last_name.lower()}@{domain}",
            f"{first_name[0].lower()}{last_name.lower()}@{domain}",
        ]
        email = random.choice(email_formats)

        # Generate a fake phone number
        prefix = random.choice(PHONE_PREFIXES)
        phone = f"{prefix}{random.randint(1000000, 9999999)}"

        return {
            "name": f"{first_name} {last_name}",
            "email": email,
            "phone": phone,
            "company": random.choice(COMPANIES),
        }

    async def get_available_slots(
        self,
        client: httpx.AsyncClient,
        event_type_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[str]:
        """Fetch available slots from Cal.com."""
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Ensure end is after start
        if start_str == end_str:
            next_day = end_date + timedelta(days=1)
            end_str = next_day.strftime("%Y-%m-%d")

        params = {
            "eventTypeId": event_type_id,
            "startTime": start_str,
            "endTime": end_str,
        }

        response = await client.get(f"{self.base_url}/slots/available", params=params)

        if response.status_code != 200:
            print(f"Error fetching slots: {response.status_code} - {response.text}")
            return []

        data = response.json()
        slots_data = data.get("data", {}).get("slots", {})

        # Extract all available ISO timestamps
        slots: list[str] = []
        for date_key, time_list in slots_data.items():
            for slot in time_list:
                if isinstance(slot, dict) and "time" in slot:
                    slots.append(slot["time"])
                elif isinstance(slot, str):
                    slots.append(slot)

        return slots

    async def create_booking(
        self,
        client: httpx.AsyncClient,
        event_type_id: int,
        start_time: str,
        attendee: dict,
    ) -> dict | None:
        """Create a single booking on Cal.com."""
        payload = {
            "eventTypeId": event_type_id,
            "start": start_time,
            "attendee": {
                "name": attendee["name"],
                "email": attendee["email"],
                "timeZone": "America/New_York",
                "language": "en",
                "phoneNumber": attendee["phone"],
            },
            "metadata": {
                "fake_booking": "true",
                "company": attendee["company"],
                "generated_by": "fake_calendar_bookings.py",
            },
        }

        response = await client.post(f"{self.base_url}/bookings", json=payload)

        if response.status_code in (200, 201):
            data = response.json()
            booking_data = data.get("data", data)
            uid = booking_data.get("uid")
            if uid:
                self.created_booking_uids.append(uid)
            return booking_data
        else:
            print(f"  Failed to create booking: {response.status_code} - {response.text}")
            return None

    async def create_fake_bookings(
        self,
        event_type_id: int,
        num_bookings: int = 20,
        days_span: int = 7,
    ):
        """Create multiple fake bookings."""
        print(f"\nCreating {num_bookings} fake Cal.com bookings over {days_span} days...\n")

        async with await self.get_client() as client:
            # Get available slots
            today = datetime.now(timezone.utc)
            end_date = today + timedelta(days=days_span)

            print("Fetching available slots from Cal.com...")
            available_slots = await self.get_available_slots(
                client, event_type_id, today, end_date
            )

            if not available_slots:
                print("\nNo available slots found! Check that:")
                print("  - Your event type ID is correct")
                print("  - You have availability set up in Cal.com")
                print("  - The date range has open slots")
                return

            print(f"Found {len(available_slots)} available slots\n")

            # Randomly select slots (don't exceed available)
            num_to_book = min(num_bookings, len(available_slots))
            selected_slots = random.sample(available_slots, num_to_book)
            selected_slots.sort()  # Sort chronologically

            created_count = 0
            for i, slot in enumerate(selected_slots):
                attendee = self.generate_fake_attendee()

                print(f"  [{i+1}/{num_to_book}] Booking: {attendee['name']} ({attendee['company']})")
                print(f"           Time: {slot}")

                result = await self.create_booking(client, event_type_id, slot, attendee)

                if result:
                    created_count += 1
                    print(f"           Done!")

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)

            print(f"\n{'='*50}")
            print(f"Successfully created {created_count} bookings!")
            print(f"{'='*50}")

            if self.created_booking_uids:
                print(f"\nBooking UIDs (save these to cancel later):")
                for uid in self.created_booking_uids:
                    print(f"  {uid}")

    async def cancel_bookings_by_metadata(self, event_type_id: int, days_span: int = 14):
        """Cancel bookings that have the fake_booking metadata."""
        print(f"\nSearching for fake bookings to cancel...\n")

        async with await self.get_client() as client:
            # List bookings
            today = datetime.now(timezone.utc)
            params = {
                "eventTypeId": event_type_id,
                "status": "upcoming",
            }

            response = await client.get(f"{self.base_url}/bookings", params=params)

            if response.status_code != 200:
                print(f"Error fetching bookings: {response.status_code} - {response.text}")
                return

            data = response.json()
            bookings = data.get("data", {}).get("bookings", [])

            if not bookings:
                bookings = data.get("data", [])

            cancelled_count = 0
            for booking in bookings:
                metadata = booking.get("metadata", {})
                is_fake = metadata.get("fake_booking") in (True, "true", "True")
                is_generated = metadata.get("generated_by") == "fake_calendar_bookings.py"
                if is_fake or is_generated:
                    uid = booking.get("uid")
                    title = booking.get("title", "Unknown")

                    print(f"  Cancelling: {title} (UID: {uid})")

                    cancel_response = await client.request(
                        "DELETE",
                        f"{self.base_url}/bookings/{uid}/cancel",
                        json={"cancellationReason": "Fake booking cleanup"},
                    )

                    if cancel_response.status_code in (200, 204):
                        cancelled_count += 1
                        print(f"           Done!")
                    else:
                        print(f"           Failed: {cancel_response.status_code}")

                    await asyncio.sleep(0.3)

            print(f"\n{'='*50}")
            print(f"Cancelled {cancelled_count} fake bookings!")
            print(f"{'='*50}")


async def main():
    parser = argparse.ArgumentParser(
        description="Create fake Cal.com bookings for marketing screenshots"
    )
    parser.add_argument(
        "--event-type-id", "-e",
        type=int,
        required=True,
        help="Your Cal.com event type ID (required)"
    )
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=20,
        help="Number of fake bookings to create (default: 20)"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=7,
        help="Number of days to spread bookings across (default: 7)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Cancel existing fake bookings instead of creating new ones"
    )

    args = parser.parse_args()

    # Get API key from environment
    api_key = os.environ.get("CALCOM_API_KEY")
    if not api_key:
        print("\n" + "=" * 50)
        print("ERROR: CALCOM_API_KEY environment variable not set!")
        print("=" * 50)
        print("\nSet it with:")
        print("  export CALCOM_API_KEY='your-api-key-here'")
        print("\nYou can find your API key at:")
        print("  https://app.cal.com/settings/developer/api-keys")
        print("=" * 50)
        return 1

    print("\n" + "=" * 50)
    print("  Cal.com Fake Booking Generator")
    print("=" * 50)

    generator = CalComBookingGenerator(api_key)

    if args.clear:
        await generator.cancel_bookings_by_metadata(args.event_type_id, args.days)
    else:
        await generator.create_fake_bookings(args.event_type_id, args.count, args.days)

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
