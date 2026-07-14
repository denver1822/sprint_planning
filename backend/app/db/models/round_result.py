import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.voting_round import VotingRound


class RoundResult(TimestampMixin, Base):
    __tablename__ = "round_results"

    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("voting_rounds.id", ondelete="CASCADE"), primary_key=True
    )
    revealed_votes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    round: Mapped["VotingRound"] = relationship(back_populates="result")

