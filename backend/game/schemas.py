from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from typing import Any


# --- Enums ---

class Team(str, Enum):
    GOOD = "good"
    EVIL = "evil"


class RoleName(str, Enum):
    MERLIN = "merlin"
    LOYAL_SERVANT = "loyal_servant"
    MINION = "minion"
    ASSASSIN = "assassin"


class GamePhase(str, Enum):
    TEAM_PROPOSAL = "team_proposal"
    VOTING = "voting"
    QUEST = "quest"
    ASSASSINATION = "assassination"
    GAME_OVER = "game_over"


class GameResult(str, Enum):
    GOOD_WINS = "good_wins"
    EVIL_WINS = "evil_wins"


# --- Core models ---

class Role(BaseModel):
    name: RoleName
    team: Team
    sees_evil: bool
    is_merlin: bool


class Player(BaseModel):
    name: str
    role: Role


# --- Action models ---

class TeamProposal(BaseModel):
    leader: str
    proposed_team: list[str]


class TeamVote(BaseModel):
    player_name: str
    approve: bool


class QuestVote(BaseModel):
    player_name: str
    vote_pass: bool


class PublicStatement(BaseModel):
    player_name: str
    statement: str

# --- Game state ---

class QuestResult(BaseModel):
    round: int
    team: list[str]
    passed: bool
    fail_count: int


class GameState(BaseModel):
    phase: GamePhase
    round: int
    players: list[Player]
    current_leader: str
    proposed_team: list[str] = []
    team_votes: list[TeamVote] = []
    quest_votes: list[QuestVote] = []
    quest_results: list[QuestResult] = []
    statements: list[PublicStatement] = []
    consecutive_rejections: int = 0
    result: GameResult | None = None

class GameEvent(BaseModel):
    type: str
    payload: dict[str, Any] = {}
    timestamp: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()