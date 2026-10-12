"""
Build the future layer: how much fish could each zone's waters hold by 2050 and
by 2100, if the climate keeps changing?

The numbers come from FishMIP, the Fisheries and Marine Ecosystem Model
Intercomparison Project. Several independent research groups each run their own
marine ecosystem model ("MEM") on the same ocean futures, simulated by two
Earth-system models (GFDL-ESM4 and IPSL-CM6A-LR). Every model x ocean pairing is
one "run". No single model is trustworthy on its own: they disagree about
mechanisms, and in some places about the direction of change. So the atlas
shows the middle of the runs, their spread, and how many of them agree.

What is measured. The variable is tcb, "total consumer biomass": the weight of
all animal life the model represents (fish, and in some models invertebrates
too), in grams per square metre. Each model counts a slightly different set of
animals, which is why we only ever compare a model with itself: % change from
its own 1995-2014 to its own future.

Why the runs without fishing. ISIMIP3b publishes two versions: "nat" (no
fishing at all) and runs with historical/fixed fishing. FishMIP's own climate
paper (Tittensor et al. 2021, Nature Climate Change, Methods) used no fishing so
that "climate change was the only stressor imposed". The fishing runs also
exist for only 2 of the 6 models (BOATS, EcoOcean), so using them would shrink
the ensemble from 10 runs to 4. The honest reading of the result is therefore:
"how much the ocean itself could support", not "how much will be in the net".

Periods are the IPCC AR6 standard: reference 1995-2014 (end of the historical
runs), mid-century 2041-2060, end of century 2081-2100. Scenarios: SSP1-2.6
(strong mitigation, roughly Paris-compatible) and SSP5-8.5 (very high emissions).

Method, per run, for every zone in site/data/eez.geojson:
  1. average the run's biomass over each period, cell by cell (every month or
     year in the period counts equally; a cell missing any month is dropped);
  2. zone mean = area-weighted mean over the 1-degree cells whose centres fall
     inside the zone polygon (land holes excluded). The weight is each cell's
     true area on the sphere, which is proportional to cos(latitude);
  3. % change = future zone mean / reference zone mean - 1. Because the cells
     and their areas are fixed, this is also the % change in the zone's total
     biomass.
A zone too small to contain a cell centre (many islands) uses the ocean cells
whose centres lie within 0.75 degrees of it (then 1.5, then 3), and is flagged
"approx". Countries (ISO3) pool the cells of their home zones and recompute,
rather than averaging the zones' percentages; "world" pools every ocean cell.

Ensemble statistics: the median of the runs, their range (min-max, or the
10th-90th percentile when 10 or more runs answer), n, and "agree", the share
of runs whose change has the same sign as the median. Runs are weighted equally
- one vote per model x Earth-system-model pair, as FishMIP does. Note what
that implies: models run with both ocean models (BOATS, EcoOcean, FEISTY,
ZooMSS) get two votes, APECOSM and DBPM (IPSL only) get one, so 6 of the 10
runs use IPSL ocean physics.

Outputs site/data/future.json.

Sources:
  https://data.isimip.org/api/v1/datasets/   ISIMIP3b, sector marine-fishery_global,
      variable tcb, soc_scenario nat. Licence: CC0 1.0 (the API's "rights"
      field for every file used). ISIMIP's terms ask users to credit the
      modelling groups; ISIMIP3b fisheries outputs have no dataset DOI, so the
      citation is the FishMIP CMIP6 ensemble paper plus acknowledgement:
      Tittensor, D.P. et al. (2021) Next-generation ensemble projections reveal
      higher climate risks for marine ecosystems. Nature Climate Change 11,
      973-981. https://doi.org/10.1038/s41558-021-01173-9

Needs numpy and netCDF4, which the rest of the atlas does not. Install once:
    python3 -m venv ~/venv-fishmip
    ~/venv-fishmip/bin/pip install numpy netCDF4
    ~/venv-fishmip/bin/python scripts/fetch_future.py
First run downloads 30 files (3.7 GB) to data/raw/fishmip/, git-ignored; a few
minutes on a fast line. Later runs reuse the downloads and the cached period
means and take well under a minute. Projections do not change, so this is a
one-off build; re-run only if ISIMIP publishes new model versions.
"""

