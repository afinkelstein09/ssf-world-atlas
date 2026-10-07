"""
Fetch small-scale fisheries data for every EEZ in the world from Sea Around Us.

Sea Around Us (University of British Columbia) is the only global source that splits
catch into artisanal / subsistence / industrial / recreational sectors. We use that
split to compute each country's small-scale share of catch.

Outputs two files into data/processed/:
  eez.geojson    - EEZ polygons, each with SSF stats baked into its properties
  countries.json - the same stats without geometry, for the side panel

Data source: https://api.seaaroundus.org/api/v1/
Citation policy: https://www.seaaroundus.org/citation-policy/
"""

import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import countries as iso_lookup

API = "https://api.seaaroundus.org/api/v1"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw")

# Write straight into the site folder. Everything the deployed page needs has to
# live under site/, because that's the only directory that gets published - data
# kept outside it would silently 404 in production.
OUT = os.path.join(HERE, "site", "data")

# Sea Around Us calls these "small-scale" sectors. Recreational is deliberately
# excluded - it's a different kind of fishing and lumping it in would inflate
# the numbers we're trying to report honestly.
SSF_SECTORS = ("Artisanal", "Subsistence")

# Rare's Fish Forever countries, for highlighting on the map.
#
# Listed as exact Sea Around Us EEZ names rather than matching on country name.
# Substring matching wrongly flagged outlying territories - Fernando de Noronha,
# the French islands in the Mozambique Channel - as Rare sites. Fish Forever
# works in coastal communities, not on uninhabited offshore rocks.
FISH_FOREVER = {
    "Philippines",
    "Indonesia (Central)", "Indonesia (Eastern)", "Indonesia (Indian Ocean)",
    "Mozambique",
    "Brazil (mainland)",
    "Honduras (Caribbean)", "Honduras (Pacific)",
    "Guatemala (Caribbean)", "Guatemala (Pacific)",
    "Palau",
    "Micronesia (Federated States of)",
}


