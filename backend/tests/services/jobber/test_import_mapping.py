"""Unit tests for the pure Jobber import mappings (clients/properties/jobs/invoices).

These are side-effect-free transformations, so they are exhaustively assertable
without a DB. The persistence + idempotency behaviour is covered separately in
``test_importer.py``.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models.field_service import JobStatus
from app.services.jobber.mapping import (
    EXTERNAL_SOURCE,
    JobberMappingError,
    jobber_client_properties,
    jobber_client_to_contact_data,
    jobber_invoice_to_invoice_data,
    jobber_job_to_job_data,
    jobber_property_to_location_data,
    map_jobber_invoice_status,
    map_jobber_job_status,
)


# --------------------------------------------------------------------------- #
# clients -> contacts
# --------------------------------------------------------------------------- #
def test_client_maps_person_with_primary_email_and_phone() -> None:
    node = {
        "id": "C1",
        "firstName": "Jane",
        "lastName": "Homeowner",
        "companyName": None,
        "emails": [
            {"primary": False, "address": "alt@x.com"},
            {"primary": True, "address": "jane@x.com"},
        ],
        "phones": [{"primary": True, "number": "(555) 111-2222"}],
        "billingAddress": {
            "street1": "12 Oak St",
            "city": "Austin",
            "province": "TX",
            "postalCode": "78701",
            "country": "US",
        },
    }

    data = jobber_client_to_contact_data(node)

    assert data["external_source"] == EXTERNAL_SOURCE
    assert data["external_id"] == "C1"
    assert data["first_name"] == "Jane"
    assert data["last_name"] == "Homeowner"
    assert data["email"] == "jane@x.com"  # primary preferred over the first entry
    assert data["phone"] == "(555) 111-2222"
    assert data["address_city"] == "Austin"
    assert data["address_state"] == "TX"
    assert data["address_zip"] == "78701"


def test_company_only_client_uses_company_as_first_name() -> None:
    node = {"id": "C2", "companyName": "Paddy's Pub", "name": "Paddy's Pub"}

    data = jobber_client_to_contact_data(node)

    # first_name is NOT NULL; a company-only client still maps.
    assert data["first_name"] == "Paddy's Pub"
    assert data["company_name"] == "Paddy's Pub"


def test_client_falls_back_to_display_name_split() -> None:
    node = {"id": "C3", "name": "Maximus Decimus"}

    data = jobber_client_to_contact_data(node)

    assert data["first_name"] == "Maximus"
    assert data["last_name"] == "Decimus"


def test_client_without_id_raises() -> None:
    with pytest.raises(JobberMappingError):
        jobber_client_to_contact_data({"firstName": "NoId"})


def test_client_without_any_name_raises() -> None:
    with pytest.raises(JobberMappingError):
        jobber_client_to_contact_data({"id": "C4"})


def test_email_phone_accept_connection_shape() -> None:
    """Some schema versions return emails/phones as a {nodes: [...]} connection."""
    node = {
        "id": "C5",
        "firstName": "Connie",
        "emails": {"nodes": [{"primary": True, "address": "connie@x.com"}]},
        "phones": {"nodes": [{"primary": True, "number": "555-9999"}]},
    }

    data = jobber_client_to_contact_data(node)

    assert data["email"] == "connie@x.com"
    assert data["phone"] == "555-9999"


# --------------------------------------------------------------------------- #
# properties -> service_locations
# --------------------------------------------------------------------------- #
def test_client_properties_extracts_nested_nodes() -> None:
    node = {"id": "C1", "clientProperties": {"nodes": [{"id": "P1"}, {"id": "P2"}]}}
    assert [p["id"] for p in jobber_client_properties(node)] == ["P1", "P2"]


def test_client_properties_absent_returns_empty() -> None:
    assert jobber_client_properties({"id": "C1"}) == []


def test_property_maps_address_and_name() -> None:
    node = {
        "id": "P1",
        "address": {
            "street1": "12 Oak St",
            "city": "Austin",
            "province": "TX",
            "postalCode": "78701",
            "country": "United States",
            "latitude": 30.27,
            "longitude": -97.74,
        },
    }

    data = jobber_property_to_location_data(node)

    assert data["external_id"] == "P1"
    assert data["name"] == "12 Oak St"  # label derived from first address line
    assert data["city"] == "Austin"
    assert data["latitude"] == pytest.approx(30.27)
    assert data["country"] == "UN"  # truncated to the 2-char column


def test_property_without_id_raises() -> None:
    with pytest.raises(JobberMappingError):
        jobber_property_to_location_data({"address": {"city": "Nowhere"}})


# --------------------------------------------------------------------------- #
# jobs -> field_service_jobs
# --------------------------------------------------------------------------- #
def test_job_maps_fields_and_resolution_keys() -> None:
    node = {
        "id": "J1",
        "jobNumber": 101,
        "title": "Gutter cleaning",
        "instructions": "2-story",
        "jobStatus": "complete",
        "startAt": "2026-06-30T14:00:00Z",
        "endAt": "2026-06-30T16:00:00Z",
        "client": {"id": "C1"},
        "property": {"id": "P1"},
        "assignedUsers": {"nodes": [{"id": "U1"}, {"id": "U2"}]},
    }

    data = jobber_job_to_job_data(node)

    assert data["external_id"] == "J1"
    assert data["title"] == "Gutter cleaning"
    assert data["status"] is JobStatus.COMPLETED
    assert isinstance(data["scheduled_start"], datetime)
    assert data["client_external_id"] == "C1"
    assert data["property_external_id"] == "P1"
    assert data["assigned_user_external_ids"] == ["U1", "U2"]


def test_job_without_client_raises() -> None:
    with pytest.raises(JobberMappingError):
        jobber_job_to_job_data({"id": "J2", "title": "Orphan"})


def test_job_title_falls_back_to_number() -> None:
    node = {"id": "J3", "jobNumber": 7, "client": {"id": "C1"}}
    data = jobber_job_to_job_data(node)
    assert data["title"] == "Job #7"


@pytest.mark.parametrize(
    ("raw", "has_start", "expected"),
    [
        ("complete", True, JobStatus.COMPLETED),
        ("cancelled", False, JobStatus.CANCELLED),
        ("unscheduled", False, JobStatus.UNSCHEDULED),
        ("active", True, JobStatus.SCHEDULED),  # unknown + has window -> scheduled
        ("late", False, JobStatus.UNSCHEDULED),  # unknown + no window -> unscheduled
        (None, True, JobStatus.SCHEDULED),
    ],
)
def test_job_status_mapping(raw: object, has_start: bool, expected: JobStatus) -> None:
    assert map_jobber_job_status(raw, has_start=has_start) is expected


# --------------------------------------------------------------------------- #
# invoices -> invoices
# --------------------------------------------------------------------------- #
def test_invoice_maps_money_and_dates() -> None:
    node = {
        "id": "I1",
        "invoiceNumber": "2001",
        "invoiceStatus": "awaiting_payment",
        "issuedDate": "2026-06-01",
        "dueDate": "2026-06-15",
        "message": "Thanks!",
        "client": {"id": "C1"},
        "amounts": {
            "total": 450.0,
            "subtotal": 410.0,
            "taxAmount": 40.0,
            "discountAmount": 0.0,
            "paymentsTotal": 100.0,
        },
    }

    data = jobber_invoice_to_invoice_data(node)

    assert data["external_id"] == "I1"
    assert data["number"] == "2001"
    assert data["status"] == "sent"  # awaiting_payment -> open AR
    assert data["total"] == pytest.approx(450.0)
    assert data["amount_paid"] == pytest.approx(100.0)
    assert data["issue_date"] == date(2026, 6, 1)
    assert data["due_date"] == date(2026, 6, 15)
    assert data["client_external_id"] == "C1"


def test_invoice_number_falls_back_to_external_id() -> None:
    data = jobber_invoice_to_invoice_data({"id": "I2", "client": {"id": "C1"}})
    assert data["number"] == "JOBBER-I2"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("paid", "paid"),
        ("partial", "partial"),
        ("past_due", "overdue"),
        ("bad_debt", "void"),
        ("draft", "draft"),
        ("something_new", "sent"),  # unknown -> open AR
        (None, "sent"),
    ],
)
def test_invoice_status_mapping(raw: object, expected: str) -> None:
    assert map_jobber_invoice_status(raw) == expected
