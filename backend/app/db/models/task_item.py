import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.room import Room
    from app.db.models.voting_round import VotingRound


class TaskItem(TimestampMixin, Base):
    __tablename__ = "task_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_task_items_position_non_negative"),
        Index("ix_task_items_room_position", "room_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    jira_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    jira_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    jira_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    room: Mapped["Room"] = relationship(back_populates="tasks")
    rounds: Mapped[list["VotingRound"]] = relationship(back_populates="task")

