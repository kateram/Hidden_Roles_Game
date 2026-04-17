from game.schemas import Player, GameState, Team


def build_context(player: Player, state: GameState) -> dict:

    context = {}

    # --- private knowledge ---
    context["your_name"] = player.name
    context["your_role"] = player.role.name
    context["your_team"] = player.role.team

    if player.role.sees_evil:
        evil_names = [p.name for p in state.players if p.role.team == Team.EVIL]

        if player.role.is_merlin:
            context["known_evil_players"] = evil_names
        else:
            context["evil_allies"] = evil_names

    # --- public game state ---
    context["current_phase"] = state.phase
    context["current_round"] = state.round
    context["current_leader"] = state.current_leader
    context["current_proposed_team"] = state.proposed_team
    context["consecutive_rejections"] = state.consecutive_rejections

    # --- score ---
    context["successful_quests"] = sum(1 for r in state.quest_results if r.passed)
    context["failed_quests"] = sum(1 for r in state.quest_results if not r.passed)

    # --- quest history ---
    context["quest_history"] = [
        {
            "round": r.round,
            "team": r.team,
            "passed": r.passed,
            "fail_count": r.fail_count,
        }
        for r in state.quest_results
    ]

    # --- team proposal history ---
    context["vote_history"] = [
        {
            "player": v.player_name,
            "approved": v.approve,
        }
        for v in state.team_votes
    ]

    # --- statements ---
    context["statements"] = [
        {
            "player": s.player_name,
            "statement": s.statement,
        }
        for s in state.statements
    ]

    return context