from decimal import Decimal, InvalidOperation

from app.core.errors import DomainError
from app.schemas.rooms import CardInput, CardType, DeckInput, DeckKind

PRESET_CARDS: dict[DeckKind, tuple[tuple[str, CardType], ...]] = {
    DeckKind.FIBONACCI: tuple(
        (value, CardType.NUMERIC)
        for value in ("0", "1", "2", "3", "5", "8", "13", "21", "34", "55", "89")
    )
    + (("?", CardType.SPECIAL),),
    DeckKind.MODIFIED_FIBONACCI: tuple(
        (value, CardType.NUMERIC)
        for value in ("0", "0.5", "1", "2", "3", "5", "8", "13", "20", "40", "100")
    )
    + (("?", CardType.SPECIAL),),
    DeckKind.POWERS_OF_TWO: tuple(
        (value, CardType.NUMERIC) for value in ("0", "1", "2", "4", "8", "16", "32", "64")
    )
    + (("?", CardType.SPECIAL),),
}


def resolve_cards(deck_input: DeckInput) -> list[dict[str, str]]:
    if deck_input.kind is not DeckKind.CUSTOM:
        return [
            {"value": value, "type": card_type.value}
            for value, card_type in PRESET_CARDS[deck_input.kind]
        ]

    cards = deck_input.cards or []
    normalized_values: set[str] = set()
    numeric_count = 0
    resolved: list[dict[str, str]] = []
    for card in cards:
        value = card.value.strip()
        normalized = value.casefold()
        if not value or normalized in normalized_values:
            raise DomainError("invalid_deck", "Значения карт должны быть уникальными")
        normalized_values.add(normalized)
        if card.type is CardType.NUMERIC:
            _validate_numeric_card(value)
            numeric_count += 1
        resolved.append({"value": value, "type": card.type.value})

    if numeric_count == 0:
        raise DomainError("invalid_deck", "Колода должна содержать хотя бы одну числовую карту")
    return resolved


def deck_response(kind: str, cards: list[dict[str, str]]) -> dict[str, object]:
    return {
        "kind": kind,
        "cards": [CardInput.model_validate(card) for card in cards],
    }


def _validate_numeric_card(value: str) -> None:
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise DomainError("invalid_deck", "Числовая карта имеет некорректное значение") from error
    if not number.is_finite() or number < 0:
        raise DomainError("invalid_deck", "Числовая карта должна быть конечной и неотрицательной")

