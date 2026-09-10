"""add research diagnostics

Records what a run suppressed and why, so a thin result stays
distinguishable from a suppressed one (plan §0.1, §4.7, §8.1).

Revision ID: 3f1a7c9b42e0
Revises: 907dee24fd0e
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3f1a7c9b42e0"
down_revision: str | Sequence[str] | None = "907dee24fd0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "research",
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("research", "diagnostics")
