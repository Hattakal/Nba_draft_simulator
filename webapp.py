import random

from flask import Flask, jsonify, render_template, request
import pandas as pd

# Updated imports to match the new functions in draft_engine.py
from draft_engine import (
    calculate_overall_rank,
    calculate_roster_synergy,
    setup_draft_state,
    execute_single_ai_pick,
    open_positions,
    player_tags,
    synergy_changes,
    ROSTER_SLOTS,
    POSITION_WEIGHTS
)
from nba_teams import NBA_TEAMS, TEAM_NAMES

app = Flask(__name__, template_folder='Templates')  # folder name is capitalized; Linux servers are case-sensitive

# How much roster synergy counts in the final team score, relative to total talent.
SYNERGY_WEIGHT = 1.0

# Global storage for active simulation state, now tracking the available pool
DRAFT_STATE = {
    "df": None,
    "teams": {},
    "draft_board": [],
    "available_players": [],
    "draft_order": [],
    "current_pick_index": 0,
    "user_team": None  # Set when the draft starts, from the chosen team
}


@app.route('/')
def home():
    """Serves the main website interface."""
    return render_template('index.html', nba_teams=NBA_TEAMS, position_weights=POSITION_WEIGHTS)


@app.route('/api/init-draft', methods=['POST'])
def init_draft():
    """Loads the database and sets up the draft state without simulating all picks.
    Accepts {"draft_slot": 1-30 or "random", "team": an NBA team name or "random"}.
    The other 29 teams are shuffled into the remaining draft spots.
    """
    try:
        data = request.get_json(silent=True) or {}
        slot = data.get('draft_slot', 'random')
        if slot == 'random':
            slot = random.randint(1, 30)
        slot = int(slot)
        if not 1 <= slot <= 30:
            return jsonify({"status": "error", "message": "Draft slot must be between 1 and 30"}), 400

        user_team = data.get('team', 'random')
        if user_team == 'random':
            user_team = random.choice(TEAM_NAMES)
        if user_team not in TEAM_NAMES:
            return jsonify({"status": "error", "message": f"Unknown team: {user_team}"}), 400

        # Shuffle the AI teams, then put the user's team in the chosen spot
        team_order = [t for t in TEAM_NAMES if t != user_team]
        random.shuffle(team_order)
        team_order.insert(slot - 1, user_team)

        df = pd.read_csv("nba_standardized_profiles_2026.csv")
        df = calculate_overall_rank(df)

        # Clean positions
        if 'position' in df.columns:
            df['position'] = df['position'].astype(str).str.upper().apply(lambda x: x.split('-')[0])
            position_map = {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C', 'G': 'G', 'F': 'F'}
            df['position'] = df['position'].map(position_map).fillna('F')

        # Initialize the draft board, but do not make any picks yet
        teams, available_players, draft_order = setup_draft_state(df, team_order)

        DRAFT_STATE["df"] = df
        DRAFT_STATE["teams"] = teams
        DRAFT_STATE["draft_board"] = []
        DRAFT_STATE["available_players"] = available_players
        DRAFT_STATE["draft_order"] = draft_order
        DRAFT_STATE["current_pick_index"] = 0
        DRAFT_STATE["user_team"] = user_team

        return jsonify({"status": "success", "message": "Draft initialized. Ready to start.",
                        "user_team": user_team, "draft_slot": slot, "team_order": team_order})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/make-ai-pick', methods=['POST'])
def make_ai_pick():
    """Advances the draft by exactly one AI pick."""
    if DRAFT_STATE["current_pick_index"] >= len(DRAFT_STATE["draft_order"]):
        return jsonify({"status": "complete"})

    current_team = DRAFT_STATE["draft_order"][DRAFT_STATE["current_pick_index"]]

    # If it is the user's turn, pause the AI loop and alert the frontend
    if current_team == DRAFT_STATE["user_team"]:
        return jsonify({"status": "user_turn", "team": current_team})

    # Let the AI make a pick
    picked = execute_single_ai_pick(
        DRAFT_STATE["teams"],
        DRAFT_STATE["available_players"],
        DRAFT_STATE["draft_order"],
        DRAFT_STATE["current_pick_index"],
        DRAFT_STATE["draft_board"]
    )
    if not picked:
        return jsonify({"status": "error", "message": f"{current_team} has no legal player left"}), 500

    DRAFT_STATE["current_pick_index"] += 1

    return jsonify({"status": "success", "team": current_team})


@app.route('/api/available-players', methods=['GET'])
def get_available_players():
    """Returns the whole available pool (sorted best first) so the UI can search it.
    Each player gets their synergy tags and whether your roster still has room for them."""
    user_roster = DRAFT_STATE["teams"].get(DRAFT_STATE["user_team"], [])
    open_slots = open_positions(user_roster)
    current_synergy = calculate_roster_synergy(user_roster)
    players = []
    for p in DRAFT_STATE["available_players"]:
        slot_open = p['position'] in open_slots
        # How much this player would change YOUR roster's synergy (only for legal picks)
        synergy_gain = round(calculate_roster_synergy(user_roster + [p]) - current_synergy, 1) if slot_open else None
        changes = synergy_changes(user_roster, p) if slot_open else []
        players.append({
            "name": p['name'],
            "position": p['position'],
            "overall_rank": round(p['overall_rank'], 1),
            "std_scoring": p.get('std_scoring', 0),
            "std_playmaking": p.get('std_playmaking', 0),
            "std_defense": p.get('std_defense', 0),
            "std_spacing": p.get('std_spacing', 0),
            "std_rebounding": p.get('std_rebounding', 0),
            "tags": player_tags(p),
            "slot_open": slot_open,
            "synergy_gain": synergy_gain,
            "synergy_changes": changes,
            "age": p.get('Age'),
            "games": p.get('G'),
            "mpg": p.get('MPG', 0.0),
            "base_score": p.get('base_score', 0.0),
            "vol_multiplier": p.get('vol_multiplier', 1.0),
            "on_off_multiplier": p.get('on_off_multiplier', 1.0),
            "on_off_raw": p.get('on_off_raw', 0.0),
        })
    return jsonify(players)


@app.route('/api/my-team', methods=['GET'])
def get_my_team():
    """Returns your team, roster, position counts and current synergy breakdown."""
    roster = DRAFT_STATE["teams"].get(DRAFT_STATE["user_team"], [])
    filled = {pos: sum(1 for p in roster if p['position'] == pos) for pos in ROSTER_SLOTS}
    synergy, breakdown = calculate_roster_synergy(roster, return_breakdown=True)
    return jsonify({
        "team": DRAFT_STATE["user_team"],
        "filled": filled,
        "slots": ROSTER_SLOTS,
        "roster": [{"name": p['name'], "position": p['position'], "overall_rank": round(p['overall_rank'], 1),
                    "tags": player_tags(p)} for p in roster],
        "talent": round(sum(p['overall_rank'] for p in roster), 1),
        "synergy": synergy,
        "synergy_breakdown": breakdown,
    })


@app.route('/api/make-user-pick', methods=['POST'])
def make_user_pick():
    """Processes the manual pick from the user."""
    data = request.json
    player_name = data.get('player_name')

    # Search for the player in the available pool
    user_roster = DRAFT_STATE["teams"][DRAFT_STATE["user_team"]]

    for i, player in enumerate(DRAFT_STATE["available_players"]):
        if player['name'] == player_name:
            if player['position'] not in open_positions(user_roster):
                limit = ROSTER_SLOTS.get(player['position'], 0)
                return jsonify({"status": "error",
                                "message": f"Your {player['position']} spots are full ({limit}/{limit})"}), 400

            drafted_player = DRAFT_STATE["available_players"].pop(i)
            team_name = DRAFT_STATE["user_team"]

            # Add to roster
            DRAFT_STATE["teams"][team_name].append(drafted_player)

            # Add to draft board
            pick_idx = DRAFT_STATE["current_pick_index"]
            round_num = (pick_idx // 30) + 1

            DRAFT_STATE["draft_board"].append({
                "Round": round_num,
                "Pick": pick_idx + 1,
                "Team": team_name,
                "Player": drafted_player['name'],
                "Position": drafted_player['position'],
                "Overall": round(drafted_player['overall_rank'], 1),
                "base_score": round(drafted_player.get('base_score', 0), 1),
                "MPG": drafted_player.get('MPG', 0.0),
                "vol_multiplier": drafted_player.get('vol_multiplier', 1.0),
                "on_off_mult": drafted_player.get('on_off_multiplier', 1.0),
                "on_off_raw": drafted_player.get('on_off_raw', 0.0),
                "std_scoring": round(drafted_player.get('std_scoring', 0), 1),
                "std_playmaking": round(drafted_player.get('std_playmaking', 0), 1),
                "std_defense": round(drafted_player.get('std_defense', 0), 1),
                "std_spacing": round(drafted_player.get('std_spacing', 0), 1),
                "std_rebounding": round(drafted_player.get('std_rebounding', 0), 1),
                "rim_protector": drafted_player.get('rim_protector', False)
            })

            DRAFT_STATE["current_pick_index"] += 1
            return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Player not found"}), 404

@app.route('/api/draft-board', methods=['GET'])
def get_draft_board():
    """Returns the full log of draft picks for the UI."""
    return jsonify(DRAFT_STATE["draft_board"])


@app.route('/api/standings', methods=['GET'])
def get_standings():
    if not DRAFT_STATE["teams"]:
        return jsonify([])

    team_evaluations = []
    for name, roster in DRAFT_STATE["teams"].items():
        total_talent = sum(p['overall_rank'] for p in roster)
        avg_talent = total_talent / len(roster) if roster else 0

        # Get score AND breakdown from draft_engine
        synergy, breakdown = calculate_roster_synergy(roster, return_breakdown=True)
        weighted_synergy = synergy * SYNERGY_WEIGHT
        final_team_score = total_talent + weighted_synergy

        team_evaluations.append({
            "team": name,
            "is_user": name == DRAFT_STATE["user_team"],
            "talent": round(total_talent, 1),
            "avg_talent": round(avg_talent, 1),
            "synergy": round(synergy, 1),
            "weighted_synergy": round(weighted_synergy, 1),
            "synergy_weight": SYNERGY_WEIGHT,
            "total_score": round(final_team_score, 1),
            "roster": roster,
            "synergy_breakdown": breakdown
        })

    team_evaluations.sort(key=lambda x: x['total_score'], reverse=True)
    return jsonify(team_evaluations)


if __name__ == '__main__':
    app.run(debug=True, port=5000)