import random

import pandas as pd


# How unpredictable the AI drafters are. Each time a team looks at a player, it values
# his talent with a random swing of about this much (0.05 = usually within +/-5%).
# 0 makes every draft identical; above ~0.10 gets wild.
DRAFT_RANDOMNESS = 0.05

# Every roster must end up with exactly this many players per position.
# A team can't draft a player whose position is already full.
ROSTER_SLOTS = {'G': 2, 'F': 2, 'C': 1}

# Thresholds shared by the synergy rules and the player tags shown in the UI.
# Pillars are scaled so the 10th best player in each = 100 (see stat_standardizer.py).
GREAT = 80.0
GOOD = 60.0
NON_SPACER = 5.0
LOW_SPACER = 25.0
ELITE_SPACER = 85.0  # Spacing is spread wider than the other pillars, so its tags need higher bars
GOOD_SPACER = 70.0
BAD_DEFENDER = 25.0

# On/off can move a player's score by at most this much either way (0.20 = +/-20%)
ON_OFF_CAP = 0.20

# How much each pillar counts toward a player's base score, by position.
# The web page reads these too (for the stat breakdowns), so change them only here.
POSITION_WEIGHTS = {
    'G': {'scoring': 0.30, 'playmaking': 0.25, 'defense': 0.20, 'spacing': 0.10, 'rebounding': 0.15},
    'F': {'scoring': 0.25, 'playmaking': 0.25, 'defense': 0.25, 'spacing': 0.10, 'rebounding': 0.15},
    'C': {'scoring': 0.20, 'playmaking': 0.20, 'defense': 0.30, 'spacing': 0.15, 'rebounding': 0.15},
}


def open_positions(roster):
    """Returns the set of positions this roster still has room for."""
    counts = {pos: 0 for pos in ROSTER_SLOTS}
    for p in roster:
        if p.get('position') in counts:
            counts[p['position']] += 1
    return {pos for pos, limit in ROSTER_SLOTS.items() if counts[pos] < limit}


def player_tags(p):
    """Labels a player with the same categories the synergy rules count."""
    tags = []
    if p.get('std_scoring', 0) >= GREAT:
        tags.append('Elite Scorer')
    elif p.get('std_scoring', 0) >= GOOD:
        tags.append('Good Scorer')
    if p.get('std_playmaking', 0) >= GREAT:
        tags.append('Primary Playmaker')
    elif p.get('std_playmaking', 0) >= GOOD:
        tags.append('Secondary Playmaker')
    if p.get('std_rebounding', 0) >= GREAT:
        tags.append('Elite Rebounder')
    elif p.get('std_rebounding', 0) >= GOOD:
        tags.append('Solid Rebounder')
    if p.get('rim_protector', False):
        tags.append('Rim Protector')
    if p.get('std_defense', 0) >= GREAT:
        tags.append('Lockdown Defender')
    elif p.get('std_defense', 0) >= GOOD:
        tags.append('Solid Defender')
    elif p.get('std_defense', 0) <= BAD_DEFENDER:
        tags.append('Bad Defender')
    if p.get('std_spacing', 0) >= ELITE_SPACER:
        tags.append('Elite Spacer')
    elif p.get('std_spacing', 0) >= GOOD_SPACER:
        tags.append('Good Spacer')
    elif p.get('std_spacing', 0) <= NON_SPACER:
        tags.append('Non-Spacer')
    elif p.get('std_spacing', 0) <= LOW_SPACER:
        tags.append('Low Spacer')
    return tags


