"""Create the Scrum Planning core schema.

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("owner_participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version >= 0", name="ck_rooms_version_non_negative"),
        sa.UniqueConstraint("public_code", name="uq_rooms_public_code"),
    )
    op.create_index("ix_rooms_state", "rooms", ["state"])

    op.create_table(
        "decks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("cards", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("room_id", name="uq_decks_room_id"),
    )

    op.create_table(
        "participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("is_online", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_participants_room_id", "participants", ["room_id"])
    op.create_index("ix_participants_room_online", "participants", ["room_id", "is_online"])
    op.create_index("uq_participants_token_hash", "participants", ["token_hash"], unique=True)
    op.create_foreign_key(
        "fk_rooms_owner_participant_id",
        "rooms",
        "participants",
        ["owner_participant_id"],
        ["id"],
    )

    op.create_table(
        "task_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_excluded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("jira_key", sa.String(length=128), nullable=True),
        sa.Column("jira_url", sa.String(length=2048), nullable=True),
        sa.Column("jira_snapshot", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("position >= 0", name="ck_task_items_position_non_negative"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_task_items_room_position", "task_items", ["room_id", "position"])

    op.create_table(
        "voting_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("sequence > 0", name="ck_voting_rounds_sequence_positive"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task_items.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("room_id", "sequence", name="uq_voting_rounds_room_sequence"),
    )
    op.create_index(
        "uq_voting_rounds_one_active_per_room",
        "voting_rounds",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text("state = 'VOTING'"),
    )

    op.create_table(
        "votes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_value", sa.String(length=32), nullable=False),
        sa.Column("is_numeric", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["round_id"], ["voting_rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("round_id", "participant_id", name="uq_votes_round_participant"),
    )
    op.create_index("ix_votes_round_id", "votes", ["round_id"])
    op.create_index("ix_votes_participant_id", "votes", ["participant_id"])

    op.create_table(
        "round_results",
        sa.Column("round_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("revealed_votes", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["round_id"], ["voting_rounds.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "room_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_participant_id"], ["participants.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_room_actions_room_created", "room_actions", ["room_id", "created_at"])
    op.create_index(
        "uq_room_actions_command_id",
        "room_actions",
        ["room_id", "client_command_id"],
        unique=True,
        postgresql_where=sa.text("client_command_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_room_actions_command_id", table_name="room_actions")
    op.drop_index("ix_room_actions_room_created", table_name="room_actions")
    op.drop_table("room_actions")
    op.drop_table("round_results")
    op.drop_index("ix_votes_participant_id", table_name="votes")
    op.drop_index("ix_votes_round_id", table_name="votes")
    op.drop_table("votes")
    op.drop_index("uq_voting_rounds_one_active_per_room", table_name="voting_rounds")
    op.drop_table("voting_rounds")
    op.drop_index("ix_task_items_room_position", table_name="task_items")
    op.drop_table("task_items")
    op.drop_constraint("fk_rooms_owner_participant_id", "rooms", type_="foreignkey")
    op.drop_index("uq_participants_token_hash", table_name="participants")
    op.drop_index("ix_participants_room_online", table_name="participants")
    op.drop_index("ix_participants_room_id", table_name="participants")
    op.drop_table("participants")
    op.drop_table("decks")
    op.drop_index("ix_rooms_state", table_name="rooms")
    op.drop_table("rooms")
