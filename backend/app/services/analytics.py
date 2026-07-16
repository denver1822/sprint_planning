from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoundResult, VotingRound
from app.schemas.rooms import SessionSummaryResponse
from app.services.rooms import get_room_or_404


async def session_summary(session: AsyncSession, code: str) -> SessionSummaryResponse:
    room = await get_room_or_404(session, code)
    results = (
        await session.scalars(
            select(RoundResult)
            .join(VotingRound, VotingRound.id == RoundResult.round_id)
            .where(VotingRound.room_id == room.id, VotingRound.state == "REVEALED")
        )
    ).all()
    distribution: Counter[str] = Counter()
    special_cards: Counter[str] = Counter()
    agreement_indices: list[float] = []
    total_vote_count = numeric_vote_count = special_vote_count = exact_consensus_count = 0
    for result in results:
        metrics = result.metrics
        total_vote_count += int(metrics.get("vote_count", 0))
        numeric_vote_count += int(metrics.get("numeric_vote_count", 0))
        special_vote_count += int(metrics.get("special_vote_count", 0))
        exact_consensus_count += int(bool(metrics.get("exact_consensus", False)))
        distribution.update(metrics.get("distribution", {}))
        special_cards.update(metrics.get("special_cards", {}))
        agreement = metrics.get("agreement_index")
        if isinstance(agreement, int | float):
            agreement_indices.append(float(agreement))
    return SessionSummaryResponse(
        revealed_round_count=len(results),
        total_vote_count=total_vote_count,
        numeric_vote_count=numeric_vote_count,
        special_vote_count=special_vote_count,
        exact_consensus_count=exact_consensus_count,
        mean_agreement_index=sum(agreement_indices) / len(agreement_indices)
        if agreement_indices
        else None,
        distribution=dict(distribution),
        special_cards=dict(special_cards),
    )
