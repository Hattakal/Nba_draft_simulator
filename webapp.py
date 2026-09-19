from flask import Flask, jsonify, render_template, request
import pandas as pd

# Updated imports to match the new functions in draft_engine.py
from draft_engine import (
    calculate_overall_rank,
    calculate_roster_synergy,
    setup_draft_state,
    execute_single_ai_pick
)

app = Flask(__name__)

# Global storage for active simulation state, now tracking the available pool
DRAFT_STATE = {
    "df": None,
    "teams": {},
    "draft_board": [],
    "available_players": [],
    "draft_order": [],
    "current_pick_index": 0,
    "user_team": "Team 1"  # You will draft for Team 1
}


@app.route('/')
def home():
    """Serves the main website interface."""
    return render_template('index.html')


@app.route('/api/init-draft', methods=['POST'])
def init_draft():
    """Loads the database and sets up the draft state without simulating all picks."""
    try:
        df = pd.read_csv("nba_standardized_profiles_2026.csv")
        df = calculate_overall_rank(df)

        # Clean positions
        if 'position' in df.columns:
            df['position'] = df['position'].astype(str).str.upper().apply(lambda x: x.split('-')[0])
            position_map = {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C', 'G': 'G', 'F': 'F'}
            df['position'] = df['position'].map(position_map).fillna('F')

        # NEW: Initialize the draft board, but do not make any picks yet
        teams, available_players, draft_order = setup_draft_state(df)

        DRAFT_STATE["df"] = df
        DRAFT_STATE["teams"] = teams
        DRAFT_STATE["draft_board"] = []
        DRAFT_STATE["available_players"] = available_players
        DRAFT_STATE["draft_order"] = draft_order
        DRAFT_STATE["current_pick_index"] = 0

        return jsonify({"status": "success", "message": "Draft initialized. Ready to start."})
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
    execute_single_ai_pick(
        DRAFT_STATE["teams"],
        DRAFT_STATE["available_players"],
        DRAFT_STATE["draft_order"],
        DRAFT_STATE["current_pick_index"],
        DRAFT_STATE["draft_board"]
    )

    DRAFT_STATE["current_pick_index"] += 1

    return jsonify({"status": "success", "team": current_team})


@app.route('/api/available-players', methods=['GET'])
def get_available_players():
    """Returns the top 50 available players to keep the UI lightweight."""
    return jsonify(DRAFT_STATE["available_players"][:50])


@app.route('/api/make-user-pick', methods=['POST'])
def make_user_pick():
    """Processes the manual pick from the user."""
    data = request.json
    player_name = data.get('player_name')

    # Search for the player in the available pool
    for i, player in enumerate(DRAFT_STATE["available_players"]):
        if player['name'] == player_name:
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
        avg_talent = sum(p['overall_rank'] for p in roster) / len(roster) if roster else 0

        # Get score AND breakdown from draft_engine
        synergy, breakdown = calculate_roster_synergy(roster, return_breakdown=True)
        final_team_score = avg_talent + synergy

        team_evaluations.append({
            "team": name,
            "avg_talent": round(avg_talent, 1),
            "synergy": round(synergy, 1),
            "total_score": round(final_team_score, 1),
            "roster": roster,
            "synergy_breakdown": breakdown
        })

    team_evaluations.sort(key=lambda x: x['total_score'], reverse=True)
    return jsonify(team_evaluations)


if __name__ == '__main__':
    app.run(debug=True, port=5000)