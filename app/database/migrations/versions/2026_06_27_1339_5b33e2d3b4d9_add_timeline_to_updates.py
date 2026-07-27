"""add timeline to updates

Revision ID: 5b33e2d3b4d9
Revises: 0234149bd8d0
Create Date: 2026-06-27 13:39:40.503015+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5b33e2d3b4d9'
down_revision: str | None = '0234149bd8d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('updates', sa.Column('timeline', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('updates', 'timeline')
