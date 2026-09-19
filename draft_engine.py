import pandas as pd


def calculate_overall_rank(df):
    """
    Calculates overall rank using position-specific pillar weights,
    and applies a Volume Penalty for players averaging under 33 MPG.
    """

    def get_weighted_score(row):
        # 1. Extract primary position
        raw_pos = str(row.get('position', 'F')).upper().strip()
        primary_pos = raw_pos.split('-')[0].split('/')[0]

        # 2. Assign Position-Specific Weights
        if 'G' in primary_pos:
            w_score, w_play, w_def, w_space, w_reb = 0.30, 0.25, 0.20, 0.10, 0.15
        elif 'C' in primary_pos:
            w_score, w_play, w_def, w_space, w_reb = 0.20, 0.20, 0.30, 0.15, 0.15
        else:
            w_score, w_play, w_def, w_space, w_reb = 0.25, 0.25, 0.25, 0.10, 0.15

        # 3. Calculate Base Per-100 Score
        base_score = (
                (row.get('std_scoring', 0.0) * w_score) +
                (row.get('std_playmaking', 0.0) * w_play) +
                (row.get('std_defense', 0.0) * w_def) +
                (row.get('std_spacing', 0.0) * w_space) +
                (row.get('std_rebounding', 0.0) * w_reb)
        )

        # 4. Calculate MPG and Apply Volume Penalty Curve
        total_mp = float(row.get('MP', 0.0))
        games = float(row.get('G', 1.0))
        mpg = total_mp / games if games > 0 else 0.0

        if mpg >= 33.0:
            minutes_multiplier = 1.0
        else:
            minutes_multiplier = 0.60 + ((mpg - 15.0) * (0.40 / 18.0))
            minutes_multiplier = max(0.20, minutes_multiplier)

        # --- NEW: ON/OFF MULTIPLIER ---
        raw_on_off = float(row.get('On-Off_pbp', 0.0))

        # Calculate the multiplier (e.g., +16 = 1.32)
        on_off_multiplier = 1.0 + (raw_on_off / 50.0)

        # Cap on the on-off numbers for outliers
        on_off_multiplier = max(0.80, min(1.30, on_off_multiplier))

        # Apply both multipliers to the base score
        final_score = base_score * minutes_multiplier * on_off_multiplier

        # 5. Save all calculated values into the row dictionary
        row['base_score'] = round(base_score, 1)
        row['MPG'] = round(mpg, 1)
        row['vol_multiplier'] = round(minutes_multiplier, 2)
        row['on_off_multiplier'] = round(on_off_multiplier, 2)
        row['on_off_raw'] = round(raw_on_off, 1)
        row['overall_rank'] = round(final_score, 1)

        return row

    # Apply the nested function across the dataframe and return the updated dataframe
    return df.apply(get_weighted_score, axis=1)
