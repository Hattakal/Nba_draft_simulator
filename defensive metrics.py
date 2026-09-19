import pandas as pd

# Load main dataset and external defensive stats
df_main = pd.read_csv("nba_ultimate_stats_2026.csv")
df_depm = pd.read_csv("depm_2026.csv")        # Columns: ['name', 'D-EPM']
df_lebron = pd.read_csv("d_lebron_2026.csv")  # Columns: ['name', 'D-LEBRON']

# Clean merge on player name
df_main = df_main.merge(df_depm[['name', 'D-EPM']], on='name', how='left')
df_main = df_main.merge(df_lebron[['name', 'D-LEBRON']], on='name', how='left')

# Fill missing values for edge players with league average (0.0)
df_main['D-EPM'] = df_main['D-EPM'].fillna(0.0)
df_main['D-LEBRON'] = df_main['D-LEBRON'].fillna(0.0)