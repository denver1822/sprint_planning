import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.deck import Deck
    from app.db.models.participant import Participant
    from app.db.models.room_action import RoomAction
    from app.db.models.task_item import TaskItem
    from app.db.models.voting_round import VotingRound


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_rooms_version_non_negative"),
        Index("ix_rooms_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    public_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="LOBBY")
    version: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    owner_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "participants.id",
            name="fk_rooms_owner_participant_id",
            use_alter=True,
        ),
        nullable=True,
    )
    active_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_items.id", ondelete="SET NULL"), nullable=True
    )
    estimate_editor_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="SET NULL"), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deck: Mapped["Deck"] = relationship(back_populates="room", uselist=False, cascade="all, delete-orphan")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="room", foreign_keys="Participant.room_id", cascade="all, delete-orphan"
    )
    owner: Mapped["Participant | None"] = relationship(
        foreign_keys=[owner_participant_id], post_update=True
    )
    tasks: Mapped[list["TaskItem"]] = relationship(
        back_populates="room",
        foreign_keys="TaskItem.room_id",
        cascade="all, delete-orphan",
        order_by="TaskItem.position",
    )
    active_task: Mapped["TaskItem | None"] = relationship(foreign_keys=[active_task_id])
    estimate_editor: Mapped["Participant | None"] = relationship(
        foreign_keys=[estimate_editor_participant_id]
    )
    rounds: Mapped[list["VotingRound"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", order_by="VotingRound.sequence"
    )
    actions: Mapped[list["RoomAction"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
