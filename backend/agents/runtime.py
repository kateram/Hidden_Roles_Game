import json
import random
import asyncio
import anthropic
from functools import partial
from dotenv import load_dotenv
from backend.game.schemas import (
    GameState, GamePhase, Player,
    TeamProposal, TeamVote, QuestVote,
    PublicStatement, RoleName, Team
)
from backend.game.roles import ROLES, ROLE_LIST, QUEST_TEAM_SIZES
from backend.game.state_machine import (
    apply_team_proposal, apply_team_vote,
    apply_quest_vote, apply_assassination
)
from backend.game.context_builder import build_context
from backend.agents.prompts import GAME_RULES, ROLE_INSTRUCTIONS, ACTION_PROMPTS
from backend.api.websocket import emit, manager

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


# --- API calls ---

def _call_claude_sync(system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }],
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            raw = response.content[0].text.strip()

            start = raw.find("{")
            if start == -1:
                raise ValueError(f"No JSON found in response: {raw}")

            depth = 0
            for i, char in enumerate(raw[start:], start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(raw[start:i+1])

            raise ValueError(f"No complete JSON object found in response: {raw}")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Failed to get valid JSON after {max_retries} attempts") from e

    raise RuntimeError("Unexpected exit from retry loop")


async def call_claude(system_prompt: str, user_prompt: str, max_retries: int = 3) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_call_claude_sync, system_prompt, user_prompt, max_retries)
    )


def _get_evil_reasoning_sync(system: str, user: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"}
        }],
        messages=[
            {"role": "user", "content": user}
        ]
    )
    return response.content[0].text.strip()


def _get_assassination_reasoning_sync(system: str, user: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"}
        }],
        messages=[
            {"role": "user", "content": user}
        ]
    )
    return response.content[0].text.strip()


# --- Prompt assembly ---

def build_system_prompt(player: Player, state: GameState) -> str:
    role_instructions = ROLE_INSTRUCTIONS[player.role.name]
    all_player_names = [p.name for p in state.players]

    knowledge = ""
    if player.role.is_merlin:
        evil_names = [p.name for p in state.players if p.role.team == Team.EVIL]
        knowledge = f"\nThe evil players are: {', '.join(evil_names)}. This is your most critical private information — do not reveal it directly.\n"
    elif player.role.team == Team.EVIL:
        ally_names = [p.name for p in state.players
                      if p.role.team == Team.EVIL and p.name != player.name]
        knowledge = f"\nYour evil ally is: {', '.join(ally_names)}. This is your most critical private information — protect them and do not reveal this.\n"

    return f"""
{GAME_RULES}

YOUR NAME IS {player.name.upper()}. You are playing as {player.name}.
When other players say "{player.name}" they are talking about you.
Your role is {player.role.name.value}.

The players in this game are: {', '.join(all_player_names)}.
These are the ONLY players that exist. Never reference any player not on this list.
{knowledge}
{role_instructions}

General behavior rules:
- Always refer to yourself as "I" or "me", never as "{player.name}".
- CRITICAL: Never vote to reject a team you proposed or strongly advocated for — this is an immediate tell.
- Before acting, carefully read all the information in your context, including your known allies or known evil players.
- Be concise and direct. Say what you think and move on.
- Do not use filler phrases like "great point", "I appreciate your thinking", "thank you for that".
- Do not repeat points already made in discussion.
- Do not refer to yourself in the third person.
- Remember that other players may be lying.
- Only reference players from the list above.
- Your responses will be parsed as JSON — always follow the exact format requested with no other text before or after it.
""".strip()


def build_user_prompt(player: Player, state: GameState, action_request: str) -> str:
    context = build_context(player, state)
    return f"""
Here is the current state of the game from your perspective:

{json.dumps(context, indent=2)}

{action_request}
""".strip()


# --- Discussion ---

