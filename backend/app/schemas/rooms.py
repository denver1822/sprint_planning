from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


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


class ParticipantRenameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class RoomUpdateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    deck: DeckInput | None = None

    @model_validator(mode="after")
    def require_change(self) -> "RoomUpdateRequest":
        if self.name is None and self.deck is None:
            raise ValueError("Необходимо передать name или deck")
        return self


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=0)


class TaskUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=0)


class TaskDeleteRequest(BaseModel):
    expected_version: int = Field(ge=0)


class TaskReorderRequest(BaseModel):
    task_ids: list[UUID] = Field(min_length=1)
    expected_version: int = Field(ge=0)


class ActiveTaskRequest(BaseModel):
    task_id: UUID | None = None
    expected_version: int = Field(ge=0)


class EstimateEditorRequest(BaseModel):
    participant_id: UUID | None = None
    expected_version: int = Field(ge=0)


class ObserverModeRequest(BaseModel):
    is_observer: bool
    expected_version: int = Field(ge=0)


class FinalEstimateRequest(BaseModel):
    value: str = Field(min_length=1, max_length=32)
    expected_version: int = Field(ge=0)


class TaskResponse(BaseModel):
    id: UUID
    title: str
    position: int
    is_excluded: bool
    is_locked: bool = False
    final_estimate: str | None = None


class JiraConnectionInput(BaseModel):
    base_url: str = Field(min_length=8, max_length=2048)
    api_token: SecretStr = Field(min_length=1, max_length=512)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


class JiraPreviewRequest(BaseModel):
    connection: JiraConnectionInput
    jql: str = Field(min_length=1, max_length=2000)
    start_at: int = Field(default=0, ge=0, le=10_000)
    max_results: int = Field(default=25, ge=1, le=50)


class JiraConnectionTestRequest(BaseModel):
    connection: JiraConnectionInput


class JiraIssueResponse(BaseModel):
    key: str
    title: str
    url: str
    snapshot: dict[str, str | None]


class JiraPreviewResponse(BaseModel):
    issues: list[JiraIssueResponse]
    start_at: int
    max_results: int
    total: int


class JiraImportRequest(JiraPreviewRequest):
    expected_version: int = Field(ge=0)
    selected_keys: list[str] = Field(min_length=1, max_length=50)

    @field_validator("selected_keys")
    @classmethod
    def validate_selected_keys(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Выбранные ключи задач должны быть уникальными")
        return normalized


class JiraImportResponse(BaseModel):
    imported: list[TaskResponse]
    version: int


class DeckResponse(BaseModel):
    kind: DeckKind
    cards: list[CardInput]


class ParticipantResponse(BaseModel):
    id: UUID
    display_name: str
    is_online: bool
    is_owner: bool
    is_observer: bool = False
    has_voted: bool = False


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    state: str
    version: int
    deck: DeckResponse
    participants: list[ParticipantResponse]
    tasks: list[TaskResponse] = Field(default_factory=list)
    active_task_id: UUID | None = None
    estimate_editor_participant_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ParticipantSessionResponse(BaseModel):
    room: RoomResponse
    participant: ParticipantResponse
    participant_token: str | None = None
    restored: bool


class RoundStartRequest(BaseModel):
    expected_version: int = Field(ge=0)
    client_command_id: UUID
    task_id: UUID | None = None


class NewRoundRequest(BaseModel):
    expected_version: int = Field(ge=0)
    client_command_id: UUID
    repeat_task: bool = False


class VoteRequest(BaseModel):
    card_value: str = Field(min_length=1, max_length=32)


class RevealRequest(BaseModel):
    expected_version: int = Field(ge=0)
    client_command_id: UUID


class FinishRequest(BaseModel):
    expected_version: int = Field(ge=0)
    client_command_id: UUID


class VoteResponse(BaseModel):
    round_id: UUID
    card_value: str
    version: int


class RoundResponse(BaseModel):
    id: UUID
    task_id: UUID | None
    sequence: int
    state: str
    version: int


class RevealResponse(BaseModel):
    round: RoundResponse
    revealed_votes: list[dict[str, object]]
    metrics: dict[str, object]


class RoundHistoryResponse(BaseModel):
    id: UUID
    sequence: int
    task_id: UUID | None
    task_title: str | None
    revealed_at: datetime
    revealed_votes: list[dict[str, object]]
    metrics: dict[str, object]


class SessionSummaryResponse(BaseModel):
    revealed_round_count: int
    total_vote_count: int
    numeric_vote_count: int
    special_vote_count: int
    exact_consensus_count: int
    mean_agreement_index: float | None
    distribution: dict[str, int]
    special_cards: dict[str, int]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
