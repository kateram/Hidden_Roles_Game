from backend.game.schemas import Role, RoleName, Team


# --- Role definitions ---
""" This is for role look up by name"""
ROLES = {
    RoleName.MERLIN: Role(
        name=RoleName.MERLIN,
        team=Team.GOOD,
        sees_evil=True,
        is_merlin=True,
    ),
    RoleName.LOYAL_SERVANT: Role(
        name=RoleName.LOYAL_SERVANT,
        team=Team.GOOD,
        sees_evil=False,
        is_merlin=False,
    ),
    RoleName.MINION: Role(
        name=RoleName.MINION,
        team=Team.EVIL,
        sees_evil=True,
        is_merlin=False,
    ),
    RoleName.ASSASSIN: Role(
        name=RoleName.ASSASSIN,
        team=Team.EVIL,
        sees_evil=True,
        is_merlin=False,
    ),
}


# --- Quest team sizes for 5 players ---

QUEST_TEAM_SIZES = {
    1: 2,
    2: 3,
    3: 2,
    4: 3,
    5: 3,
}


# --- Role assignment for 5 players ---
""" This is what gets shuffled for role assignment"""

ROLE_LIST = [
    RoleName.MERLIN,
    RoleName.LOYAL_SERVANT,
    RoleName.LOYAL_SERVANT,
    RoleName.MINION,
    RoleName.ASSASSIN,
]