import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.participant import Participant
    from app.db.models.voting_round import VotingRound


class Vote(TimestampMixin, Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("round_id", "participant_id", name="uq_votes_round_participant"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("voting_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_value: Mapped[str] = mapped_column(String(32), nullable=False)
    is_numeric: Mapped[bool] = mapped_column(Boolean, nullable=False)

    round: Mapped["VotingRound"] = relationship(back_populates="votes")
    participant: Mapped["Participant"] = relationship(back_populates="votes")

