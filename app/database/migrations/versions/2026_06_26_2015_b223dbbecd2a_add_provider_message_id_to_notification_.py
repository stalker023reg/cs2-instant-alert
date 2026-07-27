"""add provider_message_id to notification history

Revision ID: b223dbbecd2a
Revises: 
Create Date: 2026-06-26 20:15:39.604966+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b223dbbecd2a'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('notification_history', sa.Column('provider_message_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('notification_history', 'provider_message_id')
