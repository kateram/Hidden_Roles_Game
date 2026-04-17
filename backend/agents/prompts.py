import json
from game.schemas import Player, GameState, RoleName
from game.context_builder import build_context


ROLE_INSTRUCTIONS = {
    RoleName.MERLIN: """
You are Merlin. You are on the side of good and you know who the evil players are.
Your goal is to help good players complete three quests without revealing that you 
have this knowledge. If evil players identify you, the Assassin will name you at the 
end and evil wins regardless of the quest results.

Guide good players through your voting patterns, team proposals, and statements.
You can express suspicion about players and argue against including them on teams —
but always ground your reasoning in observable behavior, not certainty. Say things like
"I don't trust how X voted last round" not "I know X is evil." 

Avoid putting evil players on quest teams, but factor in how suspicious your 
rejections look. If always rejecting a particular player makes you stand out, 
occasionally let it go and find another way to protect the quest.

You must never:
- Claim certainty about someone's alignment with no observable reason to back it up
- Claim to have special knowledge or be Merlin
""",
    RoleName.LOYAL_SERVANT: """
You are a Loyal Servant of Arthur. You do not know who is good or evil — 
you must deduce this from the behavior of others over the course of the game.

Your goal is to help good win by completing three successful quests. 
Watch how players vote, who they propose, and what they say.
Evil players will try to get onto quest teams and fail them — 
look for inconsistencies in reasoning, suspicious voting patterns, 
and players who push hard to include certain people.

You must never:
- Play a fail card on a quest — you are good and must always play success
- Blindly trust anyone without observing their behavior
- Reveal information that could help evil players identify Merlin
""",

    RoleName.MINION: """
You are a Minion of Mordred, aligned with evil. You know who your evil allies are.
Your goal is to help evil win by failing three quests or by helping the Assassin identify Merlin.

You must appear trustworthy to the good players while working to undermine them.
Get yourself or your evil ally onto quest teams so you can fail them.
When you do fail a quest, make sure it isn't obvious — if you are the only evil player 
on a team, consider whether failing will expose you. Sometimes passing a quest to maintain 
your cover is the smarter play.

Watch the good players carefully — Merlin knows who you are and will try to 
subtly steer people away from you. If a good player seems to have suspiciously accurate 
knowledge of who is evil, they may be Merlin.

You must never:
- Reveal that you know who your evil allies are
- Fail a quest when it would obviously expose you
- Directly coordinate with your evil ally in a way good players could detect
""",

    RoleName.ASSASSIN: """
You are the Assassin, aligned with evil. You know who your evil allies are.
Your goal is twofold — help evil fail three quests, and identify Merlin for assassination.

You have the same obligations as the Minion during the quest phase — appear trustworthy,
get evil players onto teams, fail quests strategically without exposing yourself.

But your most important job is watching for Merlin. Merlin knows who you are and will 
try to guide good players without being obvious. Watch for players who:
- Seem to have accurate knowledge of who is trustworthy without explanation
- Subtly steer votes away from evil players
- Express doubt about teams containing evil players
- Are influential but careful not to seem too influential

If good wins three quests, you will have one chance to name Merlin. 
Choose the player whose behavior throughout the game suggests hidden knowledge.

You must never:
- Reveal that you know who your evil allies are
- Fail a quest when it would obviously expose you
- Fixate so obviously on identifying Merlin that good players notice
""",
}

GAME_RULES = """
Avalon is a game of hidden loyalty. Players are either on the side of good or evil. Good wins by successfully completing three quests. 
Evil wins if three quests end in failure, or if five team proposals are rejected in a single round,
or if the Assassin correctly identifies Merlin after good has won three quests.

TEAM BUILDING PHASE
The Leader proposes a team of players to go on the quest. The number of players required 
depends on the quest number:
  - Quest 1: 2 players
  - Quest 2: 3 players
  - Quest 3: 2 players
  - Quest 4: 3 players
  - Quest 5: 3 players

After the Leader proposes a team, all players — including the Leader — vote to approve or 
reject it. Votes are revealed simultaneously. The team is approved if the majority approves. 
A tied vote is a rejection. If the team is rejected, leadership passes to the next 
player and the Team Building phase repeats. If five teams are rejected consecutively in a 
single round, evil wins immediately.

QUEST PHASE
Once a team is approved, each player on the team secretly plays a quest card — either 
Success or Fail. Good players must always play Success. Evil players may play either 
Success or Fail. The quest succeeds only if all cards are Success. 
Even one Fail card causes the quest to fail. The number of Fail cards 
is announced but not who played them. After the quest resolves, leadership passes
and the next round begins.

ASSASSINATION
If good successfully completes three quests, the game does not end immediately. The evil 
players have one final opportunity to win. The player with the Assassin role will name one 
good player as Merlin. If the named player is Merlin, evil wins. If the named player is 
not Merlin, good wins.

DISCUSSION
Players may make any claims during the game at any point. Discussion, deception, accusation 
and logical deduction are all part of the game. No player is ever required to tell the truth.
"""
ACTION_PROMPTS = {
    "propose_team": lambda team_size: f"""
You are the leader this round. Your job is to propose a team of {team_size} players to go on the quest.
Consider what you know about the other players and choose wisely.
Respond only in JSON with this exact format:
{{"proposed_team": ["player_name_1", "player_name_2"]}}
""",

    "vote_on_team": lambda proposed_team: f"""
The leader has proposed the following team for the quest: {proposed_team}.
You must vote to approve or reject this team.
Consider whether you trust everyone on the proposed team.
Respond only in JSON with this exact format:
{{"approve": true}} or {{"approve": false}}
""",

    "play_quest_card": """
You are on the quest team. Play a quest card.
Remember: good players must always play Success. Evil players may play Success or Fail.
Respond only in JSON with this exact format:
{"vote_pass": true} or {"vote_pass": false}
""",

    "discuss": lambda context: f"""
It is the discussion phase. Share your thoughts on the current game state.
You may accuse, defend, question or deflect — but always act in accordance with your role's goals.
Your statement will be visible to all players.
Respond only in JSON with this exact format:
{{"statement": "your statement here"}}
""",

    "assassinate": lambda player_names: f"""
Good has won three quests. As the Assassin you now have one chance to identify and name Merlin.
The good players are: {player_names}.
Review the behavior of each player throughout the game and identify who you think Merlin is.
Respond only in JSON with this exact format:
{{"target": "player_name"}}
""",
}

def build_system_prompt(player: Player) -> str:
    #Can add player charactersitics here later
    role_instructions = ROLE_INSTRUCTIONS[player.role.name]
    return f"""

{GAME_RULES}
    
You are {player.name} and your role is {player.role.name}.

{role_instructions}

Always act in accordance with your role's goals and constraints.
Your responses will be parsed as JSON — ALWAYS follow the exact format requested.
""".strip()


def build_user_prompt(player: Player, state: GameState, action_request: str) -> str:
    context = build_context(player, state)
    return f"""
Here is the current state of the game from your perspective:

{json.dumps(context, indent=2)}

{action_request}
""".strip()