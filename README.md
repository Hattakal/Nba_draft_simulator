# Nba_draft_simulator
NBA draft simulation, vibe code, WIP

## Running the app

```
pip install -r requirements.txt
python webapp.py
```

Then open http://localhost:5000

## Updating to a new season

The data is built in three steps. Each script reads the previous step's output.

1. **Scrape Basketball Reference** - `python fdraft.py`
   Downloads per-100, advanced, play-by-play and shooting stats and writes `nba_ultimate_stats_<season>.csv`.
   Change `season = 2026` at the top of `build_ultimate_2026_database()` first.
   If you hit a 429 rate-limit error, wait a few minutes and run it again.

2. **Get the LEBRON defense data** - save it as `lebron-data-<season>.csv`.
   It needs at least `Player` and `D-LEBRON` columns.

3. **Build player profiles** - `python stat_standardizer.py`
   Merges the two files and writes `nba_standardized_profiles_<season>.csv`, which the web app loads.
   It prints any qualified players whose names didn't match the LEBRON file. Add those to
   `NAME_ALIASES` in `stat_standardizer.py` (e.g. `'ron holland': 'ronald holland'`).

When changing seasons, also update the file names in `stat_standardizer.py` and `webapp.py`.

## Tuning

- `SYNERGY_WEIGHT` in `webapp.py`: how much roster fit counts in the standings vs. total talent.
- `DRAFT_RANDOMNESS` in `draft_engine.py`: how much AI drafts vary (0 = identical every time).
- `ROSTER_SLOTS` in `draft_engine.py`: required players per position (default 2 G, 2 F, 1 C).
- `GREAT` / `GOOD` / `LOW_SPACER` etc. in `draft_engine.py`: thresholds for synergy rules and player tags.
- `ON_OFF_CAP` in `draft_engine.py`: the most on/off can raise or lower a player's score (0.20 = +/-20%).
- `ANCHOR_RANK` in `stat_standardizer.py`: the Nth best player in each pillar is scaled to 100 (default 10th),
  so one outlier doesn't squash everyone else. Re-run `stat_standardizer.py` after changing it.
- `nba_teams.py`: team names and abbreviations.
- `POSITION_WEIGHTS` in `draft_engine.py`: how much each pillar counts by position (the web page reads these too).
- Position weights, minutes penalty and on/off multiplier: `calculate_overall_rank()` in `draft_engine.py`.
- Synergy rules and thresholds: `calculate_roster_synergy()` in `draft_engine.py`.