import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor

# Some files store missing_value as a double beside float data, and netCDF4
# warns once per read. Harmless: _FillValue still masks those cells, and any
# fill value that slips through is caught in period_means().
warnings.filterwarnings("ignore", message=".*missing_value not used.*")

# The atlas's own point-in-polygon and edge-distance helpers, so a "zone" means
# the same polygon here as it does on the heat layer.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_climate import _edge_distance, _inside  # noqa: E402

try:
    import numpy as np
    import netCDF4
except ImportError:
    print("fetch_future.py needs numpy and netCDF4 - see the top of this file for the "
          "two-line install. future.json is left as it was.")
    sys.exit(1)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "site", "data")
RAW = os.path.join(HERE, "data", "raw", "fishmip")
MEANS = os.path.join(RAW, "period_means")

API = "https://data.isimip.org/api/v1/datasets/"
QUERY = {
    "simulation_round": "ISIMIP3b",
    "sector": "marine-fishery_global",
    "variable": "tcb",
    "soc_scenario": "nat",   # no fishing - see the docstring for why
}

BASELINE = (1995, 2014)
PERIODS = {"mid": (2041, 2060), "end": (2081, 2100)}
SCENARIOS = {"ssp126": "low emissions", "ssp585": "very high emissions"}

# Tittensor et al. 2021 used a different window: 2090-2099 against 1990-1999,
# and reported the ensemble *mean*. The same calculation is repeated here on
# the world numbers only, so the check against the paper is like for like.
PAPER_REF = (1990, 1999)
PAPER_END = (2090, 2099)

# Small zones: how far (in degrees) to look for ocean cells, nearest first.
APPROX_STEPS = (0.75, 1.5, 3.0)

# The 1-degree global grid every FishMIP ISIMIP3b file uses: rows from 89.5 N
# down to 89.5 S, columns from 179.5 W to 179.5 E. Files are checked against it.
LATS = [89.5 - i for i in range(180)]
LONS = [-179.5 + j for j in range(360)]


def get_json(url, tries=3, timeout=120):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def list_runs():
    """
    Ask ISIMIP which files exist, and keep the model x ESM pairs that have all
    three of historical, ssp126 and ssp585. The answer is cached in data/raw so a
    rebuild uses exactly the same file list (delete the cache to re-ask).
    """
    cache = os.path.join(RAW, "isimip_datasets.json")
    if os.path.exists(cache):
        with open(cache) as f:
            datasets = json.load(f)
    else:
        datasets = []
        for scen in ["historical"] + list(SCENARIOS):
            q = dict(QUERY, climate_scenario=scen, page_size=200)
            page = get_json(API + "?" + urllib.parse.urlencode(q))
            datasets += page["results"]
        with open(cache, "w") as f:
            json.dump(datasets, f, indent=1)

    runs = {}
    for d in datasets:
        s = d["specifiers"]
        # picontrol and other experiments can slip into a broad query; keep only ours
        if s.get("climate_scenario") not in ["historical"] + list(SCENARIOS):
            continue
        if s.get("soc_scenario") != "nat" or s.get("sens_scenario", "default") != "default":
            continue
        if len(d["files"]) != 1:
            raise SystemExit(f"  ! {d['name']} has {len(d['files'])} files; expected one")
        f = d["files"][0]
        run = f"{s['model']}_{s['climate_forcing']}"
        runs.setdefault(run, {})[s["climate_scenario"]] = {
            "name": f["name"], "url": f["file_url"], "size": f["size"],
            "sha512": f["checksum"], "version": d["version"],
            "licence": (d.get("rights") or {}).get("short"),
        }
    complete = {r: v for r, v in runs.items() if len(v) == 1 + len(SCENARIOS)}
    dropped = sorted(set(runs) - set(complete))
    return dict(sorted(complete.items())), dropped


def download(meta):
    """Download one file unless it is already here at the right size."""
    path = os.path.join(RAW, meta["name"])
    if os.path.exists(path) and os.path.getsize(path) == meta["size"]:
        return path
    part = path + ".part"
    req = urllib.request.Request(meta["url"], headers={"User-Agent": "ssf-atlas/0.1"})
    with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as out:
        while True:
            chunk = r.read(1 << 22)
            if not chunk:
                break
            out.write(chunk)
    if os.path.getsize(part) != meta["size"]:
        raise SystemExit(f"  ! {meta['name']} arrived incomplete; run again")
    os.replace(part, path)
    return path


