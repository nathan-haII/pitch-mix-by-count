"""Pitch mix by count: what does a pitcher throw when he is ahead, even, or behind?

get the pitcher's Statcast data, group counts into four situations, and
chart how often each pitch type is used in each one (overall, and against lefty vs righty hitters).
"""
import io
import os
import sys

import matplotlib.pyplot as plt
import pandas as pd

try:
    import requests
except ImportError:
    sys.exit("Missing package. Run: pip install requests")

# ---------------------------------------------------------------- settings ----
PITCHER_ID = 660271      # the number at the end of the pitcher's Baseball Savant page URL
SEASON = 2026
CSV_PATH = "data/pitcher.csv"
MIN_SHARE = 0.03       # pitch types used less than 3% of the time are grouped as "Other"
MIN_PITCHES = 30       # warn when a count situation has fewer pitches than this
# ---------------------------------------------------------------------------------

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # always work from this folder
os.makedirs("data", exist_ok=True)
os.makedirs("figures", exist_ok=True)

MANUAL_HELP = (
    "\nManual option: on baseballsavant.mlb.com open Statcast Search, choose Player Type = Pitcher,"
    "\npick the pitcher and season, click 'Download CSV', and save the file as data/pitcher.csv."
)


def load_data():
    """Use data/pitcher.csv if it exists; otherwise try to download it from Baseball Savant."""
    if not os.path.exists(CSV_PATH):
        if PITCHER_ID is None:
            sys.exit("Set PITCHER_ID at the top of pitch_mix.py (or save a Savant CSV as "
                     "data/pitcher.csv)." + MANUAL_HELP)
        url = ("https://baseballsavant.mlb.com/statcast_search/csv?all=true"
               f"&hfGT=R%7C&hfSea={SEASON}%7C&player_type=pitcher"
               f"&pitchers_lookup%5B%5D={PITCHER_ID}&type=details")
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            if df.empty:
                raise ValueError("no pitches returned (check PITCHER_ID and SEASON)")
            df.to_csv(CSV_PATH, index=False)
            print(f"Downloaded {len(df)} pitches")
        except Exception as e:
            sys.exit(f"Download failed: {e}" + MANUAL_HELP)
    return pd.read_csv(CSV_PATH)


def count_situation(balls, strikes):
    """Group the 12 possible counts into four situations."""
    if balls == 0 and strikes == 0:
        return "First pitch (0-0)"
    if strikes > balls:
        return "Ahead (pitcher)"
    if balls == strikes:
        return "Even (1-1, 2-2)"
    return "Behind (hitter ahead)"


ORDER = ["First pitch (0-0)", "Ahead (pitcher)", "Even (1-1, 2-2)", "Behind (hitter ahead)"]

# ---------------------------------------------------------------- clean data ----
df = load_data()
needed = ["pitch_name", "balls", "strikes", "stand", "player_name"]
missing = [c for c in needed if c not in df.columns]
if missing:
    sys.exit(f"The CSV is missing columns: {missing}\nColumns found: {list(df.columns)}")

df = df.dropna(subset=["pitch_name", "balls", "strikes", "stand"])
df = df[df["balls"].between(0, 3) & df["strikes"].between(0, 2)]
df["situation"] = [count_situation(b, s) for b, s in zip(df["balls"], df["strikes"])]

shares = df["pitch_name"].value_counts(normalize=True)
rare = shares[shares < MIN_SHARE].index
df["pitch"] = df["pitch_name"].where(~df["pitch_name"].isin(rare), "Other")

pitcher = df["player_name"].mode().iloc[0]
print(f"{pitcher}: {len(df)} pitches")

# -------------------------------------------------------------------- tables ----
def mix_table(data):
    counts = pd.crosstab(data["situation"], data["pitch"]).reindex(ORDER).fillna(0)
    return (counts.div(counts.sum(axis=1), axis=0) * 100).round(1), counts.sum(axis=1).astype(int)


overall, n_overall = mix_table(df)
overall.assign(pitches=n_overall).to_csv("data/pitch_mix_overall.csv")
print("\nPitch mix (%) by count situation:")
print(overall.assign(pitches=n_overall).to_string())
small = n_overall[n_overall < MIN_PITCHES]
if len(small):
    print(f"\nWarning: fewer than {MIN_PITCHES} pitches in: {', '.join(small.index)}")

# -------------------------------------------------------------------- charts ----
pitches = sorted(df["pitch"].unique())
colors = {p: plt.cm.tab10(i % 10) for i, p in enumerate(pitches)}


def draw(ax, table, n, title):
    bottom = pd.Series(0.0, index=table.index)
    for p in table.columns:
        ax.bar(table.index, table[p], bottom=bottom, label=p, color=colors[p])
        bottom += table[p]
    for i, name in enumerate(table.index):
        ax.text(i, 101, f"n={n[name]}", ha="center", fontsize=8)
    ax.set_title(title, pad=18)
    ax.set_ylim(0, 108)
    ax.set_ylabel("% of pitches")
    ax.tick_params(axis="x", labelrotation=20)


fig, ax = plt.subplots(figsize=(9, 5))
draw(ax, overall, n_overall, f"{pitcher}: pitch mix by count, {SEASON}")
ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
fig.tight_layout()
fig.savefig("figures/pitch_mix_by_count.png", dpi=150)

fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
for ax, (side, label) in zip(axes, (("L", "vs left-handed hitters"), ("R", "vs right-handed hitters"))):
    sub = df[df["stand"] == side]
    if sub.empty:
        ax.set_title(f"{label}: no data")
        continue
    table, n = mix_table(sub)
    table = table.reindex(columns=pitches).fillna(0)
    draw(ax, table, n, label)
axes[1].legend(bbox_to_anchor=(1.02, 1), loc="upper left")
fig.suptitle(f"{pitcher}: pitch mix by count and batter side, {SEASON}")
fig.tight_layout()
fig.savefig("figures/pitch_mix_by_hand.png", dpi=150)
print("\nSaved figures/pitch_mix_by_count.png and figures/pitch_mix_by_hand.png")