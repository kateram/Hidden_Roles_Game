import json
import random
import anthropic
from dotenv import load_dotenv
from backend.game.schemas import (
    GameState, GamePhase, Player,
    TeamProposal, TeamVote, QuestVote,
    PublicStatement, RoleName
)
from backend.game.roles import ROLES, ROLE_LIST, QUEST_TEAM_SIZES
from backend.game.state_machine import (
    apply_team_proposal, apply_team_vote,
    apply_quest_vote, apply_assassination
)
from backend.game.context_builder import build_context
from backend.agents.prompts import GAME_RULES, ROLE_INSTRUCTIONS, ACTION_PROMPTS
from utils import wait

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
    raw = response.content[0].text.strip()
    
    # extract just the JSON object from the response
    start = raw.rfind("{")
    end = raw.rfind("}") + 1
    json_str = raw[start:end]
    
    return json.loads(json_str)


# --- Prompt assembly ---

def build_system_prompt(player: Player) -> str:
    role_instructions = ROLE_INSTRUCTIONS[player.role.name]
    return f"""
{GAME_RULES}

YOUR NAME IS {player.name}. When other players say {player.name} they are talking about YOU.
Always refer to yourself as "I" or "me", never as {player.name}. Your role is {player.role.name}.

{role_instructions}

General behavior rules:

Before acting, carefully read all the information in your context, including
our known allies or known evil players. This information is critical to
playing your role correctly.

- Be concise and direct. Say what you think and move on.
- Do not use filler phrases like "great point", "I appreciate your thinking",
  "thank you for that", or "this has been a productive discussion."
- Do not repeat points that have already been made in the discussion.
- Do not refer to yourself in the third person.
- Remember that other players may be lying 
- Always act in accordance with your role's goals and constraints.
- Your responses will be parsed as JSON — always follow the exact format requested
  with no other text before or after it.
- Never vote to reject a team you proposed or strongly advocated for —
  it is an immediate tell that you are evil
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
                print(f"\n{player.name}: {response['statement']}")
                all_passed = False
            else:
                print(f"{player.name} passes")

        if all_passed:
            print("\n  Everyone passed — ending discussion early")
            break

    wait()
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

    wait()
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

    wait()
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
    print(f"\nQuest {'passed' if last_result.passed else 'failed'} "
          f"({last_result.fail_count} fail cards)")
    print(f"Score — Good: {sum(1 for r in state.quest_results if r.passed)} "
          f"Evil: {sum(1 for r in state.quest_results if not r.passed)}")

    wait()
    return state


def run_assassination(state: GameState) -> GameState:
    print("\n--- Assassination Phase ---")
    print("Good has won three quests. The Assassin now attempts to identify Merlin.")
    assassin = next(p for p in state.players if p.role.name == RoleName.ASSASSIN)
    good_players = [p.name for p in state.players if p.role.team.value == "good"]

    system = build_system_prompt(assassin)
    user = build_user_prompt(
        assassin, state,
        ACTION_PROMPTS["assassinate"](good_players)
    )
    response = call_claude(system, user)
    target_name = response["target"]
    print(f"\n{assassin.name} points at {target_name}: \"You are Merlin.\"")

    wait()
    return apply_assassination(state, target_name)


# --- Game loop ---

def run_game(player_names: list[str]) -> GameState:
    players = create_players(player_names)
    state = create_initial_state(players)

    print("=== AVALON ===")
    print("\nRoles assigned:")
    for p in players:
        print(f"  {p.name}: {p.role.name.value}")

    wait()

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
    merlin = next(p for p in state.players if p.role.is_merlin)
    print(f"Merlin was: {merlin.name}")
    return state