def sha512(path):
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def period_means(path, periods):
    """
    Average one file over each (first year, last year) period, cell by cell.

    Returns {period: 180x360 array}, NaN where the cell is land or missing in
    any time step of the period. Monthly and annual files are both handled:
    every time step in the period counts equally, which for monthly files is
    the same as averaging the annual means. Results are cached as .npy, because
    decompressing 20 years of monthly global grids is the slow part.
    """
    out, todo = {}, []
    for p in periods:
        cached = os.path.join(MEANS, f"{os.path.basename(path)[:-3]}__{p[0]}-{p[1]}.npy")
        if os.path.exists(cached):
            out[p] = np.load(cached)
        else:
            todo.append((p, cached))
    if not todo:
        return out

    with netCDF4.Dataset(path) as ds:
        lat, lon = ds["lat"][:], ds["lon"][:]
        # Every file so far is on the same grid in the same order. If a future
        # version is not, stop rather than silently mixing up cells.
        if list(np.round(lat, 3)) != LATS or list(np.round(lon, 3)) != LONS:
            raise SystemExit(f"  ! {os.path.basename(path)} is not on the expected 1-degree grid")
        t = ds["time"]
        years = np.array([d.year for d in netCDF4.num2date(
            t[:], t.units, getattr(t, "calendar", "standard"))])
        var = ds["tcb"]
        for p, cached in todo:
            idx = np.where((years >= p[0]) & (years <= p[1]))[0]
            nyears = p[1] - p[0] + 1
            # A period must be complete: 20 annual steps or 240 monthly ones,
            # in one unbroken block.
            if len(idx) not in (nyears, 12 * nyears) or idx[-1] - idx[0] + 1 != len(idx):
                raise SystemExit(f"  ! {os.path.basename(path)} does not fully cover {p[0]}-{p[1]}")
            block = var[idx[0]:idx[-1] + 1]
            block = np.ma.filled(block.astype("f8"), np.nan)
            block[block > 1e19] = np.nan   # fill values that escaped the mask
            mean = block.mean(axis=0)      # NaN anywhere in a cell's series -> NaN
            os.makedirs(MEANS, exist_ok=True)
            np.save(cached, mean)
            out[p] = mean
    return out


def cell_areas():
    """Area of each 1-degree cell in km2, by row: R^2 x dlon x (sin top - sin bottom)."""
    r = 6371.0
    dlon = math.radians(1.0)
    rows = [r * r * dlon * (math.sin(math.radians(la + 0.5)) - math.sin(math.radians(la - 0.5)))
            for la in LATS]
    return np.repeat(np.array(rows)[:, None], 360, axis=1)


def zone_cells(geometry):
    """
    Grid cells whose centres fall inside the zone, as a list of (row, col).
    An EEZ is the 200-mile line with the land cut out as holes, so a centre
    inside a hole is land and does not count.
    """
    t = geometry["type"]
    polys = [geometry["coordinates"]] if t == "Polygon" else geometry["coordinates"]
    cells = set()
    for poly in polys:
        outer, holes = poly[0], poly[1:]
        xs = [p[0] for p in outer]
        ys = [p[1] for p in outer]
        hole_boxes = [(h, min(p[0] for p in h), max(p[0] for p in h),
                       min(p[1] for p in h), max(p[1] for p in h)) for h in holes]
        # only the cell centres inside the polygon's bounding box can be inside it
        j0 = max(0, math.ceil(min(xs) - (-179.5)))
        j1 = min(359, math.floor(max(xs) - (-179.5)))
        i0 = max(0, math.ceil(89.5 - max(ys)))
        i1 = min(179, math.floor(89.5 - min(ys)))
        for i in range(i0, i1 + 1):
            y = LATS[i]
            for j in range(j0, j1 + 1):
                x = LONS[j]
                if not _inside(outer, x, y):
                    continue
                if any(hx0 <= x <= hx1 and hy0 <= y <= hy1 and _inside(h, x, y)
                       for h, hx0, hx1, hy0, hy1 in hole_boxes):
                    continue
                cells.add((i, j))
    return cells


