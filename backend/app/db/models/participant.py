import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.room import Room
    from app.db.models.vote import Vote


class Participant(TimestampMixin, Base):
    __tablename__ = "participants"
    __table_args__ = (
        Index("ix_participants_room_online", "room_id", "is_online"),
        Index("uq_participants_token_hash", "token_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_online: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    is_observer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    room: Mapped["Room"] = relationship(back_populates="participants", foreign_keys=[room_id])
    votes: Mapped[list["Vote"]] = relationship(back_populates="participant")
