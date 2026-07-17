"""Add the administrator observer mode.

Revision ID: 20260717_0004
Revises: 20260716_0003
Create Date: 2026-07-17 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_0004"
down_revision = "20260716_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("is_observer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("participants", "is_observer", server_default=None)


def downgrade() -> None:
    op.drop_column("participants", "is_observer")