async def run_discussion(state: GameState) -> GameState:
    await emit("discussion_started", {"round": state.round})

    for discussion_round in range(MAX_DISCUSSION_ROUNDS):
        player_order = state.players.copy()
        random.shuffle(player_order)
        all_passed = True

        for player in player_order:
            system = build_system_prompt(player, state)
            user = build_user_prompt(player, state, ACTION_PROMPTS["discuss"])
            response = await call_claude(system, user)

            if response["respond"]:
                statement = PublicStatement(
                    player_name=player.name,
                    statement=response["statement"],
                )
                state = state.model_copy(update={
                    "statements": state.statements + [statement]
                })
                await emit("player_statement", {
                    "player": player.name,
                    "statement": response["statement"],
                    "discussion_round": discussion_round + 1,
                })
                all_passed = False
            else:
                await emit("player_passed", {
                    "player": player.name,
                    "discussion_round": discussion_round + 1,
                })

        if all_passed:
            break

    return state


# --- Phase runners ---

async def run_team_proposal(state: GameState) -> GameState:
    leader = next(p for p in state.players if p.name == state.current_leader)
    team_size = QUEST_TEAM_SIZES[state.round]

    system = build_system_prompt(leader, state)
    user = build_user_prompt(leader, state, ACTION_PROMPTS["propose_team"](team_size))
    response = await call_claude(system, user)

    proposal = TeamProposal(
        leader=leader.name,
        proposed_team=response["proposed_team"],
    )

    await emit("team_proposed", {
        "leader": leader.name,
        "proposed_team": proposal.proposed_team,
        "round": state.round,
    })

    return apply_team_proposal(state, proposal)


async def run_voting(state: GameState) -> GameState:
    for player in state.players:
        system = build_system_prompt(player, state)
        user = build_user_prompt(
            player, state,
            ACTION_PROMPTS["vote_on_team"](state.proposed_team)
        )
        response = await call_claude(system, user)
        vote = TeamVote(
            player_name=player.name,
            approve=response["approve"],
        )
        state = apply_team_vote(state, vote)
        await emit("vote_cast", {
            "player": player.name,
            "approved": response["approve"],
        })

    return state


async def get_evil_reasoning(player: Player, state: GameState, urgent: bool = False) -> str:
    successes = sum(1 for r in state.quest_results if r.passed)
    failures = sum(1 for r in state.quest_results if not r.passed)

    urgency_block = ""
    if urgent:
        urgency_block = """
CRITICAL SITUATION: Good is close to winning and evil has not failed a single quest.
You MUST play a fail card — accept the exposure risk. Letting good win 
uncontested is worse than being discovered.
"""

    system = build_system_prompt(player, state)
    user = build_user_prompt(player, state, f"""
Before deciding whether to pass or fail this quest, reason through the following:
- Who else is on this quest team?
- If you play a fail card, how many suspects will there be?
- What is your current reputation with the other players?
- What is the exposure risk if you fail, and is that risk worth taking given the current score?

Current score: Good has {successes} successful quests, Evil has {failures} failed quests.
{urgency_block}
Respond in plain text with your reasoning. Do not respond in JSON.
""")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_get_evil_reasoning_sync, system, user)
    )


async def get_assassination_reasoning(player: Player, state: GameState) -> str:
    system = build_system_prompt(player, state)
    user = build_user_prompt(player, state, f"""
Before naming Merlin, analyze each good player carefully. Merlin knows who evil is
but must hide that knowledge. Look for these specific signals:

STRONG MERLIN SIGNALS:
- Voted to reject a team containing an evil player without a clear observable reason
- Expressed suspicion of you or your ally early, before any evidence existed
- Deflected or admitted uncertainty when pressed on how they knew something
- Was unusually quiet in early rounds despite being engaged later
- Validated good players quickly and confidently without needing evidence
- Avoided advocating for teams that included you or your ally

WEAK OR MISLEADING SIGNALS (do not rely on these):
- Being vocal or influential — good players can be vocal too
- Making logical arguments — anyone can reason well
- Being the most strategic player — that could be any good player

Go through each good player one by one and score them on the strong signals above.
The player with the most strong signals is most likely Merlin.
Note: Merlin may have deliberately let evil players through sometimes to protect
their cover — don't dismiss someone just because they didn't block every evil team.

Respond in plain text with your reasoning. Do not respond in JSON.
""")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_get_assassination_reasoning_sync, system, user)
    )


