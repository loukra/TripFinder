"""add clarification state and job cancellation

Phase 13 (plan §6, §10 Phase 13): a research that pauses for clarification
must survive the gap between the worker halting the job and the user
answering ``POST /research/{id}/clarify`` — ``clarification`` (user-facing),
``pending_plan`` (what Query Understanding already learned) and
``resume_plan`` (the finished plan a resumed run is seeded with) persist
that state. ``research_jobs.cancel_requested_at`` is the flag
``POST /research/{id}/cancel`` sets on a job already running, so the worker
can notice between pipeline steps (plan §10 Phase 13).

Revision ID: 79f1e54d415d
Revises: 6a2e8f1d4c93
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "79f1e54d415d"
down_revision: str | Sequence[str] | None = "6a2e8f1d4c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("research", sa.Column("clarification", jsonb, nullable=True))
    op.add_column("research", sa.Column("pending_plan", jsonb, nullable=True))
    op.add_column("research", sa.Column("resume_plan", jsonb, nullable=True))
    op.add_column(
        "research_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("research_jobs", "cancel_requested_at")
    op.drop_column("research", "resume_plan")
    op.drop_column("research", "pending_plan")
    op.drop_column("research", "clarification")
