from uuid import uuid4

import pytest

from app.realtime.manager import RoomConnectionManager


class FakeWebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.accepted = False
        self.fail = fail
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("socket is closed")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_websocket_fanout_and_stale_connection_cleanup() -> None:
    manager = RoomConnectionManager()
    participant = uuid4()
    healthy, stale = FakeWebSocket(), FakeWebSocket(fail=True)

    assert await manager.connect("room", participant, healthy) is True
    assert await manager.connect("room", uuid4(), stale) is True
    await manager.broadcast("room", {"type": "vote.status_changed", "payload": {"has_voted": True}})

    assert healthy.messages == [{"type": "vote.status_changed", "payload": {"has_voted": True}}]
    assert manager.is_participant_connected("room", participant)
    assert not manager.is_participant_connected("room", uuid4())
