from fastapi import WebSocket
from backend.game.schemas import GameEvent
import asyncio
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._continue_event: asyncio.Event | None = None

    @property
    def continue_event(self):
        if self._continue_event is None:
            self._continue_event = asyncio.Event()
        return self._continue_event

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, event: GameEvent):
        message = event.model_dump_json()
        for connection in self.active_connections:
            await connection.send_text(message)

    async def wait_for_continue(self):
        self.continue_event.clear()
        await self.continue_event.wait()

    def signal_continue(self):
        self.continue_event.set()

manager = ConnectionManager()

async def emit(event_type: str, payload: dict = {}):
    event = GameEvent(type=event_type, payload=payload)
    await manager.broadcast(event)