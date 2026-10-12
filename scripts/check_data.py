"""
Check the data files before a refresh is published.

Run by the weekly GitHub Action after the fetch scripts, and safe to run by hand:

    python3 scripts/check_data.py

It fails (exit 1) when a file the page reads is broken: not JSON, or missing
the parts the page draws from. A file that is merely old is a warning, not a
failure: the fetch scripts keep the last good file when a source does not
answer, and the page prints the date of what it shows, so an old file is
honest. A broken one would blank part of the map.
"""

import json
import os
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "site", "data")

# How old a live file may get before the run warns about it, in days.
STALE = {"climate.json": 10, "news.json": 10, "outlook.json": 40,
         "outlook.json enso_odds": 40, "outlook.json enso_strength": 40, "outlook.json mhw_forecast": 40}

problems, warnings = [], []


def load(name, required=True):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        if required:
            problems.append(f"{name}: missing")
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except ValueError as e:
        problems.append(f"{name}: not valid JSON ({e})")
        return None


def age(name, d):
    stamp = (d or {}).get("generated")
    try:
        days = (date.today() - datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()).days
    except ValueError:
        warnings.append(f"{name}: no readable 'generated' date")
        return
    print(f"  {name:<32} generated {stamp}  ({days} days ago)")
    if days > STALE.get(name, 10_000):
        warnings.append(f"{name}: {days} days old; its source may not have answered")


def main():
    # every file must at least parse
    for name in sorted(os.listdir(DATA)):
        if name.endswith((".json", ".geojson")):
            load(name, required=False)

    climate = load("climate.json")
    if climate:
        age("climate.json", climate)
        e = climate.get("enso") or {}
        if not e.get("state") or e.get("oni") is None:
            problems.append("climate.json: the El Nino reading is missing")
        zones = climate.get("zones") or {}
        read = sum(1 for z in zones.values() if z and z.get("mhw") is not None)
        if len(zones) < 250 or read < 200:
            problems.append(f"climate.json: only {len(zones)} zones, {read} with a heatwave reading")

    news = load("news.json")
    if news:
        age("news.json", news)
        if len(news.get("countries") or {}) < 50:
            problems.append(f"news.json: headlines for only {len(news.get('countries') or {})} countries")

    outlook = load("outlook.json", required=False)
    if outlook:
        age("outlook.json", outlook)
        # The file's date moves even when a part is carried over from an earlier run,
        # so each part's own fetch date is checked too.
        for part in ("enso_odds", "enso_strength", "mhw_forecast"):
            fetched = (outlook.get(part) or {}).get("fetched")
            if fetched:
                age(f"outlook.json {part}", {"generated": fetched})
        fc = (outlook.get("mhw_forecast") or {}).get("zones") or {}
        if fc and len(fc) < 200:
            problems.append(f"outlook.json: heatwave forecast for only {len(fc)} zones")

    for w in warnings:
        # GitHub shows lines in this form as warnings on the run's page
        print(f"::warning::{w}")
    for p in problems:
        print(f"::error::{p}")
    if problems:
        return 1
    print("  all files read correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
