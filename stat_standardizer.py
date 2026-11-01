import re
import unicodedata

import pandas as pd
import numpy as np


# Players whose first name differs between sources (normalized key -> normalized key)
NAME_ALIASES = {
    'ron holland': 'ronald holland',
}

NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}

# The Nth best player in each pillar is scaled to 100 (see process_and_standardize_profiles)
ANCHOR_RANK = 10


def name_key(name):
    """Normalizes a player name so different sources match.
    'Nikola Jokić' -> 'nikola jokic', 'A.J. Green' -> 'aj green', 'Jimmy Butler III' -> 'jimmy butler'
    """
    text = str(name).replace('ё', 'e').replace('Ё', 'E')  # Cyrillic ё doesn't decompose like Latin accents
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r"[^a-z0-9 ]", "", text.lower())
    words = [w for w in text.split() if w not in NAME_SUFFIXES]
    key = " ".join(words)
    return NAME_ALIASES.get(key, key)


# =====================================================================
#  PROFILE METRIC HELPER FUNCTIONS
# =====================================================================

def compute_raw_spacing(row):
    """Calculates spacing based on 3-point volume, accuracy, and depth."""
    fg3a_100 = float(row.get('3PA_100', 0.0))
    fg3_pct = float(row.get('3P%_100', 0.0))
    return fg3a_100 * (1.0 + fg3_pct)


def compute_raw_rebounding(row):
    """Calculates raw rebounding from per 100 offensive & defensive boards."""
    orb = float(row.get('ORB_100', 0.0))
    drb = float(row.get('DRB_100', 0.0))
    return (orb * 1.2) + drb


def compute_raw_scoring(row):
    """Calculates raw scoring output using Per 100 Points and True Shooting efficiency."""
    pts = float(row.get('PTS_100', 0.0))
    ts_pct = float(row.get('TS%_adv', 0.0))
    return pts * (ts_pct / 0.55 if ts_pct > 0 else 1.0)


def compute_raw_playmaking(row):
    """Calculates playmaking based on Per 100 Assists and Assist-to-Turnover ratio."""
    ast = float(row.get('AST_100', 0.0))
    tov = float(row.get('TOV_100', 0.1))
    ast_tov_ratio = ast / tov if tov > 0 else ast
    return ast * (1.0 + (ast_tov_ratio * 0.1))


# =====================================================================
#  MAIN PROCESSING & STANDARDIZATION PIPELINE
# =====================================================================