async def run_quest(state: GameState) -> GameState:
    successes = sum(1 for r in state.quest_results if r.passed)
    failures = sum(1 for r in state.quest_results if not r.passed)
    urgent = successes >= 2 and failures <= 1

    await emit("quest_started", {
        "round": state.round,
        "team": state.proposed_team,
    })

    for player in state.players:
        if player.name not in state.proposed_team:
            continue

        system = build_system_prompt(player, state)

        if player.role.team == Team.EVIL:
            reasoning = await get_evil_reasoning(player, state, urgent=urgent)
            await emit("evil_reasoning", {
                "player": player.name,
                "reasoning": reasoning,
            })
            action_prompt = f"""
You have already reasoned through this decision:

{reasoning}

Based on this reasoning, now play your quest card.
Respond only in JSON with this exact format and no other text before or after it.
{{"vote_pass": true}} or {{"vote_pass": false}}
"""
        else:
            action_prompt = ACTION_PROMPTS["play_quest_card"]

        user = build_user_prompt(player, state, action_prompt)
        response = await call_claude(system, user)
        vote = QuestVote(
            player_name=player.name,
            vote_pass=response["vote_pass"],
        )
        state = apply_quest_vote(state, vote)
        await emit("quest_card_played", {
            "player": player.name,
        })

    last_result = state.quest_results[-1]
    await emit("quest_result", {
    "round": state.round,
    "passed": last_result.passed,
    "fail_count": last_result.fail_count,
    "good_score": sum(1 for r in state.quest_results if r.passed),
    "evil_score": sum(1 for r in state.quest_results if not r.passed),
})

    await manager.wait_for_continue() 

    return state


async def run_assassination(state: GameState) -> GameState:
    assassin = next(p for p in state.players if p.role.name == RoleName.ASSASSIN)
    good_players = [p.name for p in state.players if p.role.team == Team.GOOD]

    await emit("assassination_started", {
        "assassin": assassin.name,
        "good_players": good_players,
    })

    reasoning = await get_assassination_reasoning(assassin, state)
    await emit("assassination_reasoning", {
        "player": assassin.name,
        "reasoning": reasoning,
    })

    action_prompt = f"""
You have already reasoned through this decision:

{reasoning}

Based on this reasoning, name the player you believe is Merlin.
Respond only in JSON with this exact format and no other text before or after it.
{{"target": "player_name"}}
"""

    system = build_system_prompt(assassin, state)
    user = build_user_prompt(assassin, state, action_prompt)
    response = await call_claude(system, user)
    target_name = response["target"]

    await emit("assassination_target", {
        "assassin": assassin.name,
        "target": target_name,
    })

    return apply_assassination(state, target_name)


# --- Game loop ---

async def run_game(player_names: list[str]) -> GameState:
    players = create_players(player_names)
    state = create_initial_state(players)

    await emit("game_started", {
        "players": [
            {
                "name": p.name,
                "role": p.role.name.value,
                "team": p.role.team.value,
                "is_merlin": p.role.is_merlin,
                "is_evil": p.role.team == Team.EVIL,
            }
            for p in players
        ]
    })

    while state.phase != GamePhase.GAME_OVER:
        if state.phase == GamePhase.TEAM_PROPOSAL:
            state = await run_discussion(state)
            state = await run_team_proposal(state)
        elif state.phase == GamePhase.VOTING:
            state = await run_voting(state)
        elif state.phase == GamePhase.QUEST:
            state = await run_quest(state)
        elif state.phase == GamePhase.ASSASSINATION:
            state = await run_assassination(state)

    merlin = next(p for p in state.players if p.role.is_merlin)
    await emit("game_over", {
        "result": state.result.value,
        "merlin": merlin.name,
    })

    return state