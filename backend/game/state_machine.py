from game.schemas import (
    GameState, GamePhase, GameResult,
    TeamProposal, TeamVote, QuestVote,
    QuestResult, Player
)
from game.roles import QUEST_TEAM_SIZES


def get_next_leader(state: GameState) -> str:
    names = [p.name for p in state.players]
    current_index = names.index(state.current_leader)
    return names[(current_index + 1) % len(names)]


def apply_team_proposal(state: GameState, proposal: TeamProposal) -> GameState:
    assert state.phase == GamePhase.TEAM_PROPOSAL, "Not in team proposal phase"
    assert len(proposal.proposed_team) == QUEST_TEAM_SIZES[state.round], \
        f"Wrong team size for round {state.round}"

    return state.model_copy(update={
        "phase": GamePhase.VOTING,
        "proposed_team": proposal.proposed_team,
        "team_votes": [],
    })


def apply_team_vote(state: GameState, vote: TeamVote) -> GameState:
    assert state.phase == GamePhase.VOTING, "Not in voting phase"

    updated_votes = state.team_votes + [vote]

    # not everyone has voted yet
    if len(updated_votes) < len(state.players):
        return state.model_copy(update={"team_votes": updated_votes})

    # all votes in — evaluate
    approve_count = sum(1 for v in updated_votes if v.approve)
    rejected = approve_count <= len(state.players) // 2  # tied = rejection

    if rejected:
        new_rejections = state.consecutive_rejections + 1

        # 5 consecutive rejections — evil wins
        if new_rejections >= 5:
            return state.model_copy(update={
                "phase": GamePhase.GAME_OVER,
                "result": GameResult.EVIL_WINS,
                "team_votes": updated_votes,
                "consecutive_rejections": new_rejections,
            })

        # normal rejection — pass to next leader
        return state.model_copy(update={
            "phase": GamePhase.TEAM_PROPOSAL,
            "team_votes": updated_votes,
            "proposed_team": [],
            "consecutive_rejections": new_rejections,
            "current_leader": get_next_leader(state),
        })

    # approved — move to quest
    return state.model_copy(update={
        "phase": GamePhase.QUEST,
        "team_votes": updated_votes,
        "quest_votes": [],
        "consecutive_rejections": 0,
    })


def apply_quest_vote(state: GameState, vote: QuestVote) -> GameState:
    assert state.phase == GamePhase.QUEST, "Not in quest phase"

    updated_votes = state.quest_votes + [vote]

    # not everyone on the team has voted yet
    if len(updated_votes) < len(state.proposed_team):
        return state.model_copy(update={"quest_votes": updated_votes})

    # all quest votes in — evaluate
    fail_count = sum(1 for v in updated_votes if not v.vote_pass)
    quest_passed = fail_count == 0

    quest_result = QuestResult(
        round=state.round,
        team=state.proposed_team,
        passed=quest_passed,
        fail_count=fail_count,
    )

    updated_results = state.quest_results + [quest_result]
    successes = sum(1 for r in updated_results if r.passed)
    failures = sum(1 for r in updated_results if not r.passed)

    # evil wins — 3 failed quests
    if failures >= 3:
        return state.model_copy(update={
            "phase": GamePhase.GAME_OVER,
            "result": GameResult.EVIL_WINS,
            "quest_votes": updated_votes,
            "quest_results": updated_results,
        })

    # good wins quests — move to assassination
    if successes >= 3:
        return state.model_copy(update={
            "phase": GamePhase.ASSASSINATION,
            "quest_votes": updated_votes,
            "quest_results": updated_results,
        })

    # neither side at 3 yet — next round
    return state.model_copy(update={
        "phase": GamePhase.TEAM_PROPOSAL,
        "round": state.round + 1,
        "quest_votes": updated_votes,
        "quest_results": updated_results,
        "proposed_team": [],
        "current_leader": get_next_leader(state),
    })


def apply_assassination(state: GameState, target_name: str) -> GameState:
    assert state.phase == GamePhase.ASSASSINATION, "Not in assassination phase"

    merlin = next(p for p in state.players if p.role.is_merlin)
    correct = target_name == merlin.name

    return state.model_copy(update={
        "phase": GamePhase.GAME_OVER,
        "result": GameResult.EVIL_WINS if correct else GameResult.GOOD_WINS,
    })