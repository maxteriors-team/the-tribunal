"""Unit tests for the pure Jobber-user → technician mapping."""

import pytest

from app.services.jobber.mapping import (
    EXTERNAL_SOURCE,
    JobberMappingError,
    jobber_user_to_technician_data,
)


def _node(**overrides):
    node = {
        "id": "Z2lkOi8vSm9iYmVyL1VzZXIvMQ==",
        "name": {"full": "Dana Tech", "first": "Dana", "last": "Tech"},
        "email": {"raw": "dana@example.com"},
        "phone": {"friendly": "(555) 123-4567"},
    }
    node.update(overrides)
    return node


def test_maps_all_fields() -> None:
    data = jobber_user_to_technician_data(_node())
    assert data == {
        "external_source": EXTERNAL_SOURCE,
        "external_id": "Z2lkOi8vSm9iYmVyL1VzZXIvMQ==",
        "name": "Dana Tech",
        "email": "dana@example.com",
        "phone": "(555) 123-4567",
    }


def test_falls_back_to_first_last_when_no_full_name() -> None:
    data = jobber_user_to_technician_data(_node(name={"first": "Sam", "last": "Rivera"}))
    assert data["name"] == "Sam Rivera"


def test_missing_email_and_phone_become_none() -> None:
    data = jobber_user_to_technician_data(_node(email=None, phone=None))
    assert data["email"] is None
    assert data["phone"] is None


def test_blank_nested_values_become_none() -> None:
    data = jobber_user_to_technician_data(_node(email={"raw": "  "}, phone={"friendly": ""}))
    assert data["email"] is None
    assert data["phone"] is None


def test_external_id_coerced_to_string() -> None:
    data = jobber_user_to_technician_data(_node(id=12345))
    assert data["external_id"] == "12345"


def test_long_name_truncated_to_column_limit() -> None:
    data = jobber_user_to_technician_data(_node(name={"full": "x" * 500}))
    assert len(data["name"]) == 200


def test_missing_id_raises() -> None:
    with pytest.raises(JobberMappingError, match="missing an 'id'"):
        jobber_user_to_technician_data(_node(id=None))


def test_no_derivable_name_raises() -> None:
    with pytest.raises(JobberMappingError, match="no usable name"):
        jobber_user_to_technician_data(_node(name={"full": "  "}))
