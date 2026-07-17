"""Add final estimates and a delegated estimate editor.

Revision ID: 20260716_0003
Revises: 20260715_0002
Create Date: 2026-07-16 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260716_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_items", sa.Column("final_estimate", sa.String(length=32), nullable=True))
    op.add_column("rooms", sa.Column("estimate_editor_participant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_rooms_estimate_editor_participant_id",
        "rooms",
        "participants",
        ["estimate_editor_participant_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_rooms_estimate_editor_participant_id", "rooms", type_="foreignkey")
    op.drop_column("rooms", "estimate_editor_participant_id")
    op.drop_column("task_items", "final_estimate")
