"""Add the selected task to a room.

Revision ID: 20260715_0002
Revises: 20260714_0001
Create Date: 2026-07-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260715_0002"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("active_task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_rooms_active_task_id",
        "rooms",
        "task_items",
        ["active_task_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_rooms_active_task_id", "rooms", type_="foreignkey")
    op.drop_column("rooms", "active_task_id")