def process_and_standardize_profiles():
    input_file = "nba_ultimate_stats_2026.csv"
    lebron_file = "lebron-data-2026.csv"  # Matched to your exact filename
    output_file = "nba_standardized_profiles_2026.csv"

    print(f"📖 Loading datasets...")
    try:
        df = pd.read_csv(input_file)
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{input_file}'.")
        return

    # Merge D-LEBRON data
    try:
        df_lebron = pd.read_csv(lebron_file)

        # Rename columns to ensure a clean merge regardless of source naming
        df_lebron = df_lebron.rename(columns={
            'Player': 'name',
            'D_LEBRON': 'D-LEBRON',
            'D-LEBRON Value': 'D-LEBRON'
        })

        # Match on a normalized name key so accents, capitalization and
        # punctuation differences ("Jokić" vs "Jokic", "A.J." vs "Aj") don't break the merge
        df['_key'] = df['name'].apply(name_key)
        df_lebron['_key'] = df_lebron['name'].apply(name_key)
        df_lebron = df_lebron.drop_duplicates(subset=['_key'], keep='first')
        df = df.merge(df_lebron[['_key', 'D-LEBRON']], on='_key', how='left').drop(columns=['_key'])

        unmatched = df.loc[df['D-LEBRON'].isna() & (df.get('MP', 0) >= 500), 'name'].tolist()
        print("✅ Successfully merged D-LEBRON metrics.")
        if unmatched:
            print(f"⚠️ {len(unmatched)} qualified players had no D-LEBRON match (set to 0.0): {unmatched}")
    except FileNotFoundError:
        print(f"⚠️ Warning: '{lebron_file}' not found. Defaulting missing D-LEBRON to 0.0 (League Avg).")
        df['D-LEBRON'] = 0.0

    # Fill missing/unmapped players with 0.0
    df['D-LEBRON'] = df['D-LEBRON'].fillna(0.0)

    # Cut out low-minute players (< 500 minutes)
    if 'MP' in df.columns:
        original_count = len(df)
        df = df[df['MP'] >= 500].copy()
        print(f"✂️ Culled out {original_count - len(df)} players with < 500 minutes.")

    print("⚙️ Computing raw profile metrics...")
    df['raw_spacing'] = df.apply(compute_raw_spacing, axis=1)
    df['raw_rebounding'] = df.apply(compute_raw_rebounding, axis=1)
    df['raw_scoring'] = df.apply(compute_raw_scoring, axis=1)
    df['raw_playmaking'] = df.apply(compute_raw_playmaking, axis=1)

    # Pure Impact Defense from D-LEBRON
    df['raw_defense'] = df['D-LEBRON']

    # Independent flags
    blk_col = 'BLK_100' if 'BLK_100' in df.columns else 'BLK'
    df['rim_protector'] = df[blk_col] >= 2.0 if blk_col in df.columns else False

    shot_0_3 = df['0-3_shot'] if '0-3_shot' in df.columns else 0.0
    shot_3_10 = df['3-10_shot'] if '3-10_shot' in df.columns else 0.0
    df['inside_tendency'] = (shot_0_3 + shot_3_10) * 100.0

    print("📊 Standardizing scores to 0-100 scales...")

    standardized_columns = {}

    # Scale each pillar so the ANCHOR_RANK-th best player = 100.
    # Anchoring on the 10th best instead of #1 stops one outlier (e.g. Wembanyama on defense)
    # from squashing everyone else. Players above the anchor score over 100.
    for metric in ['scoring', 'spacing', 'playmaking', 'rebounding']:
        raw_col = f"raw_{metric}"
        anchor = df[raw_col].nlargest(ANCHOR_RANK).iloc[-1]
        standardized_columns[f"std_{metric}"] = (df[raw_col] / anchor) * 100.0 if anchor > 0 else 0.0

    # DEFENSE: D-LEBRON can be negative, so anchor both ends:
    # ANCHOR_RANK-th best = 100, ANCHOR_RANK-th worst = 0 (anything below is floored at 0)
    def_high = df['raw_defense'].nlargest(ANCHOR_RANK).iloc[-1]
    def_low = df['raw_defense'].nsmallest(ANCHOR_RANK).iloc[-1]
    if def_high > def_low:
        std_def = (df['raw_defense'] - def_low) / (def_high - def_low) * 100.0
        standardized_columns['std_defense'] = std_def.clip(lower=0.0)
    else:
        standardized_columns['std_defense'] = 50.0

    # Append standardized columns
    df = pd.concat([df, pd.DataFrame(standardized_columns, index=df.index)], axis=1)

    # Save final CSV
    metadata_candidates = ['name', 'position', 'Age', 'Team', 'Tm', 'tm', 'team', 'G', 'MP', 'VORP_adv', 'On-Off_pbp']
    existing_metadata = [col for col in metadata_candidates if col in df.columns]

    final_cols = existing_metadata + [
        'std_scoring', 'std_spacing', 'std_playmaking', 'std_rebounding', 'std_defense',
        'rim_protector', 'inside_tendency'
    ]

    final_df = df[final_cols].copy()
    numeric_cols = ['std_scoring', 'std_spacing', 'std_playmaking', 'std_rebounding', 'std_defense', 'inside_tendency']
    final_df[numeric_cols] = final_df[numeric_cols].round(1)

    final_df.to_csv(output_file, index=False)
    print(f"🎉 Standardized Profile Database ready in '{output_file}'!")


if __name__ == "__main__":
    process_and_standardize_profiles()