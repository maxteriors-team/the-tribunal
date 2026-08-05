"""One definition of "this sent quote has lapsed".

``expired`` is derived, not stored at the moment it happens: a quote sits in
``sent`` until :meth:`QuoteService._expire_overdue` sweeps it, and that sweep
only runs on quote read paths — there is no expiry worker. So a quote whose
``expiry_date`` passed last week is still ``sent`` in the database until
somebody opens a quote list.

That is fine for the quote screens (they sweep before they read) and wrong for
reporting, which would count a lapsed quote as *undecided* and quietly deflate
the close rate. Sales reporting is a GET and must not write, so it derives the
status in SQL instead — using the predicate defined **here**, so the sweep and
the report can never disagree about what "expired" means.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Case, ColumnElement, String, case, cast

from app.models.quote import Quote

__all__ = ["EXPIRED_STATUS", "SENT_STATUS", "effective_status", "overdue_sent_predicate"]

SENT_STATUS = "sent"
EXPIRED_STATUS = "expired"


def overdue_sent_predicate(today: date | None = None) -> ColumnElement[bool]:
    """Still ``sent`` but past its expiry date, as of ``today`` (default: now)."""
    reference = today or date.today()
    return (
        (Quote.status == SENT_STATUS)
        & Quote.expiry_date.is_not(None)
        & (Quote.expiry_date < reference)
    )


def effective_status(today: date | None = None) -> Case[str]:
    """``quotes.status``, with lapsed ``sent`` quotes read as ``expired``.

    A read-only equivalent of the sweep, for callers that must not mutate rows.
    Both branches are text: ``quotes.status`` is the ``quote_status`` enum and
    Postgres refuses a ``CASE`` mixing an enum with a string literal.
    """
    return case(
        (overdue_sent_predicate(today), EXPIRED_STATUS),
        else_=cast(Quote.status, String),
    )
