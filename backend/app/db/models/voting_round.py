import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.room import Room
    from app.db.models.round_result import RoundResult
    from app.db.models.task_item import TaskItem
    from app.db.models.vote import Vote


class VotingRound(TimestampMixin, Base):
    __tablename__ = "voting_rounds"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_voting_rounds_sequence_positive"),
        UniqueConstraint("room_id", "sequence", name="uq_voting_rounds_room_sequence"),
        Index(
            "uq_voting_rounds_one_active_per_room",
            "room_id",
            unique=True,
            postgresql_where=text("state = 'VOTING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_items.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="VOTING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["Room"] = relationship(back_populates="rounds")
    task: Mapped["TaskItem | None"] = relationship(back_populates="rounds")
    votes: Mapped[list["Vote"]] = relationship(back_populates="round", cascade="all, delete-orphan")
    result: Mapped["RoundResult | None"] = relationship(
        back_populates="round", uselist=False, cascade="all, delete-orphan"
    )
