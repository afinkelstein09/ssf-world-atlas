"""
Build the value layer: what is the catch worth, and who earns it?

Tonnes are the wrong unit for half the questions people bring to a fisheries
map. Peru's small-scale fleet lands a fifth of the tonnage and more than two
fifths of the value, because the industrial fleet's anchoveta is ground into
fishmeal and the small boats land food fish. Sea Around Us publishes the landed
(ex-vessel) value of every tonne it reconstructs, through the same API and for
the same zones as the catch, so the two can be set side by side with no new
source and no new join.

Three things are computed for every ocean zone:

  value by sector       the small-scale share of value, next to the share of
                        tonnes the rest of the atlas uses
  price per tonne       small-scale against industrial
  value by fleet        how much of the value leaves with foreign fleets

Two national context figures are added, keyed by ISO3:

  fish per person       FAO food balance sheets, through Our World in Data
  fisheries in GDP      UN SDG indicator 14.7.1

Outputs site/data/value.json.

Sources:
  https://api.seaaroundus.org/api/v1/eez/value/sector/     Sea Around Us, cite per policy
  https://api.seaaroundus.org/api/v1/eez/value/country/
  https://ourworldindata.org/grapher/fish-and-seafood-consumption-per-capita   CC BY (FAO data)
  https://unstats.un.org/SDGAPI/                            UN Statistics Division

Values are Sea Around Us's estimates in real 2010 US dollars: a reconstruction
priced with a global ex-vessel price database, not a record of sales.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw")
OUT = os.path.join(HERE, "site", "data")
API = "https://api.seaaroundus.org/api/v1"

OWID_FISH = "https://ourworldindata.org/grapher/fish-and-seafood-consumption-per-capita.csv"
SDG_FSHGDP = ("https://unstats.un.org/SDGAPI/v1/sdg/Series/Data"
              "?seriesCode=EN_SCP_FSHGDP&pageSize=20000")

# The same window and the same small-scale definition as fetch_saup.py, so the
# share of value can sit beside the share of tonnes and mean the same thing.
WINDOW = 5
SSF_SECTORS = ("Artisanal", "Subsistence")
LOW_PRICE = 200     # dollars a tonne; below this a sector's price is treated as unreliable


def get_bytes(url, tries=3, timeout=90):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def get_json(url, **kw):
    raw = get_bytes(url, **kw)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def cached(kind, rid, url):
    """One zone's response for one endpoint, kept on disk so re-runs are instant."""
    folder = os.path.join(RAW, kind)
    path = os.path.join(folder, f"{rid}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    data = get_json(url)
    if data and data.get("data"):
        os.makedirs(folder, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    return data


def series_map(data):
    """{key: {year: value}} with nulls dropped - a null is a gap, not a zero."""
    out = {}
    for s in (data or {}).get("data") or []:
        clean = {}
        for pair in s.get("values") or []:
            if not pair or len(pair) < 2 or pair[1] is None:
                continue
            clean[int(pair[0])] = float(pair[1])
        if clean:
            out[s.get("key")] = clean
    return out


def price(value, tonnes, sectors, window):
    """
    Dollars per tonne for a group of sectors: total value over total tonnes,
    using only the sector-years where both numbers exist. A ratio of sums, not
    a mean of yearly prices, so one tiny year cannot swing it.
    """
    usd = t = 0.0
    for s in sectors:
        for y in window:
            if y in value.get(s, {}) and y in tonnes.get(s, {}):
                usd += value[s][y]
                t += tonnes[s][y]
    if t < 1:       # under a tonne a price is noise
        return None, usd, t
    return usd / t, usd, t


def zone_value(zone):
    rid = zone["region_id"]
    tonnes = series_map(cached("sector", rid, f"{API}/eez/tonnage/sector/?region_id={rid}"))
    value = series_map(cached("value_sector", rid, f"{API}/eez/value/sector/?region_id={rid}"))
    fleets = series_map(cached("value_fleets", rid, f"{API}/eez/value/country/?region_id={rid}"))
    if not value:
        return zone, None

    # The window is set by the catch record, exactly as in fetch_saup.py, so
    # both shares describe the same five years.
    years = {y for m in (tonnes or value).values() for y in m}
    last = max(years)
    window = list(range(last - WINDOW + 1, last + 1))

    recent, unknown = {}, []
    for sector, by_year in value.items():
        pts = [by_year[y] for y in window if y in by_year]
        if pts:
            recent[sector] = sum(pts) / len(pts)
        else:
            unknown.append(sector)   # no value in the window: unknown, not zero
    total = sum(recent.values())
    if total <= 0:
        return zone, None
    ssf = sum(recent.get(s, 0.0) for s in SSF_SECTORS)

    p_ssf, ssf_usd, ssf_t = price(value, tonnes, SSF_SECTORS, window)
    p_ind, ind_usd, ind_t = price(value, tonnes, ("Industrial",), window)
    p_all, all_usd, all_t = price(value, tonnes, tuple(value.keys()), window)

    out = {
        "iso3": zone.get("iso3"),
        "value_usd": round(total),
        "ssf_value_share": round(100.0 * ssf / total, 1),
        "sectors_usd": {k: round(v) for k, v in sorted(recent.items())},
        "usd_per_t": {
            "ssf": round(p_ssf) if p_ssf is not None else None,
            "industrial": round(p_ind) if p_ind is not None else None,
            "all": round(p_all) if p_all is not None else None,
        },
        # Window sums, carried so a country page can divide total dollars by
        # total tonnes across its zones instead of averaging prices.
        # Tonnes to 3 decimals: at 0.1 t the Falklands' 2.85 t became 2.8 and its
        # country page priced small-scale catch at $4,319 a tonne against $4,243.
        "sums": {"ssf_usd": round(ssf_usd), "ssf_t": round(ssf_t, 3),
                 "industrial_usd": round(ind_usd), "industrial_t": round(ind_t, 3)},
        "years": [window[0], window[-1]],
        "unknown_sectors": sorted(unknown),
    }

    # A price far below anything plausible is a gap in the price database, not a
    # bargain. Across all zones the middle half of small-scale prices runs from
    # about $1,200 to $3,400 a tonne and the 2nd percentile is about $300; Eritrea's
    # small-scale catch is priced at $31, which cuts its share of value from 42% of
    # the tonnes to 4%. Such zones are flagged: the page shows the numbers with a
    # caution and the map does not colour them.
    suspect = [label for label, p in (("small-scale", p_ssf), ("industrial", p_ind))
               if p is not None and p < LOW_PRICE]
    if suspect:
        out["suspect_price"] = suspect

    # Who earns it. Same rules as fetch_fleets.py: a fleet absent from a year
    # earned nothing that year (fixed denominator), the domestic fleet is found
    # through the ISO3 resolver, and value attributed to no fleet is its own
    # category rather than being counted as foreign.
    if fleets:
        fl_recent = {k: sum(m.get(y, 0.0) for y in window) / WINDOW
                     for k, m in fleets.items() if any(y in m for y in window)}
        fl_total = sum(fl_recent.values())
        if fl_total > 0:
            domestic = unknown_v = 0.0
            for fleet, usd in fl_recent.items():
                if str(fleet).strip().lower().startswith("unknown"):
                    unknown_v += usd
                    continue
                f_iso, _ = iso_lookup.resolve(fleet)
                if f_iso and zone.get("iso3") and f_iso == zone["iso3"]:
                    domestic += usd
            foreign = max(0.0, fl_total - domestic - unknown_v)
            out["fleets"] = {
                "foreign_value_pct": round(100.0 * foreign / fl_total, 1),
                "domestic_value_pct": round(100.0 * domestic / fl_total, 1),
                "unknown_value_pct": round(100.0 * unknown_v / fl_total, 1),
                "foreign_usd": round(foreign),
                "total_usd": round(fl_total),
            }
    return zone, out


def pacific_second_estimate():
    """
    A second opinion for the Pacific islands, keyed by atlas zone name.

    The Pacific Community values each island country's fisheries from agency reports
    and household surveys (Gillett and Fong 2023, "Benefish 4"). Its "coastal
    commercial" plus "coastal subsistence" is the region's small-scale sector. It
    matters here because Sea Around Us prices Kiribati's small-scale catch at under
    $30 a tonne, and this study puts it near $2,300. The table is a transcription
    kept in data/pacific_benefish_2021.csv, with its source and page numbers.
    """
    path = os.path.join(HERE, "data", "pacific_benefish_2021.csv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    out = {}
    for r in rows:
        t = float(r["coastal_commercial_t"]) + float(r["coastal_subsistence_t"])
        usd = float(r["coastal_commercial_usd"]) + float(r["coastal_subsistence_usd"])
        rec = {
            "entity": r["entity"], "year": 2021,
            "coastal_t": round(t), "coastal_usd": round(usd),
            "coastal_usd_per_t": round(usd / t) if t >= 1 else None,
            "subsistence_t": round(float(r["coastal_subsistence_t"])),
            "offshore_foreign_t": round(float(r["offshore_foreign_t"])),
            "offshore_foreign_usd": round(float(r["offshore_foreign_usd"])),
            "offshore_local_t": round(float(r["offshore_local_t"])),
            "offshore_local_usd": round(float(r["offshore_local_usd"])),
            "zones_covered": len(r["atlas_zones"].split("|")),
        }
        for zone in r["atlas_zones"].split("|"):
            out[zone] = rec
    return out


def fish_per_person():
    """Fish and seafood supply per person, latest year, by ISO3 (FAO via OWID)."""
    raw = get_bytes(OWID_FISH)
    if not raw:
        return {}, None
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8", errors="replace"))))
    out, world = {}, None
    for entity, code, year, val in (r[:4] for r in rows[1:] if len(r) >= 4):
        if not val:
            continue
        rec = {"kg": round(float(val), 1), "year": int(year)}
        if entity == "World":
            if not world or rec["year"] > world["year"]:
                world = rec
        elif len(code) == 3 and (code not in out or rec["year"] > out[code]["year"]):
            out[code] = rec
    return out, world


def fisheries_gdp():
    """UN SDG 14.7.1, sustainable fisheries as a share of GDP, by ISO3."""
    data = get_json(SDG_FSHGDP, timeout=120)
    if not data or not data.get("data"):
        return {}
    # The UN keys countries by M49 number, which is the ISO numeric code. Sea
    # Around Us's country list carries both, so it is the crosswalk.
    with open(os.path.join(RAW, "sau_country.json")) as f:
        feats = json.load(f)["data"]["features"]
    m49 = {int(p["properties"]["c_number"]): p["properties"]["c_iso_code"]
           for p in feats if p["properties"].get("c_number") and p["properties"].get("c_iso_code")}
    series = {}
    for row in data["data"]:
        try:
            iso = m49.get(int(row.get("geoAreaCode")))
            val = float(row.get("value"))
            year = int(float(row.get("timePeriodStart")))
        except (TypeError, ValueError):
            continue
        if iso and val == val:          # val == val drops NaN
            series.setdefault(iso, {})[year] = val
    out = {}
    for iso, by_year in series.items():
        first, last = min(by_year), max(by_year)
        out[iso] = {"pct": round(by_year[last], 2), "year": last,
                    "first_pct": round(by_year[first], 2), "first_year": first}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "countries.json")) as f:
        zones = json.load(f)["countries"]

    print(f"Landed value for {len(zones)} ocean zones")
    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, pair in enumerate(pool.map(zone_value, zones), 1):
            results.append(pair)
            if i % 40 == 0 or i == len(zones):
                print(f"  {i}/{len(zones)}  ({time.time() - started:.0f}s)")

    out, missing = {}, []
    for zone, rec in results:
        if rec:
            out[zone["name"]] = rec
        else:
            missing.append(zone["name"])

    pacific = pacific_second_estimate()
    for name, rec in pacific.items():
        if name in out:
            out[name]["pacific"] = rec
    print(f"Pacific second estimate (SPC, Gillett and Fong 2023): {len(pacific)} zones")

    print("Fish per person (FAO via Our World in Data)")
    fish, world = fish_per_person()
    print(f"  {len(fish)} countries" + (f", world {world['kg']} kg in {world['year']}" if world else ""))
    print("Fisheries in GDP (UN SDG 14.7.1)")
    gdp = fisheries_gdp()
    print(f"  {len(gdp)} countries")

    # A download that fails must not quietly erase figures the page already shows.
    # If either national source came back empty, the previous build's figures stay.
    prev_path = os.path.join(OUT, "value.json")
    if (not fish or not gdp) and os.path.exists(prev_path):
        with open(prev_path) as f:
            prev = json.load(f)
        if not fish:
            print("  ! fish-per-person download failed; keeping the previous figures")
            fish = {iso: {"kg": r["fish_kg"], "year": r["fish_year"]}
                    for iso, r in (prev.get("countries") or {}).items() if r.get("fish_kg") is not None}
            if prev.get("world"):
                world = {"kg": prev["world"]["fish_kg"], "year": prev["world"]["fish_year"]}
        if not gdp:
            print("  ! SDG 14.7.1 download failed; keeping the previous figures")
            gdp = {iso: r["gdp"] for iso, r in (prev.get("countries") or {}).items() if r.get("gdp")}

    national = {}
    for iso in sorted(set(fish) | set(gdp)):
        rec = {}
        if iso in fish:
            rec["fish_kg"] = fish[iso]["kg"]
            rec["fish_year"] = fish[iso]["year"]
        if iso in gdp:
            rec["gdp"] = gdp[iso]
        national[iso] = rec

    with open(os.path.join(OUT, "value.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": "Sea Around Us (UBC), landed value by sector and by fishing entity within each EEZ",
            "currency": "real 2010 US dollars",
            "window_years": WINDOW,
            "note": ("Landed (ex-vessel) value as estimated by Sea Around Us: reconstructed catch "
                     "priced with a global ex-vessel price database. An estimate, not sales records."),
            "count": len(out),
            "zones": out,
            "countries": national,
            "world": {"fish_kg": world["kg"], "fish_year": world["year"]} if world else None,
        }, f)

    print(f"\n  wrote {len(out)} zones ({len(missing)} without a value series)")
    if missing:
        print("  no value:", ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
    have = [(n, v) for n, v in out.items() if v["value_usd"] > 50_000_000]
    with open(os.path.join(OUT, "countries.json")) as f:
        share_t = {z["name"]: z.get("ssf_share") for z in json.load(f)["countries"]}
    gaps = sorted(have, key=lambda kv: -(kv[1]["ssf_value_share"] - (share_t.get(kv[0]) or 0)))
    print("\n  where small boats earn far more than their tonnage suggests (>$50M a year):")
    for n, v in gaps[:10]:
        print(f"    {n[:32]:<34}{share_t.get(n):>5.1f}% of tonnes  {v['ssf_value_share']:>5.1f}% of value")


if __name__ == "__main__":
    main()