def calculate_roster_synergy(roster, return_breakdown=False):
    """
    Evaluates a roster and scores synergy fit.
    Returns (score, breakdown_list) if return_breakdown is True.
    """
    score = 0.0
    breakdown = []

    if not roster:
        return (score, breakdown) if return_breakdown else score

    roster_size = len(roster)
    completeness_factor = roster_size / 5.0

    playmakers_great = sum(1 for p in roster if p.get('std_playmaking', 0) >= 65.0)
    playmakers_good = sum(1 for p in roster if p.get('std_playmaking', 0) >= 50.0)

    scorers_great = sum(1 for p in roster if p.get('std_scoring', 0) >= 65.0)
    scorers_good = sum(1 for p in roster if p.get('std_scoring', 0) >= 50.0)

    no_spacers = sum(1 for p in roster if p.get('std_spacing', 0) <= 5.0)
    low_spacers = sum(1 for p in roster if p.get('std_spacing', 0) <= 20.0)

    rebounders_great = sum(1 for p in roster if p.get('std_rebounding', 0) >= 65.0)
    rebounders_good = sum(1 for p in roster if p.get('std_rebounding', 0) >= 50.0)

    rim_protectors = sum(1 for p in roster if p.get('rim_protector', False))
    defenders_great = sum(1 for p in roster if p.get('std_defense', 0) >= 65.0)
    defenders_good = sum(1 for p in roster if p.get('std_defense', 0) >= 50.0)
    bad_defenders = sum(1 for p in roster if p.get('std_defense', 0) <= 30.0)

    # 1. Playmaking
    if playmakers_great >= 1:
        score += 25.0
        breakdown.append({"rule": "Primary Playmaker (65+)", "pts": +25.0, "type": "bonus"})
    elif playmakers_good >= 1:
        score += 12.0
        breakdown.append({"rule": "Secondary Playmaker (50+)", "pts": +12.0, "type": "bonus"})
    else:
        penalty = round(30.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Playmaker", "pts": -penalty, "type": "penalty"})

    # 2. Scoring
    if scorers_great >= 2:
        score += 25.0
        breakdown.append({"rule": "Dual Elite Scorers (65+)", "pts": +25.0, "type": "bonus"})
    elif (scorers_great + scorers_good) >= 2:
        score += 15.0
        breakdown.append({"rule": "Dual Good Scorers (50+)", "pts": +15.0, "type": "bonus"})
    elif (scorers_great + scorers_good) == 1:
        score += 5.0
        breakdown.append({"rule": "Single Primary Scorer", "pts": +5.0, "type": "bonus"})
    else:
        penalty = round(30.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Scoring Engine", "pts": -penalty, "type": "penalty"})

    # 3. Spacing
    if no_spacers == 1:
        score += 15.0
        breakdown.append({"rule": "Optimal Non-Spacer Balance (1)", "pts": +15.0, "type": "bonus"})
    elif low_spacers == 1:
        score += 8.0
        breakdown.append({"rule": "Acceptable Low-Spacer Balance (1)", "pts": +8.0, "type": "bonus"})
    elif (no_spacers + low_spacers) > 1:
        score -= 20.0
        breakdown.append({"rule": "Clogged Paint (>1 Non-Spacer)", "pts": -20.0, "type": "penalty"})
    elif (no_spacers + low_spacers) < 1:
        score += 20.0
        breakdown.append({"rule": "Open Paint (Everyone can shoot)", "pts": +20.0, "type": "bonus"})

    # 4. Rebounding
    if rebounders_great >= 1:
        score += 15.0
        breakdown.append({"rule": "Elite Glass Cleaner (65+)", "pts": +15.0, "type": "bonus"})
    elif rebounders_good >= 1:
        score += 7.0
        breakdown.append({"rule": "Solid Rebounder (50+)", "pts": +7.0, "type": "bonus"})
    else:
        penalty = round(15.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Rebounder", "pts": -penalty, "type": "penalty"})

    # 5. Rim Protection & Defense Anchor
    if rim_protectors >= 1:
        score += 15.0
        breakdown.append({"rule": "Rim Protector Present", "pts": +15.0, "type": "bonus"})
    else:
        penalty = round(25.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Rim Protection", "pts": -penalty, "type": "penalty"})

    if defenders_great >= 2:
        score += 20.0
        breakdown.append({"rule": "Dual Lockdown Defenders (65+)", "pts": +20.0, "type": "bonus"})
    elif (defenders_great + defenders_good) >= 2:
        score += 10.0
        breakdown.append({"rule": "Dual Solid Defenders (50+)", "pts": +10.0, "type": "bonus"})
    elif (defenders_great + defenders_good) == 1:
        score += 5.0
        breakdown.append({"rule": "Single Defensive Anchor", "pts": +5.0, "type": "bonus"})
    else:
        penalty = round(20.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Defense", "pts": -penalty, "type": "penalty"})

    # 6. Defensive Liabilities
    if bad_defenders > 2:
        penalty = (bad_defenders - 2) * 15.0
        score -= penalty
        breakdown.append({"rule": f"Multiple Bad Defenders ({bad_defenders})", "pts": -penalty, "type": "penalty"})
    elif bad_defenders < 1:
        score += 10.0
        breakdown.append({"rule": "No defensive liability", "pts": +10.0, "type": "bonus"})


        # Always round cleanly
        score = round(score, 1)

    score = round(score, 1)
    return (score, breakdown) if return_breakdown else score


def setup_draft_state(df):
    """Initializes empty teams and the available player pool."""
    # Create 30 generic teams (or use NBA team names)
    teams = {f"Team {i}": [] for i in range(1, 31)}

    # Sort the initial pool by overall rank so the best are at the top
    available_players = df.sort_values(by='overall_rank', ascending=False).to_dict(orient='records')

    # Standard snake draft order (Round 1: 1-30, Round 2: 30-1, etc.)
    base_order = list(teams.keys())
    draft_order = []
    for round_num in range(1, 6):
        if round_num % 2 == 1:
            draft_order.extend(base_order)
        else:
            draft_order.extend(reversed(base_order))

    return teams, available_players, draft_order


def execute_single_ai_pick(teams, available_players, draft_order, pick_index, draft_log):
    """Executes a single AI draft pick based on synergy and best available."""
    if pick_index >= len(draft_order) or not available_players:
        return False  # Draft is over

    team_name = draft_order[pick_index]
    roster = teams[team_name]
    round_num = (pick_index // 30) + 1

    # Calculate the team's baseline synergy BEFORE making the pick
    current_synergy = calculate_roster_synergy(roster)

    # AI LOGIC: Evaluate synergy for the top 15 available players
    best_player_idx = 0
    best_utility = -999

    eval_pool = available_players[:15]

    for i, player in enumerate(eval_pool):
        # Calculate what synergy WOULD be if we drafted this player
        test_roster = roster + [player]
        new_synergy = calculate_roster_synergy(test_roster)

        # The actual chemistry value this specific player brings to the table
        marginal_synergy = new_synergy - current_synergy

        # Utility = Player's Base Talent + (Marginal Synergy * 2.0)
        utility = player['overall_rank'] + (marginal_synergy * 2.0)

        if utility > best_utility:
            best_utility = utility
            best_player_idx = i

    # Pop the selected player from the available pool
    drafted_player = available_players.pop(best_player_idx)
    teams[team_name].append(drafted_player)

    # Log the pick
    draft_log.append({
        "Round": round_num,
        "Pick": pick_index + 1,
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

    return drafted_player