import pandas as pd
import requests
from io import StringIO
import time


def scrape_bref_table(url, table_id=None):
    """Downloads a webpage and extracts a specific table. Can filter by HTML ID if provided."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 429:
            print("🛑 Hit a 429 Rate Limit! Wait 2-3 minutes before running the script again.")
            return None
        response.encoding = 'utf-8'

        all_tables = pd.read_html(StringIO(response.text), flavor='html5lib')

        # If looking for a specific table ID (like 'all_defense' or 'advanced_stats')
        if table_id:
            # Simple check if there are tables parsed
            if all_tables:
                # BRef tables usually match the order or have distinct shapes.
                # We will return the first substantial table as fallback.
                return all_tables[0]

        return all_tables[0] if all_tables else None
    except Exception as e:
        print(f"Error scraping {url}: {e}")
    return None


def clean_and_normalize_df(df, suffix="", is_primary=False):
    """
    Removes multi-index headers, repeated rows, and handles metadata columns.
    If it's the primary table, we keep the demographic info.
    If it's a secondary table, we drop them to prevent duplicate column clashes.
    """
    if df is None:
        return None

    # 1. Flatten MultiIndex headers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[-1] if not col[-1].startswith('Unnamed') else col[0] for col in df.columns]

    # 2. Drop rows that repeat column names
    if 'Player' in df.columns:
        df = df[df['Player'] != 'Player']

    # 3. Keep the first instance (keeps 'TOT' for traded players)
    df = df.drop_duplicates(subset=['Player'], keep='first')

    # 4. Handle clashing metadata columns
    metadata_cols = ['Age', 'Tm', 'G', 'MP', 'Pos']

    if not is_primary:
        # For supplementary tables, drop these columns entirely so they don't clash
        cols_to_drop = [col for col in metadata_cols if col in df.columns]
        df = df.drop(columns=cols_to_drop)

    # 5. Add a suffix to the unique statistical columns to prevent name overlap
    rename_dict = {}
    for col in df.columns:
        if col != 'Player':
            # Only apply suffix if the column doesn't already have one
            if not col.endswith(suffix) and col not in metadata_cols:
                rename_dict[col] = f"{col}{suffix}"

    df = df.rename(columns=rename_dict)
    return df


def build_ultimate_2026_database():
    season = 2026
    print(f"🚀 Building Ultimate Player Database for the {season} season...\n")

    # Base URL configurations
    sources = {
        "per_poss": {
            "url": f"https://www.basketball-reference.com/leagues/NBA_{season}_per_poss.html",
            "suffix": "_100"
        },
        "advanced": {
            "url": f"https://www.basketball-reference.com/leagues/NBA_{season}_advanced.html",
            "suffix": "_adv"
        },
        "play_by_play": {
            "url": f"https://www.basketball-reference.com/leagues/NBA_{season}_play-by-play.html",
            "suffix": "_pbp"
        },
        "shooting": {
            "url": f"https://www.basketball-reference.com/leagues/NBA_{season}_shooting.html",
            "suffix": "_shot"
        }
    }

    master_df = None

    # 1. Scrape and merge all main stats tables
    for key, info in sources.items():
        print(f"📥 Gathering all columns from: {key}...")
        raw_table = scrape_bref_table(info['url'])

        # The first table (per_poss) acts as our primary database skeleton
        is_primary = (master_df is None)
        df = clean_and_normalize_df(raw_table, suffix=info['suffix'], is_primary=is_primary)

        if df is not None:
            if master_df is None:
                master_df = df
            else:
                # Merge cleanly on Player without any clashing metadata columns!
                master_df = pd.merge(master_df, df, on='Player', how='left')
        else:
            print(f"⚠️ Warning: Could not retrieve {key}")

        time.sleep(4)  # Polite pause to avoid rate limits

    # 2. Grab Defensive Voting Shares from the Awards Page
    print("\n🎖️ Scraping Award Voting Shares for Defense...")
    awards_url = f"https://www.basketball-reference.com/awards/awards_{season}.html"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # We initialize dpoy_df as None outside the try block so it is always accessible safely
    dpoy_df = None
    try:
        response = requests.get(awards_url, headers=headers)
        if response.status_code == 200:
            # Parse all award tables on this page.
            # Match specifically on "All-Defensive Teams" to target the right table.
            award_tables = pd.read_html(StringIO(response.text), flavor='html5lib', match="All-Defensive Teams")

            if award_tables:
                table = award_tables[0]

                # Drop multiheaders if present
                if isinstance(table.columns, pd.MultiIndex):
                    table.columns = [col[-1] for col in table.columns]

                # Identify All-Defensive Table and extract Player and Share
                if 'Share' in table.columns and 'Player' in table.columns:
                    dpoy_df = table[['Player', 'Share']].copy()
                    dpoy_df = dpoy_df.rename(columns={'Share': 'def_vote_share'})
                    print("✅ Found the All-Defensive Teams voting table!")
                else:
                    print("⚠️ Found table, but columns 'Player' or 'Share' were missing.")
            else:
                print("⚠️ Could not locate the 'All-Defensive Teams' table on the page.")
        else:
            print(f"⚠️ Could not access awards page. HTTP {response.status_code}")
    except Exception as e:
        print(f"⚠️ Error parsing awards voting: {e}")

    # Merge the All-Defensive df if we found it
    if dpoy_df is not None and master_df is not None:
        # --- THE MERGE CLASH GUARD ---
        # If 'def_vote_share' already exists in master_df, drop it before merging
        if 'def_vote_share' in master_df.columns:
            master_df = master_df.drop(columns=['def_vote_share'])
        # -----------------------------

        print("✅ Merging All-Defensive shares into master database...")
        master_df = pd.merge(master_df, dpoy_df, on='Player', how='left')
    else:
        print("⚠️ Skipping All-Defensive merge (data unavailable or primary scrape failed).")

    # 3. FORCE FILE GENERATION & CLEANING (No nesting!)
    print("\n🧹 Initiating final cleaning sequence...")

    # Safeguard if master_df is empty
    if master_df is None or master_df.empty:
        print("❌ Master database assembly failed: master_df is completely empty!")
        return

    # Drop any duplicate columns that snuck through the merges
    master_df = master_df.loc[:, ~master_df.columns.duplicated()]

    # Fill completely missing NaN values with '0' before converting types
    master_df = master_df.fillna(0)

    # Safely convert all columns to numeric except name, position, and team
    non_numeric = ['Player', 'Pos', 'Tm']
    for col in master_df.columns:
        if col not in non_numeric:
            column_series = master_df[col]
            if isinstance(column_series, pd.DataFrame):
                column_series = column_series.iloc[:, 0]

            master_df[col] = pd.to_numeric(column_series, errors='coerce').fillna(0)

    # Clean up general details
    if 'Pos' in master_df.columns:
        master_df['Pos'] = master_df['Pos'].apply(lambda x: str(x).split('-')[0].upper())

    master_df = master_df.rename(columns={'Player': 'name', 'Pos': 'position'})

    # PHYSICAL FILE WRITE OUT
    output_filename = f"nba_ultimate_stats_{season}.csv"
    master_df.to_csv(output_filename, index=False)

    print(f"\n🎉 Ultimate Database successfully built and saved to '{output_filename}'!")
    print(f"Merged {len(master_df.columns)} statistics for {len(master_df)} active players.")


if __name__ == "__main__":
    build_ultimate_2026_database()