def near_cells(geometry, ocean):
    """
    For a zone too small to hold a cell centre: the ocean cells nearest to it.
    Distance is to the zone's outline, in degrees, so a cell whose square
    touches the zone (centre within ~0.71 degrees) is picked up first.
    """
    t = geometry["type"]
    polys = [geometry["coordinates"]] if t == "Polygon" else geometry["coordinates"]
    rings = [ring for poly in polys for ring in poly]
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    for reach in APPROX_STEPS:
        found = set()
        j0 = max(0, math.ceil(min(xs) - reach + 179.5))
        j1 = min(359, math.floor(max(xs) + reach + 179.5))
        i0 = max(0, math.ceil(89.5 - max(ys) - reach))
        i1 = min(179, math.floor(89.5 - min(ys) + reach))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                if ocean[i, j] and min(_edge_distance(r, LONS[j], LATS[i]) for r in rings) <= reach:
                    found.add((i, j))
        if found:
            return found
    return set()


def ensemble(values):
    """Median, range, n and sign agreement across the runs that answered."""
    v = [x for x in values if x is not None]
    if not v:
        return None
    a = np.array(v)
    med = float(np.median(a))
    if len(v) >= 10:
        lo, hi = float(np.percentile(a, 10)), float(np.percentile(a, 90))
    else:
        lo, hi = float(a.min()), float(a.max())
    sign = 1 if med > 0 else -1 if med < 0 else 0
    agree = sum(1 for x in v if (x > 0) - (x < 0) == sign) / len(v)
    return {"median": r1(med), "lo": r1(lo), "hi": r1(hi), "n": len(v),
            "agree": round(agree, 2), "by_run": [r1(x) if x is not None else None for x in values]}


def r1(x):
    x = round(x, 1)
    return 0.0 if x == 0 else x   # no "-0.0" on the page


def change(ref, fut, w, cells):
    """% change of the area-weighted mean over the given (rows, cols)."""
    if cells is None or len(cells[0]) == 0:
        return None
    rr, ff, ww = ref[cells], fut[cells], w[cells]
    m0 = float((rr * ww).sum() / ww.sum())
    m1 = float((ff * ww).sum() / ww.sum())
    if m0 <= 0:
        return None
    return 100.0 * (m1 / m0 - 1.0)


