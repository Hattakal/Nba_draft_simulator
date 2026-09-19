import pandas as pd
import requests
from io import StringIO

# 1. Ensure you save your .py script file with UTF-8 encoding!
# Most modern editors (VS Code, PyCharm) do this automatically.
MANUAL_COPIED_HTML = """<table><tbody>

<tr class="thead"><th class="right " data-stat="ranker" >Rk</th><th class="left " data-stat="name_display" >Player</th> ...
... PASTE ALL OF YOUR COPIED TR ROWS HERE ...
<tr class="full_table" ><td class="right " data-stat="ranker" >51</td><td class="left " data-stat="name_display" csk="Okeke,Chuma" ><a href="/players/o/okekech01.html">Chuma Okeke</a></td> ...

</tbody></table>"""


def get_live_vorp_data(season_year=2026):
    """
    Downloads the Advanced Player Stats page from Basketball Reference.
    If rate-limited or offline, falls back to using the manually pasted HTML.
    Handles non-standard letters (like ş, ç, ğ, ö, ı, ü) seamlessly.
    """
    url = f"https://www.basketball-reference.com/leagues/NBA_{season_year}_advanced.html"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"Connecting to Basketball Reference for the {season_year} season...")
    use_manual_fallback = False
    downloaded_html_content = ""

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 429:
            print("Error 429: We've been rate-limited by Basketball Reference!")
            use_manual_fallback = True
        elif response.status_code != 200:
            print(f"Could not fetch data. HTTP Error: {response.status_code}")
            use_manual_fallback = True
        else:
            # FORCE the response decoding to UTF-8 to handle regional characters cleanly
            response.encoding = 'utf-8'
            downloaded_html_content = response.text
    except requests.exceptions.RequestException as e:
        print(f"Network error occurred: {e}")
        use_manual_fallback = True

    # ---- PARSING LOGIC ----
    if use_manual_fallback:
        print("Using your manually pasted HTML fallback data instead...")
        # Wrap the manual string in StringIO to stream it as a file
        html_to_parse = StringIO(MANUAL_COPIED_HTML)
    else:
        print("Webpage downloaded successfully! Now processing data...")
        html_to_parse = StringIO(downloaded_html_content)

    try:
        # Use html5lib to correctly interpret special symbols from the stream
        all_tables = pd.read_html(html_to_parse, flavor='html5lib')
    except ValueError as e:
        print(f"Pandas failed to locate any tables: {e}")
        return None
    except Exception as e:
        print(f"An unexpected parsing error occurred: {e}")
        return None

    df = all_tables[0]

    # Clean up multi-index headers if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(0)

    # Drop rows that repeat the table headers
    df = df[df['Player'] != 'Player']

    # Filter and copy only the columns we want
    df = df[['Player', 'Pos', 'VORP']].copy()
    df.columns = ['name', 'position', 'vorp']

    # Safely convert VORP to numeric, turning missing values into NaN
    df['vorp'] = pd.to_numeric(df['vorp'], errors='coerce')

    # Remove duplicate rows (keeps the first occurrence, which is 'TOT' for traded players)
    df = df.drop_duplicates(subset=['name'], keep='first')

    # Clean up position strings (e.g. "SG-PG" -> "SG")
    df['position'] = df['position'].apply(lambda x: str(x).split('-')[0].upper() if pd.notna(x) else 'N/A')

    # Sort by VORP
    df = df.sort_values(by='vorp', ascending=False).reset_index(drop=True)

    return df


if __name__ == "__main__":
    player_pool = get_live_vorp_data(2026)

    if player_pool is not None:
        # Save to a CSV file so we don't have to scrape again!
        player_pool.to_csv("nba_players_2026.csv", index=False)
        print("Success! Saved 2026 player pool to 'nba_players_2026.csv'.")