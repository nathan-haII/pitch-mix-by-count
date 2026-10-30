"""Pitch mix by count: a web app. Choose a team and pitcher, see what he throws ahead, even and behind.
Run locally:  streamlit run app.py
"""
import io

import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Pitch mix by count", layout="wide")

API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0"}
ORDER = ["First pitch (0-0)", "Ahead (pitcher)", "Even (1-1, 2-2)", "Behind (hitter ahead)"]
KEEP = ["pitch_name", "balls", "strikes", "stand", "release_speed"]
MIN_SHARE = 0.03      # pitch types under 3% of pitches are grouped as "Other"
MIN_PITCHES = 30      # warn when a count situation has fewer pitches than this


# ------------------------------------------------------------------ data ------
@st.cache_data(ttl=86400)
def get_teams(season):
    r = requests.get(f"{API}/teams", params={"sportId": 1, "season": season},
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {t["name"]: t["id"] for t in sorted(r.json()["teams"], key=lambda t: t["name"])}


@st.cache_data(ttl=86400)
def get_pitchers(team_id, season):
    r = requests.get(f"{API}/teams/{team_id}/roster",
                     params={"rosterType": "40Man", "season": season},
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {p["person"]["fullName"]: p["person"]["id"] for p in r.json()["roster"]
            if p["position"]["type"] in ("Pitcher", "Two-Way Player")}


@st.cache_data(ttl=3600, show_spinner="Downloading pitch data from Baseball Savant...")
def get_pitches(pitcher_id, season):
    url = ("https://baseballsavant.mlb.com/statcast_search/csv?all=true"
           f"&hfGT=R%7C&hfSea={season}%7C&player_type=pitcher"
           f"&pitchers_lookup%5B%5D={pitcher_id}&type=details")
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    if df.empty:
        return df
    cols = [c for c in KEEP if c in df.columns]
    return df[cols].copy()


def count_situation(balls, strikes):
    if balls == 0 and strikes == 0:
        return "First pitch (0-0)"
    if strikes > balls:
        return "Ahead (pitcher)"
    if balls == strikes:
        return "Even (1-1, 2-2)"
    return "Behind (hitter ahead)"


def clean(df):
    df = df.dropna(subset=["pitch_name", "balls", "strikes", "stand"]).copy()
    df = df[df["balls"].between(0, 3) & df["strikes"].between(0, 2)].copy()
    df["situation"] = [count_situation(b, s) for b, s in zip(df["balls"], df["strikes"])]
    shares = df["pitch_name"].value_counts(normalize=True)
    rare = shares[shares < MIN_SHARE].index
    df["pitch"] = df["pitch_name"].where(~df["pitch_name"].isin(rare), "Other")
    return df


def mix_table(data, pitches):
    counts = (pd.crosstab(data["situation"], data["pitch"])
              .reindex(index=ORDER, columns=pitches).fillna(0))
    n = counts.sum(axis=1).astype(int)
    pct = counts.div(counts.sum(axis=1).replace(0, 1), axis=0) * 100
    return pct.round(1), n


def draw(ax, table, n, colors, title):
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


# ------------------------------------------------------------------- UI -------
st.title("Pitch mix by count")
st.caption("What does a pitcher throw when he is ahead, even, or behind in the count? "
           "Data: Baseball Savant (Statcast) and the MLB Stats API.")

season = st.sidebar.selectbox("Season", list(range(2026, 2015, -1)))
try:
    teams = get_teams(season)
except Exception as e:
    st.error(f"Could not load teams from the MLB Stats API: {e}")
    st.stop()

team_names = list(teams)
default_team = team_names.index("Toronto Blue Jays") if "Toronto Blue Jays" in team_names else 0
team = st.sidebar.selectbox("Team", team_names, index=default_team)

try:
    pitchers = get_pitchers(teams[team], season)
except Exception as e:
    st.error(f"Could not load the roster: {e}")
    st.stop()

pitcher_id, pitcher_name = None, None
if pitchers:
    pitcher_name = st.sidebar.selectbox("Pitcher", sorted(pitchers))
    pitcher_id = pitchers[pitcher_name]
else:
    st.sidebar.write("No pitchers found on this roster.")

with st.sidebar.expander("Pitcher not listed? Use a Savant ID"):
    manual = st.text_input("MLBAM ID (number at the end of the pitcher's Savant URL)")
    if manual.strip().isdigit():
        pitcher_id, pitcher_name = int(manual), f"Pitcher {manual.strip()}"

if pitcher_id is None:
    st.info("Choose a team and pitcher in the sidebar.")
    st.stop()

try:
    raw = get_pitches(pitcher_id, season)
except Exception as e:
    st.error(f"Could not download pitch data: {e}")
    st.stop()

missing = [c for c in ("pitch_name", "balls", "strikes", "stand") if c not in raw.columns]
if raw.empty or missing:
    st.warning(f"No pitch data found for {pitcher_name} in {season}. "
               "He may not have pitched in the majors that season.")
    st.stop()

df = clean(raw)
pitches = sorted(df["pitch"].unique())
colors = {p: plt.cm.tab10(i % 10) for i, p in enumerate(pitches)}
overall, n_overall = mix_table(df, pitches)

st.subheader(f"{pitcher_name}, {season}")
c1, c2, c3 = st.columns(3)
c1.metric("Pitches", f"{len(df):,}")
c2.metric("Pitch types", len(pitches))
c3.metric("Smallest count situation", f"{int(n_overall.min())} pitches")
if (n_overall < MIN_PITCHES).any():
    st.warning(f"Small sample: fewer than {MIN_PITCHES} pitches in "
               f"{', '.join(n_overall[n_overall < MIN_PITCHES].index)}. Read those bars with caution.")

tab1, tab2, tab3 = st.tabs(["By count", "By batter side", "Pitch summary"])

with tab1:
    fig, ax = plt.subplots(figsize=(9, 5))
    draw(ax, overall, n_overall, colors, f"{pitcher_name}: pitch mix by count")
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    st.pyplot(fig)
    st.dataframe(overall.assign(pitches=n_overall))

with tab2:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (side, label) in zip(axes, (("L", "vs left-handed hitters"),
                                        ("R", "vs right-handed hitters"))):
        sub = df[df["stand"] == side]
        if sub.empty:
            ax.set_title(f"{label}: no data")
            continue
        table, n = mix_table(sub, pitches)
        draw(ax, table, n, colors, label)
    axes[1].legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    st.pyplot(fig)

with tab3:
    summary = df.groupby("pitch").agg(pitches=("pitch", "size"))
    summary["usage_%"] = (summary["pitches"] / len(df) * 100).round(1)
    if "release_speed" in df.columns:
        summary["avg_velocity_mph"] = df.groupby("pitch")["release_speed"].mean().round(1)
    st.dataframe(summary.sort_values("pitches", ascending=False))

with st.expander("How to read this, and limits"):
    st.markdown(
        "- Counts are grouped: **first pitch** (0-0), **ahead** (more strikes than balls), "
        "**even** (1-1, 2-2) and **behind** (more balls than strikes).\n"
        "- Pitch types used under 3% of the time are grouped as \"Other\".\n"
        "- One pitcher and one season can be a small sample; check the n= labels.\n"
        "- Pitch choice also depends on the hitter, score, inning and pitcher health, "
        "which this does not account for.")