def main():
    os.makedirs(RAW, exist_ok=True)
    started = time.time()

    print("FishMIP runs on ISIMIP (tcb, no fishing)")
    runs, dropped = list_runs()
    for r, files in runs.items():
        print(f"  {r:<26} {files['historical']['version']}")
    if dropped:
        print(f"  skipped (missing a scenario): {', '.join(dropped)}")
    total = sum(f["size"] for v in runs.values() for f in v.values())
    print(f"  {len(runs)} runs, {3 * len(runs)} files, {total / 1e9:.2f} GB")

    print("\nDownloading (skips files already in data/raw/fishmip)")
    metas = [m for v in runs.values() for m in v.values()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, metas))

    # ISIMIP publishes a SHA-512 for every file. On 11 October 2026 the three
    # ZooMSS x IPSL files did not match theirs, although the size, header and a
    # second download all agreed - the record looks stale rather than the data
    # damaged. A mismatch is reported in the output instead of being hidden.
    mismatched = [m["name"] for m in metas if sha512(os.path.join(RAW, m["name"])) != m["sha512"]]
    for n in mismatched:
        print(f"  ! checksum differs from ISIMIP's record: {n}")

    print("\nPeriod means")
    hist_periods = [BASELINE, PAPER_REF]
    fut_periods = list(PERIODS.values()) + [PAPER_END]
    ref, fut = {}, {}
    for r, files in runs.items():
        h = period_means(os.path.join(RAW, files["historical"]["name"]), hist_periods)
        ref[r] = h
        fut[r] = {s: period_means(os.path.join(RAW, files[s]["name"]), fut_periods) for s in SCENARIOS}
        print(f"  {r}")

    # A cell counts for a run only where that run has a value in the reference
    # and in every future period of both scenarios, so each run compares the
    # same water across scenarios and periods.
    valid = {}
    for r in runs:
        ok = np.isfinite(ref[r][BASELINE]) & np.isfinite(ref[r][PAPER_REF])
        for s in SCENARIOS:
            for p in fut_periods:
                ok &= np.isfinite(fut[r][s][p])
        valid[r] = ok
    ocean = np.zeros((180, 360), bool)
    for ok in valid.values():
        ocean |= ok
    w = cell_areas()
    run_names = list(runs)

    def stats_for(cellset):
        """All scenario x period statistics for one set of cells."""
        cells = sorted(cellset)
        rows = np.array([c[0] for c in cells], int)
        cols = np.array([c[1] for c in cells], int)
        out = {}
        per_run_cells = {}
        for r in run_names:
            keep = valid[r][rows, cols]
            per_run_cells[r] = (rows[keep], cols[keep]) if keep.any() else None
        for s in SCENARIOS:
            out[s] = {}
            for key, p in PERIODS.items():
                vals = [change(ref[r][BASELINE], fut[r][s][p], w, per_run_cells[r]) for r in run_names]
                out[s][key] = ensemble(vals)
        return out

    print("\nZones")
    with open(os.path.join(OUT, "eez.geojson")) as f:
        feats = json.load(f)["features"]
    zones, zone_cellsets, missing = {}, {}, []
    approx_count = 0
    for feat in feats:
        props = feat["properties"]
        inside = {c for c in zone_cells(feat["geometry"]) if ocean[c]}
        approx = not inside
        cells = inside or near_cells(feat["geometry"], ocean)
        if not cells:
            missing.append({"name": props["name"], "iso3": props.get("iso3"),
                            "reason": "no model ocean cell within 3 degrees"})
            continue
        approx_count += approx
        zone_cellsets[props["name"]] = cells
        zones[props["name"]] = dict({"iso3": props.get("iso3"), "cells": len(cells), "approx": approx},
                                    **stats_for(cells))
    print(f"  {len(zones)} zones ({approx_count} approximate), {len(missing)} missing")

    # Countries pool their home waters: zones that are the country itself or a
    # piece of it ('self', 'split'). Overseas territories carry their
    # sovereign's code in eez.geojson, and pooling them would let Kerguelen's
    # Southern Ocean outweigh mainland France; they keep their own zone entries.
    # A code with only territory zones (e.g. FLK) pools those.
    print("Countries")
    by_iso = {}
    for feat in feats:
        p = feat["properties"]
        if p["name"] in zone_cellsets and p.get("iso3"):
            by_iso.setdefault(p["iso3"], []).append((p["name"], p.get("iso_kind")))
    countries = {}
    for iso, members in sorted(by_iso.items()):
        home = [n for n, kind in members if kind in ("self", "split")] or [n for n, _ in members]
        cells = set().union(*(zone_cellsets[n] for n in home))
        countries[iso] = dict({"zones": home, "cells": len(cells),
                               "approx": all(zones[n]["approx"] for n in home)}, **stats_for(cells))
    print(f"  {len(countries)} countries")

    # World: every ocean cell, high seas included.
    world = stats_for({(int(i), int(j)) for i, j in zip(*np.where(ocean))})
    for s in SCENARIOS:
        for key in PERIODS:
            vals = [x for x in world[s][key]["by_run"] if x is not None]
            world[s][key]["mean"] = r1(sum(vals) / len(vals))

    # The paper's own definition, for the like-for-like check.
    paper = {}
    for s in SCENARIOS:
        vals = [change(ref[r][PAPER_REF], fut[r][s][PAPER_END], w, np.where(valid[r])) for r in run_names]
        paper[s] = {"mean": r1(sum(vals) / len(vals)), "sd": r1(float(np.std(vals, ddof=1))),
                    "median": r1(float(np.median(vals))), "n": len(vals)}

    result = {
        "generated": time.strftime("%Y-%m-%d"),
        "source": ("FishMIP (Fisheries and Marine Ecosystem Model Intercomparison Project), "
                   "ISIMIP3b simulation round, sector marine-fishery_global, via the ISIMIP "
                   "Repository (data.isimip.org)"),
        "citation": ("Tittensor, D.P. et al. (2021) Next-generation ensemble projections reveal "
                     "higher climate risks for marine ecosystems. Nature Climate Change 11, 973-981. "
                     "https://doi.org/10.1038/s41558-021-01173-9. Model outputs from the FishMIP "
                     "modelling groups (APECOSM, BOATS, DBPM, EcoOcean, FEISTY, ZooMSS), the ISIMIP "
                     "sector coordinators and the ISIMIP cross-sectoral science team."),
        "licence": "CC0 1.0 (ISIMIP Repository rights field for every file used)",
        "variable": "tcb",
        "variable_meaning": ("Total consumer biomass: the weight of all animals each model represents "
                             "(fish, and in some models invertebrates), per square metre of sea. "
                             "Models count different sets of animals, so only % change within a "
                             "model is meaningful."),
        "fishing": ("No fishing ('nat' runs), as in Tittensor et al. 2021: climate is the only "
                    "pressure, so this is what the ocean could support, not what will be caught."),
        "baseline": f"{BASELINE[0]}–{BASELINE[1]}",
        "periods": {k: f"{a}–{b}" for k, (a, b) in PERIODS.items()},
        "scenarios": SCENARIOS,
        "runs": run_names,
        "run_versions": {r: runs[r]["historical"]["version"] for r in run_names},
        "weighting": ("Equal weight per run (one run = one ecosystem model x one Earth-system model). "
                      "Models run with both Earth-system models count twice; 6 of 10 runs use IPSL."),
        "range_rule": ("lo/hi are the 10th and 90th percentiles (linear interpolation) when n >= 10, "
                       "otherwise the minimum and maximum of the runs."),
        "method_note": ("For each run, biomass is averaged over each period cell by cell, then over "
                        "the zone with each 1-degree cell weighted by its area (proportional to cos "
                        "latitude), using cells whose centres fall inside the zone. % change = "
                        "future mean / 1995–2014 mean − 1. 'median', 'lo', 'hi' summarise the runs "
                        "that cover the zone ('n'); 'agree' is the share of those runs with the "
                        "same sign as the median; 'by_run' lists each run's value in the order of "
                        "'runs' (null = that model has no ocean there). 'approx': the zone is too "
                        "small to contain a cell centre, so the nearest ocean cells (within 0.75°, "
                        "else 1.5°, else 3°) stand in. Countries pool the cells of their home "
                        "zones ('zones' lists them; overseas territories keep their own entries); "
                        "the world pools every ocean cell including the high seas and also gives "
                        "the ensemble 'mean', the statistic FishMIP papers report."),
        "world": world,
        "world_check": {
            "definition": "Ensemble mean (sd) of the same runs, 2090–2099 vs 1990–1999, the window used by Tittensor et al. 2021",
            "this_build": paper,
            "published": {
                "tittensor_2021_cmip6": {"ssp126": -7, "ssp585": -19,
                                          "note": "≈ values in the text, 9 models / 16 runs, "
                                                  "of which ISIMIP now publishes tcb for 6 models / 10 runs"},
                "lotze_2019_cmip5": {"rcp26": -5, "rcp85": -17,
                                     "note": "the previous (CMIP5) FishMIP ensemble, Lotze et al. 2019 "
                                             "PNAS, by 2100, ±4 and ±11 sd"},
            },
        },
        "checksum_mismatch": mismatched,
        "zones": zones,
        "countries": countries,
        "missing": missing,
    }
    # Written compact, like value.json: the per-run lists make an indented file
    # twice the size (520 KB against 266 KB) for no gain in the browser.
    with open(os.path.join(OUT, "future.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n  wrote future.json in {time.time() - started:.0f}s")
    for s in SCENARIOS:
        for key, p in PERIODS.items():
            e = world[s][key]
            print(f"  world {s} {p[0]}-{p[1]}: median {e['median']:+.1f}%  "
                  f"(mean {e['mean']:+.1f}, range {e['lo']:+.1f} to {e['hi']:+.1f}, "
                  f"{e['agree']:.0%} agree)")
    for s, e in paper.items():
        print(f"  paper window {s}: mean {e['mean']:+.1f}% sd {e['sd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
