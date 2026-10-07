"""
Build the foreign fishing layer: whose fleets take the catch from each country's water?

Sea Around Us publishes catch by *fishing entity* - the nationality of the fleet
doing the fishing - as a dimension separate from sector. Crossed with the EEZ,
that answers a question no other layer here does: of everything landed from this
country's waters, how much leaves with someone else's fleet?

This is the layer a fisheries ministry acts on. Guinea-Bissau reconstructs at
1.1 million tonnes against 40,071 tonnes reported to FAO, and the gap is not
under-reporting: 97% of the catch in its EEZ is taken by foreign fleets, led by
Senegal, China, Spain and Russia. Its own vessels account for 3%.

Outputs site/data/fleets.json.

Source: Sea Around Us, https://api.seaaroundus.org/api/v1/eez/tonnage/country/
Cite: Pauly, D., Zeller, D. & Palomares, M.L.D. (Eds.) 2020. Sea Around Us
Concepts, Design and Data (seaaroundus.org). Their citation policy also asks that
country-level extractions cite that country's catch reconstruction report.
"""

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "fleets")
OUT = os.path.join(HERE, "site", "data")
API = "https://api.seaaroundus.org/api/v1/eez/tonnage/country/"

# Average the most recent years rather than trusting one. A single season can
# swing a small EEZ badly, and access agreements are multi-year arrangements.
WINDOW = 5


def get_json(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def fetch_one(feat):
    """One EEZ's catch split by the nationality of the fleet, cached to disk."""
    rid = feat["region_id"]
    cache = os.path.join(RAW, f"{rid}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return feat, json.load(f)
    data = get_json(f"{API}?region_id={rid}")
    if data:
        os.makedirs(RAW, exist_ok=True)
        with open(cache, "w") as f:
            json.dump(data, f)
    return feat, data


def summarise(series, zone_name):
    """
    Mean tonnage per fleet over the last WINDOW years of record.

    Returns None when the zone has no usable series - some EEZs report nothing
    for the recent window even though they have a long history.
    """
    per_fleet, years = {}, set()
    for s in series or []:
        key = s.get("key")
        clean = {}
        for pair in (s.get("values") or []):
            if not pair or len(pair) < 2 or pair[1] is None:
                continue
            clean[int(pair[0])] = float(pair[1])
            years.add(int(pair[0]))
        if clean:
            per_fleet[key] = clean
    if not per_fleet or not years:
        return None

    last = max(years)
    window = range(last - WINDOW + 1, last + 1)
    recent = {}
    for fleet, by_year in per_fleet.items():
        # A fleet absent from a year caught nothing that year, so the mean is
        # over the whole window, not over the years the fleet happens to appear
        # in. Averaging only the present years weighted a fleet that fished once
        # in five years as if it fished every year - Northern Marianas read as
        # 91% foreign-fished against a true 68%, and the fleet total no longer
        # matched the catch total the sector script computes from the same
        # window. With a fixed denominator the two agree in 274 of 282 zones;
        # the eight that differ have a sector series that is null inside the
        # window, which the sector script treats as unknown rather than zero.
        if any(y in by_year for y in window):
            recent[fleet] = sum(by_year.get(y, 0.0) for y in window) / WINDOW

    total = sum(recent.values())
    if total <= 0:
        return None
    return recent, total, last


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "countries.json")) as f:
        zones = json.load(f)["countries"]

    print(f"Fleet nationality for {len(zones)} EEZs")
    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (feat, data) in enumerate(pool.map(fetch_one, zones), 1):
            results.append((feat, data))
            if i % 40 == 0 or i == len(zones):
                print(f"  {i}/{len(zones)}  ({time.time() - started:.0f}s)")

    out = {}
    no_data = []
    for feat, data in results:
        name = feat["name"]
        summ = summarise((data or {}).get("data"), name)
        if not summ:
            no_data.append(name)
            continue
        recent, total, last_year = summ

        # Which fleet is the domestic one. Sea Around Us names fishing entities in
        # its own style, so the zone's own resolver is reused rather than matching
        # strings - "Guinea-Bissau" the fleet and "Guinea-Bissau" the EEZ have to
        # end up as the same ISO3 or the domestic share silently reads as zero.
        zone_iso = feat.get("iso3")
        domestic = 0.0
        unknown = 0.0
        fleets = []
        for fleet, tonnes in recent.items():
            share = 100.0 * tonnes / total
            # Sea Around Us attributes some catch to no fleet at all. Counting that
            # as foreign would overstate the case - in Micronesia it is the largest
            # single category - so it is held separately and reported as its own
            # number rather than folded into either side.
            if str(fleet).strip().lower().startswith("unknown"):
                unknown += tonnes
                continue
            f_iso, _ = iso_lookup.resolve(fleet)
            if f_iso and zone_iso and f_iso == zone_iso:
                domestic += tonnes
            elif share >= 0.5:  # below this the list becomes unreadable noise
                fleets.append({"fleet": fleet, "iso3": f_iso,
                               "t": round(tonnes), "pct": round(share, 1), "_t": tonnes})

        # Sort on the unrounded tonnage: two fleets at "4 t" otherwise keep
        # dictionary order and can print 0.6% above 0.7%.
        fleets.sort(key=lambda f: -f["_t"])
        for f in fleets:
            del f["_t"]
        foreign = max(0.0, total - domestic - unknown)  # never -0.0 from rounding
        foreign_pct = round(100.0 * foreign / total, 1)

        out[name] = {
            "iso3": zone_iso,
            "total_t": round(total),
            "domestic_t": round(domestic),
            "domestic_pct": round(100.0 * domestic / total, 1),
            "foreign_pct": foreign_pct,
            "unknown_t": round(unknown),
            "unknown_pct": round(100.0 * unknown / total, 1),
            "top_fleets": fleets[:8],
            "fleet_count": len(recent),
            "last_year": last_year,
        }

    with open(os.path.join(OUT, "fleets.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": "Sea Around Us (UBC), catch by fishing entity within each EEZ",
            "window_years": WINDOW,
            "note": ("Foreign share is catch taken inside a country's EEZ by fleets of "
                     "other nationalities. It is a reconstruction, not a landings record, "
                     "and it does not distinguish licensed access from unlicensed."),
            "count": len(out),
            "zones": out,
        }, f)

    print(f"\n  wrote {len(out)} zones ({len(no_data)} without a usable series)")
    have = [(n, v) for n, v in out.items() if v["total_t"] > 50000]
    have.sort(key=lambda kv: -kv[1]["foreign_pct"])
    print("\n  most foreign-dominated waters (>50k t/yr):")
    for n, v in have[:12]:
        top = v["top_fleets"][0]["fleet"] if v["top_fleets"] else "—"
        print(f"    {n[:30]:<32}{v['foreign_pct']:>6.1f}% foreign   "
              f"{v['total_t']:>9,}t   led by {top[:20]}")
    print("\n  most domestic (>50k t/yr):")
    for n, v in sorted(have, key=lambda kv: kv[1]["foreign_pct"])[:6]:
        print(f"    {n[:30]:<32}{v['foreign_pct']:>6.1f}% foreign   {v['total_t']:>9,}t")


if __name__ == "__main__":
    main()
