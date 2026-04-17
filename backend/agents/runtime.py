import json
import random
import anthropic
from dotenv import load_dotenv
from game.schemas import (
    GameState, GamePhase, Player,
    TeamProposal, TeamVote, QuestVote,
    PublicStatement, RoleName
)
from game.roles import ROLES, ROLE_LIST, QUEST_TEAM_SIZES
from game.state_machine import (
    apply_team_proposal, apply_team_vote,
    apply_quest_vote, apply_assassination
)
from game.context_builder import build_context
from agents.prompts import GAME_RULES, ROLE_INSTRUCTIONS, ACTION_PROMPTS

load_dotenv()

client = anthropic.Anthropic()

MAX_DISCUSSION_ROUNDS = 3


# --- Setup ---

def create_players(names: list[str]) -> list[Player]:
    roles = ROLE_LIST.copy()
    random.shuffle(roles)
    return [
        Player(name=name, role=ROLES[role])
        for name, role in zip(names, roles)
    ]


def create_initial_state(players: list[Player]) -> GameState:
    return GameState(
        phase=GamePhase.TEAM_PROPOSAL,
        round=1,
        players=players,
        current_leader=players[0].name,
    )


# --- API call ---

def call_claude(system_prompt: str, user_prompt: str) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )
    raw = response.content[0].text
    return json.loads(raw)


# --- Prompt assembly ---

def build_system_prompt(player: Player) -> str:
    role_instructions = ROLE_INSTRUCTIONS[player.role.name]
    return f"""
{GAME_RULES}

You are {player.name} and your role is {player.role.name}.

{role_instructions}

Always act in accordance with your role's goals and constraints.
Your responses will be parsed as JSON — always follow the exact format requested.
""".strip()


def build_user_prompt(player: Player, state: GameState, action_request: str) -> str:
    context = build_context(player, state)
    return f"""
Here is the current state of the game from your perspective:

{json.dumps(context, indent=2)}

{action_request}
""".strip()


# --- Discussion ---

def run_discussion(state: GameState) -> GameState:
    print("\n--- Discussion Phase ---")

    for discussion_round in range(MAX_DISCUSSION_ROUNDS):
        print(f"\n  Round {discussion_round + 1}")
        player_order = state.players.copy()
        random.shuffle(player_order)
        all_passed = True

        for player in player_order:
            system = build_system_prompt(player)
            user = build_user_prompt(player, state, ACTION_PROMPTS["discuss"])
            response = call_claude(system, user)

            if response["respond"]:
                statement = PublicStatement(
                    player_name=player.name,
                    statement=response["statement"],
                )
                state = state.model_copy(update={
                    "statements": state.statements + [statement]
                })
                print(f"{player.name}: {response['statement']}")
                all_passed = False
            else:
                print(f"{player.name} passes")

        if all_passed:
            print("  Everyone passed — ending discussion early")
            break

    return state


# --- Phase runners ---

def run_team_proposal(state: GameState) -> GameState:
    leader = next(p for p in state.players if p.name == state.current_leader)
    team_size = QUEST_TEAM_SIZES[state.round]

    print(f"\n--- Team Proposal (Round {state.round}) ---")
    print(f"Leader: {leader.name}")

    system = build_system_prompt(leader)
    user = build_user_prompt(leader, state, ACTION_PROMPTS["propose_team"](team_size))
    response = call_claude(system, user)

    proposal = TeamProposal(
        leader=leader.name,
        proposed_team=response["proposed_team"],
    )
    print(f"Proposed team: {proposal.proposed_team}")
    return apply_team_proposal(state, proposal)


def run_voting(state: GameState) -> GameState:
    print("\n--- Voting Phase ---")
    for player in state.players:
        system = build_system_prompt(player)
        user = build_user_prompt(
            player, state,
            ACTION_PROMPTS["vote_on_team"](state.proposed_team)
        )
        response = call_claude(system, user)
        vote = TeamVote(
            player_name=player.name,
            approve=response["approve"],
        )
        state = apply_team_vote(state, vote)
        print(f"{player.name} voted: {'approve' if vote.approve else 'reject'}")
    return state


def run_quest(state: GameState) -> GameState:
    print("\n--- Quest Phase ---")
    for player in state.players:
        if player.name not in state.proposed_team:
            continue
        system = build_system_prompt(player)
        user = build_user_prompt(player, state, ACTION_PROMPTS["play_quest_card"])
        response = call_claude(system, user)
        vote = QuestVote(
            player_name=player.name,
            vote_pass=response["vote_pass"],
        )
        state = apply_quest_vote(state, vote)
        print(f"{player.name} played a quest card")

    last_result = state.quest_results[-1]
    print(f"Quest {'passed' if last_result.passed else 'failed'} "
          f"({last_result.fail_count} fail cards)")
    return state


def run_assassination(state: GameState) -> GameState:
    print("\n--- Assassination Phase ---")
    #find the assassin player
    assassin = next(p for p in state.players if p.role.name == RoleName.ASSASSIN)
    # get list of good players
    good_players = [p.name for p in state.players if p.role.team.value == "good"]

    system = build_system_prompt(assassin)
    user = build_user_prompt(
        assassin, state,
        ACTION_PROMPTS["assassinate"](good_players)
    )
    response = call_claude(system, user)
    target_name = response["target"]
    print(f"Assassin targets: {target_name}")
    return apply_assassination(state, target_name)


# --- Game loop ---

def run_game(player_names: list[str]) -> GameState:
    players = create_players(player_names)
    state = create_initial_state(players)

    print("=== AVALON ===")
    print("Roles assigned:")
    for p in players:
        print(f"  {p.name}: {p.role.name}")

    while state.phase != GamePhase.GAME_OVER:
        if state.phase == GamePhase.TEAM_PROPOSAL:
            state = run_discussion(state)
            state = run_team_proposal(state)
        elif state.phase == GamePhase.VOTING:
            state = run_voting(state)
        elif state.phase == GamePhase.QUEST:
            state = run_quest(state)
        elif state.phase == GamePhase.ASSASSINATION:
            state = run_assassination(state)

    print(f"\n=== GAME OVER: {state.result.value} ===")
    return state