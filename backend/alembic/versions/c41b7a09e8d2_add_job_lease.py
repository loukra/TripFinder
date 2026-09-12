"""add job lease: heartbeat and claim token

A job left ``claimed`` by a dead worker was lost for ever — ``requeue_stale``
existed but nothing called it, so a worker restart stranded a run at
``analyzing`` with no process behind it. Calling it on a timeout alone is
unsafe once more than one worker polls the table: a slow-but-alive run would
be handed to a second worker, and two pipelines would spend two budgets and
write the same research row.

A lease fixes both halves. ``heartbeat_at`` is touched while a job is being
worked on, so "no worker" is distinguishable from "slow worker"; and
``claim_token`` is refreshed on every claim, so a worker that comes back from
the dead cannot finish a job somebody else has since taken over.

Revision ID: c41b7a09e8d2
Revises: 79f1e54d415d
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41b7a09e8d2"
down_revision: str | Sequence[str] | None = "79f1e54d415d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "research_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("research_jobs", sa.Column("claim_token", sa.Uuid(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("research_jobs", "claim_token")
    op.drop_column("research_jobs", "heartbeat_at")
