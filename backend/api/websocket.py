from fastapi import WebSocket
from backend.game.schemas import GameEvent
import asyncio
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, event: GameEvent):
        message = event.model_dump_json()
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

async def emit(event_type: str, payload: dict = {}):
    event = GameEvent(type=event_type, payload=payload)
    await manager.broadcast(event)