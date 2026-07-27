"""Enforce one notification channel of each type per user.

Revision ID: 61b25a7c4ef1
Revises: 5b33e2d3b4d9
Create Date: 2026-06-29 21:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "61b25a7c4ef1"
down_revision: str | None = "5b33e2d3b4d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM notification_channels AS duplicate
        USING notification_channels AS keeper
        WHERE duplicate.user_id = keeper.user_id
          AND duplicate.channel_type = keeper.channel_type
          AND duplicate.id > keeper.id
        """
    )
    op.create_unique_constraint(
        "uq_notification_channel_user_type",
        "notification_channels",
        ["user_id", "channel_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_notification_channel_user_type",
        "notification_channels",
        type_="unique",
    )