def get_json(url, tries=3):
    """Fetch JSON with retries. Returns None if the endpoint keeps failing."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch_eez_list():
    """Get all EEZ polygons. One call returns geometry + region_id + name."""
    path = os.path.join(RAW, "eez.json")
    if os.path.exists(path):
        print("  using cached EEZ polygons")
        with open(path) as f:
            return json.load(f)["data"]["features"]

    print("  downloading EEZ polygons...")
    data = get_json(f"{API}/eez/")
    if not data:
        raise SystemExit("Could not reach Sea Around Us. Check your connection.")
    with open(path, "w") as f:
        json.dump(data, f)
    return data["data"]["features"]


def summarise(series_list, recent_years=5):
    """
    Turn raw [year, tonnes] series into the numbers the map needs.

    Averages the most recent years rather than using a single year, because
    one bad year can swing a small country's share by a lot. Nulls in the
    Sea Around Us data are treated as missing, not zero - that distinction
    is the whole point of the confidence layer.
    """
    by_sector = {}
    years_seen = set()
    nulls = 0
    # Years where a sector that was reporting goes null. A null is a gap in the
    # record, not a zero catch, and a history point built from the sectors that
    # remain is wrong in the worst way - Ascension's sparkline ended on
    # "2019 · 100%" because industrial was null that year and artisanal was
    # not, against a five-year share of 5%. A null counts as a gap when it sits
    # inside a series (values before and after it - Musandam's industrial
    # series is null 1986-2004 and then resumes) or within five years after
    # the series' last value. A series that has not started yet (recreational
    # in the 1950s) or stopped long ago (Belgium's artisanal series, last
    # value 1960) is a known absence, and those years stay so the chart keeps
    # what it honestly can.
    null_years = set()
    last_value = {}  # sector -> last year with a value, for the "since" wording

    for s in series_list:
        key = s.get("key")
        vals = s.get("values") or []
        clean = {}
        sector_nulls = set()
        for pair in vals:
            if not pair or len(pair) < 2:
                continue
            yr, tonnes = pair[0], pair[1]
            if tonnes is None:
                nulls += 1
                sector_nulls.add(int(yr))
                continue
            clean[int(yr)] = float(tonnes)
            years_seen.add(int(yr))
        if clean:
            by_sector[key] = clean
            first, last = min(clean), max(clean)
            last_value[key] = last
            for y in sector_nulls:
                if first < y < last or (y > last and y - last <= 5):
                    null_years.add(y)

    if not by_sector or not years_seen:
        return None

    last_year = max(years_seen)
    window = [y for y in range(last_year - recent_years + 1, last_year + 1)]

    recent = {}
    unknown = []
    for sector, yearmap in by_sector.items():
        pts = [yearmap[y] for y in window if y in yearmap]
        # A sector with no reading in the window is unknown, not zero - Jamaica's
        # industrial series is null from 1991 - so it is left out rather than
        # drawn as a "0 t" bar. The share is then a share of the known catch,
        # the confidence score docks a point for the nulls, and the panel names
        # the sector so a 100% does not pass as a certainty.
        if pts:
            recent[sector] = sum(pts) / len(pts)
        else:
            unknown.append(sector)

    total = sum(recent.values())
    if total <= 0:
        return None

    ssf = sum(recent.get(s, 0.0) for s in SSF_SECTORS)

    # Full time series for the side-panel chart, as [year, ssf_share] pairs.
    history = []
    for y in sorted(years_seen - null_years):
        yr_total = sum(m.get(y, 0.0) for m in by_sector.values())
        if yr_total <= 0:
            continue
        yr_ssf = sum(by_sector.get(s, {}).get(y, 0.0) for s in SSF_SECTORS)
        history.append([y, round(100.0 * yr_ssf / yr_total, 1)])

    # Whole tonnes are fine for a fishery, but on a 25-tonne island rounding
    # each sector moves the bars a couple of points off the headline share.
    sector_dp = 0 if total >= 1000 else 1

    return {
        "ssf_share": round(100.0 * ssf / total, 1),
        "total_t": round(total),
        "sectors": {k: round(v, sector_dp) for k, v in sorted(recent.items())},
        "years": [min(years_seen), last_year],
        "history": history,
        "nulls": nulls,
        "unknown_sectors": sorted(unknown),
        # when each missing series last reported, so the panel can say
        # "no values since 1960" rather than implying a recent gap
        "unknown_since": {k: last_value[k] for k in sorted(unknown)},
    }


def confidence(stats):
    """
    A 1-4 data-confidence score, shown as its own map layer.

    This is our own heuristic, not a Sea Around Us product - it reflects how
    much of the record is actually present. Labelled as an estimate in the UI
    so nobody mistakes it for an official figure.
    """
    if not stats:
        return 0
    span = stats["years"][1] - stats["years"][0] + 1
    score = 4
    if stats["nulls"] > 0:
        score -= 1
    if span < 60:
        score -= 1
    if stats["total_t"] < 5000:
        score -= 1
    return max(1, score)


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    features = fetch_eez_list()
    print(f"  {len(features)} EEZs to fetch\n")

    sector_dir = os.path.join(RAW, "sector")
    os.makedirs(sector_dir, exist_ok=True)

    def fetch_one(feat):
        """Fetch one EEZ's sector series, caching the raw response to disk so
        re-runs are instant and we stay polite to the Sea Around Us API."""
        rid = feat["properties"]["region_id"]
        cache = os.path.join(sector_dir, f"{rid}.json")

        if os.path.exists(cache):
            with open(cache) as f:
                data = json.load(f)
        else:
            data = get_json(f"{API}/eez/tonnage/sector/?region_id={rid}")
            if data:
                with open(cache, "w") as f:
                    json.dump(data, f)

        stats = summarise(data.get("data", [])) if data else None
        return feat, stats

    results = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (feat, stats) in enumerate(pool.map(fetch_one, features), 1):
            results.append((feat, stats))
            if i % 25 == 0 or i == len(features):
                print(f"  {i}/{len(features)}  ({time.time() - started:.0f}s)")

    out_features = []
    countries = []
    missing = []

    for feat, stats in results:
        props = feat["properties"]
        name = props["title"]
        rid = props["region_id"]
        is_ff = name in FISH_FOREVER

        # ISO3 is the key every other dataset uses - without it the atlas can
        # only ever show catch. 'kind' records how the match was made so the site
        # can be honest when a territory is inheriting its parent's statistics.
        iso3, kind = iso_lookup.resolve(name)

        base = {
            "name": name,
            "region_id": rid,
            "fish_forever": is_ff,
            "iso3": iso3,
            "iso_kind": kind,
        }

        if stats:
            base.update({
                "ssf_share": stats["ssf_share"],
                "total_t": stats["total_t"],
                "confidence": confidence(stats),
                "years": stats["years"],
            })
        else:
            base.update({"ssf_share": None, "total_t": None, "confidence": 0})
            missing.append(name)

        out_features.append({
            "type": "Feature",
            "properties": base,
            "geometry": feat["geometry"],
        })

        detail = dict(base)
        if stats:
            detail["sectors"] = stats["sectors"]
            detail["history"] = stats["history"]
            detail["unknown_sectors"] = stats["unknown_sectors"]
            detail["unknown_since"] = stats["unknown_since"]
        countries.append(detail)

    geo = {"type": "FeatureCollection", "features": out_features}
    with open(os.path.join(OUT, "eez.geojson"), "w") as f:
        json.dump(geo, f)

    countries.sort(key=lambda c: c["name"])
    with open(os.path.join(OUT, "countries.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": "Sea Around Us (UBC), reconstructed catch by sector",
            "source_url": "https://www.seaaroundus.org",
            "count": len(countries),
            "missing": len(missing),
            "countries": countries,
        }, f, indent=1)

    have = [c for c in countries if c["ssf_share"] is not None]
    print(f"\n  wrote {len(out_features)} EEZs")
    print(f"  {len(have)} with catch data, {len(missing)} without")
    if have:
        avg = sum(c["ssf_share"] for c in have) / len(have)
        print(f"  mean small-scale share: {avg:.1f}%")
        top = sorted(have, key=lambda c: -c["ssf_share"])[:5]
        print("  most small-scale:")
        for c in top:
            print(f"    {c['name'][:28]:<28} {c['ssf_share']:5.1f}%")
    if missing:
        print(f"  no data: {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}")


if __name__ == "__main__":
    main()
