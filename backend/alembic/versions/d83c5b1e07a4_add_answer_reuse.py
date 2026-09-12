"""add the reuse key and the reuse marker

Phase 14.10 (plan §2.15): a question already answered can be answered from
the earlier run instead of being paid for again. Three columns carry it.

``plan`` is the plan the run actually ran against — stored for the first
time here. Until now a finished run kept its *results* and forgot what its
question had been understood to mean, which is the one thing needed to
recognise the same question asked again.

``plan_fingerprint`` is the digest of that plan and the column the lookup
runs against, so it is indexed. It is derived from ``plan`` and stored
anyway: a key recomputed at query time cannot be looked up, and recomputing
it across a growing table to answer one question is how a feature ends up
switched off.

``reused`` marks a run that showed an earlier run's answer, and carries the
date that answer was produced. Plan §2.15 rule 1 — a reused answer says when
it was produced — is enforced by the two travelling together: there is no
state in which a reader knows an answer is old and cannot say how old.

Every column is nullable. Runs that predate this phase have no plan stored
and simply never match a fingerprint, which is the safe direction: they keep
their answers and stop being reusable.

Revision ID: d83c5b1e07a4
Revises: c41b7a09e8d2
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d83c5b1e07a4"
down_revision: str | Sequence[str] | None = "c41b7a09e8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("research", sa.Column("plan", jsonb, nullable=True))
    op.add_column("research", sa.Column("plan_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("research", sa.Column("reused", jsonb, nullable=True))
    op.create_index("ix_research_plan_fingerprint", "research", ["plan_fingerprint"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_research_plan_fingerprint", table_name="research")
    op.drop_column("research", "reused")
    op.drop_column("research", "plan_fingerprint")
    op.drop_column("research", "plan")
