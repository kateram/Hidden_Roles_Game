import asyncio
from fastapi import APIRouter
from backend.agents.runtime import run_game

router = APIRouter()

PLAYER_NAMES = ["Leyou", "Christine", "Rhea", "Hannah", "Josh"]

@router.post("/game/start")
async def start_game():
    asyncio.create_task(run_game(PLAYER_NAMES))
    return {"status": "started"}