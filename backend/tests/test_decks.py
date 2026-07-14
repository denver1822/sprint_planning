import pytest

from app.core.errors import DomainError
from app.schemas.rooms import CardInput, CardType, DeckInput, DeckKind
from app.services.decks import resolve_cards


def test_fibonacci_preset_ends_at_89() -> None:
    cards = resolve_cards(DeckInput(kind=DeckKind.FIBONACCI))

    assert [card["value"] for card in cards] == [
        "0",
        "1",
        "2",
        "3",
        "5",
        "8",
        "13",
        "21",
        "34",
        "55",
        "89",
        "?",
    ]


def test_custom_deck_requires_a_numeric_card() -> None:
    deck = DeckInput(
        kind=DeckKind.CUSTOM,
        cards=[CardInput(value="?", type=CardType.SPECIAL)],
    )

    with pytest.raises(DomainError, match="числовую"):
        resolve_cards(deck)
