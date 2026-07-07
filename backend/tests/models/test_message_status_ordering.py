"""Tests for ``advances_message_status`` — the monotonic delivery-status guard.

Used by the Telnyx SMS and Resend email webhook handlers to ignore duplicate or
out-of-order provider webhooks so a late ``sent`` never downgrades a message that
already reached DELIVERED/FAILED (which would also double-count campaign stats).
"""

from __future__ import annotations

import pytest

from app.models.conversation import MessageStatus, advances_message_status

S = MessageStatus


@pytest.mark.parametrize(
    ("current", "candidate", "expected"),
    [
        # Forward transitions advance.
        (S.QUEUED, S.SENDING, True),
        (S.SENDING, S.SENT, True),
        (S.SENT, S.DELIVERED, True),
        (S.SENT, S.FAILED, True),
        (S.QUEUED, S.DELIVERED, True),
        # Duplicates / same status do not advance.
        (S.SENT, S.SENT, False),
        (S.DELIVERED, S.DELIVERED, False),
        (S.FAILED, S.FAILED, False),
        # Backwards transitions (out-of-order webhooks) are rejected.
        (S.DELIVERED, S.SENT, False),
        (S.DELIVERED, S.SENDING, False),
        (S.FAILED, S.SENT, False),
        (S.SENT, S.QUEUED, False),
        # DELIVERED and FAILED are both terminal (equal rank) — neither wins.
        (S.DELIVERED, S.FAILED, False),
        (S.FAILED, S.DELIVERED, False),
    ],
)
def test_advances_message_status(
    current: MessageStatus, candidate: MessageStatus, expected: bool
) -> None:
    assert advances_message_status(current, candidate) is expected