def calculate_overall_rank(df):
    """
    Calculates overall rank using position-specific pillar weights,
    and applies a Volume Penalty for players averaging under 33 MPG.
    """

    def get_weighted_score(row):
        # 1. Extract primary position
        raw_pos = str(row.get('position', 'F')).upper().strip()
        primary_pos = raw_pos.split('-')[0].split('/')[0]

        # 2. Assign Position-Specific Weights (PG/SG -> G, C -> C, everything else -> F)
        if 'G' in primary_pos:
            w = POSITION_WEIGHTS['G']
        elif 'C' in primary_pos:
            w = POSITION_WEIGHTS['C']
        else:
            w = POSITION_WEIGHTS['F']
        w_score, w_play, w_def, w_space, w_reb = (
            w['scoring'], w['playmaking'], w['defense'], w['spacing'], w['rebounding'])

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
        on_off_multiplier = max(1.0 - ON_OFF_CAP, min(1.0 + ON_OFF_CAP, on_off_multiplier))

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

    playmakers_great = sum(1 for p in roster if p.get('std_playmaking', 0) >= GREAT)
    playmakers_good = sum(1 for p in roster if p.get('std_playmaking', 0) >= GOOD)

    scorers_great = sum(1 for p in roster if p.get('std_scoring', 0) >= GREAT)
    scorers_good = sum(1 for p in roster if p.get('std_scoring', 0) >= GOOD)

    no_spacers = sum(1 for p in roster if p.get('std_spacing', 0) <= NON_SPACER)
    low_spacers = sum(1 for p in roster if p.get('std_spacing', 0) <= LOW_SPACER)

    rebounders_great = sum(1 for p in roster if p.get('std_rebounding', 0) >= GREAT)
    rebounders_good = sum(1 for p in roster if p.get('std_rebounding', 0) >= GOOD)

    rim_protectors = sum(1 for p in roster if p.get('rim_protector', False))
    defenders_great = sum(1 for p in roster if p.get('std_defense', 0) >= GREAT)
    defenders_good = sum(1 for p in roster if p.get('std_defense', 0) >= GOOD)
    bad_defenders = sum(1 for p in roster if p.get('std_defense', 0) <= BAD_DEFENDER)

    # 1. Playmaking
    if playmakers_great >= 1:
        score += 25.0
        breakdown.append({"rule": "Primary Playmaker (80+)", "pts": +25.0, "type": "bonus"})
    elif playmakers_good >= 1:
        score += 12.0
        breakdown.append({"rule": "Secondary Playmaker (60+)", "pts": +12.0, "type": "bonus"})
    else:
        penalty = round(30.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Playmaker", "pts": -penalty, "type": "penalty"})

    # 2. Scoring
    # Note: scorers_good already includes the great ones (80+ is also 60+)
    if scorers_great >= 2:
        score += 25.0
        breakdown.append({"rule": "Dual Elite Scorers (80+)", "pts": +25.0, "type": "bonus"})
    elif scorers_good >= 2:
        score += 15.0
        breakdown.append({"rule": "Dual Good Scorers (60+)", "pts": +15.0, "type": "bonus"})
    elif scorers_good == 1:
        score += 5.0
        breakdown.append({"rule": "Single Primary Scorer", "pts": +5.0, "type": "bonus"})
    else:
        penalty = round(30.0 * completeness_factor, 1)
        score -= penalty
        breakdown.append({"rule": "Missing Scoring Engine", "pts": -penalty, "type": "penalty"})

    # 3. Spacing
    # low_spacers (<=20) already includes the non-spacers (<=5), so it is the total count
    if low_spacers > 1:
        score -= 20.0
        breakdown.append({"rule": "Clogged Paint (>1 Non-Spacer)", "pts": -20.0, "type": "penalty"})
    elif low_spacers == 1 and no_spacers == 1:
        score += 15.0
        breakdown.append({"rule": "Optimal Non-Spacer Balance (1)", "pts": +15.0, "type": "bonus"})
    elif low_spacers == 1:
        score += 8.0
        breakdown.append({"rule": "Acceptable Low-Spacer Balance (1)", "pts": +8.0, "type": "bonus"})
    else:
        score += 20.0
        breakdown.append({"rule": "Open Paint (Everyone can shoot)", "pts": +20.0, "type": "bonus"})

    # 4. Rebounding
    if rebounders_great >= 1:
        score += 15.0
        breakdown.append({"rule": "Elite Glass Cleaner (80+)", "pts": +15.0, "type": "bonus"})
    elif rebounders_good >= 1:
        score += 7.0
        breakdown.append({"rule": "Solid Rebounder (60+)", "pts": +7.0, "type": "bonus"})
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
        breakdown.append({"rule": "Dual Lockdown Defenders (80+)", "pts": +20.0, "type": "bonus"})
    elif defenders_good >= 2:
        score += 10.0
        breakdown.append({"rule": "Dual Solid Defenders (60+)", "pts": +10.0, "type": "bonus"})
    elif defenders_good == 1:
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

    score = round(score, 1)
    return (score, breakdown) if return_breakdown else score


def synergy_changes(roster, player):
    """Lists how each synergy rule would change if this player joined the roster.
    Returns [{"rule": ..., "pts": change}], biggest changes first.
    """
    _, before = calculate_roster_synergy(roster, return_breakdown=True)
    _, after = calculate_roster_synergy(roster + [player], return_breakdown=True)
    before_pts = {b['rule']: b['pts'] for b in before}
    after_pts = {b['rule']: b['pts'] for b in after}

    changes = []
    for rule in list(dict.fromkeys(list(after_pts) + list(before_pts))):
        diff = round(after_pts.get(rule, 0.0) - before_pts.get(rule, 0.0), 1)
        if diff != 0:
            changes.append({"rule": rule, "pts": diff, "gained": rule not in before_pts,
                            "lost": rule not in after_pts})
    changes.sort(key=lambda c: -abs(c['pts']))
    return changes


def setup_draft_state(df, team_order=None):
    """Initializes empty teams and the available player pool.
    team_order is the list of team names in round-1 draft order (defaults to Team 1-30).
    """
    if team_order is None:
        team_order = [f"Team {i}" for i in range(1, 31)]
    teams = {name: [] for name in team_order}

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
    """Executes a single AI draft pick: best available in round 1, talent + synergy after."""
    if pick_index >= len(draft_order) or not available_players:
        return False  # Draft is over

    team_name = draft_order[pick_index]
    roster = teams[team_name]
    round_num = (pick_index // 30) + 1

    # Calculate the team's baseline synergy BEFORE making the pick
    current_synergy = calculate_roster_synergy(roster)

    # AI LOGIC: Evaluate the top 15 available players at positions this team still needs.
    # Round 1 is pure best-player-available; synergy only matters from round 2 on.
    needed = open_positions(roster)
    eval_pool = [(i, p) for i, p in enumerate(available_players) if p.get('position') in needed][:15]
    if not eval_pool:
        return False  # No legal player left for this team

    best_player_idx = eval_pool[0][0]
    best_utility = float('-inf')

    for i, player in eval_pool:
        # Calculate what synergy WOULD be if we drafted this player
        test_roster = roster + [player]
        new_synergy = calculate_roster_synergy(test_roster)

        # The actual chemistry value this specific player brings to the table
        marginal_synergy = new_synergy - current_synergy

        # Each team's scouts see talent slightly differently, so drafts vary
        scouted_talent = player['overall_rank'] * (1.0 + random.gauss(0.0, DRAFT_RANDOMNESS))

        # Utility = Scouted Talent + (Marginal Synergy * 2.0), talent only in round 1
        if round_num == 1:
            utility = scouted_talent
        else:
            utility = scouted_talent + (marginal_synergy * 2.0)

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