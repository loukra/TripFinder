"""add research weak_results

Persists entities that were ranked but did not make the strong-recommendation
cut — below the independent-user threshold, or beyond the top-N cap (plan
§4.4) — so nothing Aggregation computes is silently discarded (plan §0.1).

Revision ID: 6a2e8f1d4c93
Revises: 3f1a7c9b42e0
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6a2e8f1d4c93"
down_revision: str | Sequence[str] | None = "3f1a7c9b42e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "research",
        sa.Column(
            "weak_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("research", "weak_results")
