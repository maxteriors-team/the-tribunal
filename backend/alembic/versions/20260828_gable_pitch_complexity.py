"""Retire the 'aerial' permanent-complexity tier in favour of gable pitch.

'aerial' was never a labor tier: it hardcoded a 1.5 COGS markup that *replaced*
the 3.0 standard markup, so every gable run was quoted at roughly half price.
A gable's extra length is now handled where it belongs -- the designer applies
the Pythagorean rake correction to measured feet -- and complexity is once again
only easy/standard/complex.

Data handling (footage is preserved, never dropped):
- ``permanent_complexity = 'aerial'``          -> 'standard'
- ``permanent_complexity_feet -> 'aerial'``    -> folded into the 'standard'
  bucket, then the key is removed.

Both must move together: ``LinearFeetEstimateRequest`` re-validates these rows
through a ``Literal`` when a shared comparison link is opened, so a leftover
'aerial' in *either* place raises a ValidationError and 500s the public page.

Note: affected comparisons will now reprice at the correct (roughly double)
standard markup. That is the point of the fix, but any already-shared link
showing the old halved number will change.

Revision ID: 20260828_gable_pitch
Revises: 20260826_msg_sender
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_gable_pitch"
down_revision: str | None = "20260826_msg_sender"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CHECK_NAME = "ck_roofline_comparisons_permanent_complexity"
_OLD_CHECK = "permanent_complexity IN ('aerial', 'easy', 'standard', 'complex')"
_NEW_CHECK = "permanent_complexity IN ('easy', 'standard', 'complex')"

# Fold the 'aerial' feet into 'standard' and drop the retired key. Written as a
# read-modify-write over jsonb so the *sum* survives when a row already carries a
# 'standard' bucket -- a plain key rename would silently discard one of them.
_FOLD_FEET = f"""
    UPDATE roofline_comparisons
       SET permanent_complexity_feet =
             (permanent_complexity_feet - '{{from_key}}'::text)
             || jsonb_build_object(
                  'standard',
                  COALESCE((permanent_complexity_feet ->> 'standard')::numeric, 0)
                  + COALESCE((permanent_complexity_feet ->> '{{from_key}}')::numeric, 0)
                )
     WHERE permanent_complexity_feet ? '{{from_key}}'
"""


def upgrade() -> None:
    """Retire 'aerial' from both the scalar column and the measured-feet map."""
    bind = op.get_bind()

    # Constraint first: it is what would reject the rewritten rows otherwise.
    op.drop_constraint(_CHECK_NAME, "roofline_comparisons", type_="check")
    bind.exec_driver_sql(
        "UPDATE roofline_comparisons SET permanent_complexity = 'standard' "
        "WHERE permanent_complexity = 'aerial'"
    )
    bind.exec_driver_sql(_FOLD_FEET.format(from_key="aerial"))
    op.create_check_constraint(_CHECK_NAME, "roofline_comparisons", _NEW_CHECK)


def downgrade() -> None:
    """Restore the permissive constraint.

    Deliberately one-way for data: rows already folded into 'standard' cannot be
    told apart from rows that were always 'standard', and inventing an 'aerial'
    value back would re-introduce the half-price bug. Footage is unchanged either
    way, so the rollback is safe -- it just does not resurrect the old label.
    """
    op.drop_constraint(_CHECK_NAME, "roofline_comparisons", type_="check")
    op.create_check_constraint(_CHECK_NAME, "roofline_comparisons", _OLD_CHECK)
