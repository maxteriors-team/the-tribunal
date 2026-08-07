"""Give every proposal_document add-on charge a stable id.

A quote built by the sales wizard keeps its money in ``proposal_document``, and
the add-on charges in it are the persistence a *post-save* added service uses —
see ``QuoteService.add_service``. Removing one needs a handle that survives the
document being repriced (which rebuilds every derived line from scratch), and
position is not that handle: repricing reorders nothing today, but pinning a
delete to a list index makes "remove the gutters" one refactor away from
removing the wrong service off a customer's quote.

So each charge gets an ``id``. New documents get one at build time; this
backfills the ones written before that existed. Additive and per-charge: no
amount, description, tier pin or catalog link is read or rewritten, so no quote
total moves. Charges that already carry an id are left alone, which makes the
migration safe to re-run.

Revision ID: a7f3c21d9e04
Revises: c2e043d6bb65
Create Date: 2026-08-07
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7f3c21d9e04"
down_revision: str | None = "c2e043d6bb65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rows(conn: sa.Connection) -> list[tuple[uuid.UUID, dict]]:
    """Quotes whose snapshot carries at least one add-on charge.

    Filtered in SQL so a workspace with thousands of plain or charge-free quotes
    is never loaded into memory to be discarded.
    """
    result = conn.execute(
        sa.text(
            """
            SELECT id, proposal_document
            FROM quotes
            WHERE proposal_document IS NOT NULL
              AND jsonb_typeof(proposal_document -> 'additional_charges') = 'array'
              AND jsonb_array_length(proposal_document -> 'additional_charges') > 0
            """
        )
    )
    rows: list[tuple[uuid.UUID, dict]] = []
    for row in result:
        document = row.proposal_document
        # psycopg returns jsonb already decoded; a str means a driver that does
        # not, and guessing wrong here would rewrite a document as a JSON string.
        if isinstance(document, str):
            document = json.loads(document)
        if isinstance(document, dict):
            rows.append((row.id, document))
    return rows


def upgrade() -> None:
    conn = op.get_bind()
    for quote_id, document in _rows(conn):
        charges = document.get("additional_charges")
        if not isinstance(charges, list):
            continue
        touched = False
        for charge in charges:
            if not isinstance(charge, dict):
                continue
            if not charge.get("id"):
                charge["id"] = uuid.uuid4().hex
                touched = True
        if not touched:
            continue
        conn.execute(
            sa.text("UPDATE quotes SET proposal_document = :doc WHERE id = :id"),
            {"doc": json.dumps(document), "id": quote_id},
        )


def downgrade() -> None:
    """Strip the ids again.

    The column is untyped JSONB and ``ProposalCharge.id`` is optional, so a
    document that keeps its ids would still validate and still price identically
    — but leaving them would make a downgrade a no-op that quietly diverges from
    the schema it claims to restore.
    """
    conn = op.get_bind()
    for quote_id, document in _rows(conn):
        charges = document.get("additional_charges")
        if not isinstance(charges, list):
            continue
        touched = False
        for charge in charges:
            if isinstance(charge, dict) and "id" in charge:
                charge.pop("id")
                touched = True
        if not touched:
            continue
        conn.execute(
            sa.text("UPDATE quotes SET proposal_document = :doc WHERE id = :id"),
            {"doc": json.dumps(document), "id": quote_id},
        )
