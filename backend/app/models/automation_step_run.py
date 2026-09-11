"""AutomationStepRun model — the per-step ledger for a workflow run.

``automation_executions`` records that a run happened and how far it got. That
is one integer, and one integer cannot answer the questions an operator and the
engine both need:

* *Which touches actually went out, and what happened to each?* A run whose
  cursor reads 7 might have sent three messages and skipped four on consent.
  ``unsold_quote_worker`` keeps exactly this ledger by hand
  (``QuoteFollowupTouch``, one row per touch with an outcome) because the engine
  could not.
* *When did we last talk to this person in this sequence?* The answer gates the
  most valuable suppression rule there is — do not talk over a live
  conversation — and it is unanswerable without per-touch timestamps.

So each step that acts (or declines to act) appends a row here. The table is
**append-only**: a goto loop may legitimately run the same ``step_index`` more
than once, and collapsing those into one row would erase the evidence that a
workflow is looping.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.automation import Automation
    from app.models.automation_execution import AutomationExecution
    from app.models.contact import Contact

# A step that reached the customer. The one outcome that counts as a "touch",
# and therefore the only one that moves the last-touch clock.
OUTCOME_SENT = "sent"
# A step that deliberately did nothing: no consent, opted out, quiet hours,
# appointment already booked. Not a failure — a rule working correctly.
OUTCOME_SKIPPED = "skipped"
# A step that tried and could not: provider error, missing template, exception.
OUTCOME_FAILED = "failed"
# A step held at the approval gate, awaiting a human.
OUTCOME_PENDING_APPROVAL = "pending_approval"
# A step the approval gate refused outright.
OUTCOME_BLOCKED = "blocked"
# Control flow, recorded so a run's path through its branches is reconstructable.
OUTCOME_BRANCHED = "branched"
OUTCOME_WAITED = "waited"

STEP_RUN_OUTCOMES = (
    OUTCOME_SENT,
    OUTCOME_SKIPPED,
    OUTCOME_FAILED,
    OUTCOME_PENDING_APPROVAL,
    OUTCOME_BLOCKED,
    OUTCOME_BRANCHED,
    OUTCOME_WAITED,
)


class AutomationStepRun(Base, WorkspaceScoped):
    """One step of one workflow run, and what came of it."""

    __tablename__ = "automation_step_runs"
    __table_args__ = (
        # "What happened in this run, in order" — the timeline view, and the
        # query behind ``last_touch_at``.
        Index(
            "ix_automation_step_runs_execution_created",
            "execution_id",
            "created_at",
        ),
        # "How often has this automation skipped on consent this week" — the
        # per-automation reporting slice.
        Index(
            "ix_automation_step_runs_automation_created",
            "automation_id",
            "created_at",
        ),
        # "When did we last touch this person, across every sequence" — the
        # frequency-capping question, which is per-contact rather than per-run.
        Index(
            "ix_automation_step_runs_contact_created",
            "contact_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automation_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized from the execution so per-automation reporting does not have
    # to join through it.
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for the same reason, and nullable because contactless
    # triggers (workspace conditions, knowledge uploads) still run steps.
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Where in the step list this ran. Not unique with execution_id: a backward
    # goto may legitimately revisit a step, and each visit is its own row.
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # The author-assigned step id when the workflow defines one, so a ledger
    # stays readable after steps are reordered.
    step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)

    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    # Why, when the outcome is not self-explanatory: "no_sms_consent",
    # "quiet_hours", "appointment_booked", a provider error string.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider message ids, branch targets taken, template ids — whatever makes
    # this row reconstructable without re-reading the workflow definition.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    execution: Mapped["AutomationExecution"] = relationship(back_populates="step_runs")
    automation: Mapped["Automation"] = relationship()
    contact: Mapped["Contact | None"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<AutomationStepRun step={self.step_index} "
            f"type={self.step_type} outcome={self.outcome}>"
        )
