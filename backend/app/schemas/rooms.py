from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CardType(StrEnum):
    NUMERIC = "numeric"
    SPECIAL = "special"


class DeckKind(StrEnum):
    FIBONACCI = "fibonacci"
    MODIFIED_FIBONACCI = "modified_fibonacci"
    POWERS_OF_TWO = "powers_of_two"
    CUSTOM = "custom"


class CardInput(BaseModel):
    value: str = Field(min_length=1, max_length=32)
    type: CardType


class DeckInput(BaseModel):
    kind: DeckKind = DeckKind.FIBONACCI
    cards: list[CardInput] | None = None

    @model_validator(mode="after")
    def validate_custom_deck(self) -> "DeckInput":
        if self.kind is DeckKind.CUSTOM and not self.cards:
            raise ValueError("Для пользовательской колоды требуется cards")
        if self.kind is not DeckKind.CUSTOM and self.cards is not None:
            raise ValueError("cards разрешены только для пользовательской колоды")
        return self


class RoomCreateRequest(BaseModel):
    name: str = Field(default="Новая комната", min_length=1, max_length=160)
    owner_name: str = Field(min_length=1, max_length=80)
    deck: DeckInput = Field(default_factory=DeckInput)


class RoomJoinRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class RoomUpdateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    deck: DeckInput | None = None

    @model_validator(mode="after")
    def require_change(self) -> "RoomUpdateRequest":
        if self.name is None and self.deck is None:
            raise ValueError("Необходимо передать name или deck")
        return self


class DeckResponse(BaseModel):
    kind: DeckKind
    cards: list[CardInput]


class ParticipantResponse(BaseModel):
    id: UUID
    display_name: str
    is_online: bool
    is_owner: bool


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    state: str
    version: int
    deck: DeckResponse
    participants: list[ParticipantResponse]
    created_at: datetime
    updated_at: datetime


class ParticipantSessionResponse(BaseModel):
    room: RoomResponse
    participant: ParticipantResponse
    participant_token: str | None = None
    restored: bool


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody

