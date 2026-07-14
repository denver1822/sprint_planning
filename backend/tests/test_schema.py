from app.db.base import Base
import app.db.models  # noqa: F401


def test_core_tables_are_registered() -> None:
    expected_tables = {
        "rooms",
        "participants",
        "decks",
        "task_items",
        "voting_rounds",
        "votes",
        "round_results",
        "room_actions",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_database_constraints_cover_core_vote_invariants() -> None:
    voting_round_indexes = {index.name for index in Base.metadata.tables["voting_rounds"].indexes}
    vote_constraints = {constraint.name for constraint in Base.metadata.tables["votes"].constraints}

    assert "uq_voting_rounds_one_active_per_room" in voting_round_indexes
    assert "uq_votes_round_participant" in vote_constraints
