"""Add telegram message fields and unique constraint to notification history

Revision ID: 0234149bd8d0
Revises: b223dbbecd2a
Create Date: 2026-06-27 13:28:43.266517+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0234149bd8d0'
down_revision: str | None = 'b223dbbecd2a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('notification_history', sa.Column('chat_id', sa.String(length=255), nullable=True))
    op.add_column('notification_history', sa.Column('message_id', sa.String(length=255), nullable=True))
    op.add_column('notification_history', sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notification_history', sa.Column('current_message_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('notification_history', sa.Column('last_edit_reason', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_notification_user_update_channel', 'notification_history', ['user_id', 'update_id', 'channel_type'])


def downgrade() -> None:
    op.drop_constraint('uq_notification_user_update_channel', 'notification_history', type_='unique')
    op.drop_column('notification_history', 'last_edit_reason')
    op.drop_column('notification_history', 'current_message_version')
    op.drop_column('notification_history', 'edited_at')
    op.drop_column('notification_history', 'message_id')
    op.drop_column('notification_history', 'chat_id')
