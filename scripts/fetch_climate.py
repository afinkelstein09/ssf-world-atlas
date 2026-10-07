"""
Build the climate layer: what is the ocean doing to these fisheries right now?

Three timescales:

  ENSO           one global number, weekly and monthly. El Nino is the single most
                 consequential recurring climate signal for small-scale fisheries.
  Marine heatwave per EEZ, daily, everywhere. The headline metric.
  Coral heat     per EEZ, daily, tropics only. Secondary, and reef-specific.

Why two heat metrics. Degree heating weeks is what NOAA Coral Reef Watch is famous
for, but it is calibrated to coral: the 4 and 8 thresholds come from bleaching
studies. Applied to Peru's anchoveta or Norway's cod it means nothing, and because
it is only meaningful in the tropics it also silently deleted most of Europe and
North America from the layer.

The marine heatwave category fixes both problems. It classifies sea surface
temperature against each location's own climatology, so "unusually hot for here"
means the same thing off Svalbard as off Fiji, and it is defined globally. Degree
heating weeks is kept alongside it, labelled as the coral-specific measure it is.

Outputs site/data/climate.json.

Sources:
  https://www.cpc.ncep.noaa.gov/data/indices/     NOAA CPC, public domain
  https://pae-paha.pacioos.hawaii.edu/erddap/     NOAA Coral Reef Watch via PacIOOS
"""

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "site", "data")

ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
WEEKLY_NINO = "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"
ERDDAP = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap"

# NOAA's marine heatwave scale, after Hobday et al. Categories are defined by how
# far SST exceeds the local climatology, so they are comparable between oceans.
MHW_LABELS = {
    0: "No heatwave",
    1: "Moderate heatwave",
    2: "Strong heatwave",
    3: "Severe heatwave",
    4: "Extreme heatwave",
    5: "Beyond extreme",
}

# Degree heating weeks, kept for reef zones only and labelled as such.
CORAL_LABELS = {
    0: "No coral heat stress",
    1: "Coral watch",
    2: "Coral warning",
    3: "Bleaching likely",
    4: "Mortality likely",
}


def get_text(url, tries=3, timeout=60):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def enso():
    """Current El Nino / La Nina state and recent trajectory."""
    out = {}
    raw = get_text(ONI)
    if raw:
        rows = []
        for line in raw.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    rows.append({"season": parts[0], "year": int(parts[1]),
                                 "anomaly": float(parts[3])})
                except ValueError:
                    continue
        if rows:
            latest = rows[-1]
            out["oni"] = latest["anomaly"]
            out["oni_season"] = f"{latest['season']} {latest['year']}"
            out["oni_recent"] = [[r["season"], r["anomaly"]] for r in rows[-6:]]
            v = latest["anomaly"]
            if v >= 1.5:
                state, note = "Strong El Nino", "Major disruption to eastern Pacific fisheries likely."
            elif v >= 0.5:
                state, note = "El Nino", "Warm phase — expect reduced upwelling in the eastern Pacific."
            elif v <= -1.5:
                state, note = "Strong La Nina", "Cool phase, unusually strong."
            elif v <= -0.5:
                state, note = "La Nina", "Cool phase — often stronger upwelling off South America."
            else:
                state, note = "Neutral", "No strong ENSO signal."
            out["state"], out["note"] = state, note

            # "The highest since ..." - walk back past the current event, then
            # find the last season that matched or beat today's reading. The
            # record starts in 1950, so an empty answer means a record.
            if abs(v) >= 0.5:
                sign = 1 if v > 0 else -1
                i = len(rows) - 1
                while i >= 0 and sign * rows[i]["anomaly"] >= 0.5:
                    i -= 1
                # "The highest since" is only true while this reading is the event's
                # own peak. Once the event turns, the card says how far it has come
                # down from its peak instead.
                event = rows[i + 1:]
                peak = max(event, key=lambda r: sign * r["anomaly"])
                if sign * peak["anomaly"] > sign * v:
                    out["event_peak"] = {"oni": peak["anomaly"], "season": f"{peak['season']} {peak['year']}"}
                while i >= 0 and sign * rows[i]["anomaly"] < sign * v:
                    i -= 1
                if i >= 0:
                    s, y = rows[i]["season"], rows[i]["year"]
                    # Seasons straddling the new year read as "2015–16".
                    if s in ("OND", "NDJ"):
                        label = f"{y}–{(y + 1) % 100:02d}"
                    elif s in ("DJF", "JFM"):
                        label = f"{y - 1}–{y % 100:02d}"
                    else:
                        label = str(y)
                    out["since"] = label
                else:
                    out["since"] = "records began in 1950"

    raw = get_text(WEEKLY_NINO)
    if raw:
        # The file is fixed-width and a negative anomaly runs into the number before
        # it ("20.6-0.1"), so splitting on spaces skipped every week with a cool
        # reading and the card quietly showed an older week. Numbers are read with a
        # pattern instead: date, then four (temperature, anomaly) pairs.
        import re
        for line in reversed([l for l in raw.strip().splitlines() if l.strip()]):
            date = line.split()[0] if line.split() else ""
            nums = re.findall(r"-?\d+\.\d", line[len(line) - len(line.lstrip()) + len(date):])
            if date[:2].isdigit() and len(nums) >= 8:
                out["week"] = date
                out["nino12_anomaly"] = float(nums[1])
                out["nino34_anomaly"] = float(nums[5])
                break
    return out


def ring_centroid(coords):
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _inside(ring, x, y):
    """Ray-casting point-in-polygon."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _edge_distance(ring, x, y):
    """Distance in degrees from (x, y) to the nearest ring edge."""
    best = float("inf")
    n = len(ring)
    for i in range(n):
        ax, ay = ring[i][0], ring[i][1]
        bx, by = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            d = ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            d = ((x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2) ** 0.5
        if d < best:
            best = d
    return best


def sample_point(geometry, box=0.6):
    """
    A point inside the zone to sample the heat grids at.

    The vertex-mean centroid of an EEZ is very often on land - a coastal zone
    wraps around its coast, so its centre of mass is the coast. That put the
    sample box on Baffin Island for Canada's Arctic zone, in the outback for
    Australia, and inside Kuwait's waters for Iraq, so 15 large zones returned
    nothing and several more were reading someone else's water. The centroid
    is kept when it lies inside the zone; otherwise a grid over the largest
    ring is searched for the interior point furthest from the zone's edges,
    which is water by construction and, where the zone allows it, far enough
    in that the whole sample box is water too.
    """
    t = geometry.get("type")
    if t == "Polygon":
        polys = [geometry["coordinates"]]
    elif t == "MultiPolygon":
        polys = geometry["coordinates"]
    else:
        return None
    # An EEZ polygon is the 200-mile line with the land cut out as holes - the
    # Australian mainland is a 3,600-vertex hole in a 234-vertex ring. A point
    # inside the outer ring is very likely on land, so the holes have to count.
    poly = max(polys, key=lambda p: len(p[0]))
    outer, holes = poly[0], poly[1:]

    def bbox(ring):
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return min(xs), max(xs), min(ys), max(ys)

    hole_boxes = [(h, bbox(h)) for h in holes]

    def in_zone(x, y):
        if not _inside(outer, x, y):
            return False
        for h, (hx0, hx1, hy0, hy1) in hole_boxes:
            if hx0 <= x <= hx1 and hy0 <= y <= hy1 and _inside(h, x, y):
                return False
        return True

    # Thin the rings for the distance search: distance to a 300-vertex outline
    # is close enough to choose a sample point with.
    def thin(ring):
        step = max(1, len(ring) // 300)
        t_ = ring[::step]
        return t_ if len(t_) >= 4 else ring

    thin_rings = [(thin(outer), bbox(outer))] + [(thin(h), b) for h, b in hole_boxes]

    def edge(x, y):
        best = float("inf")
        for r, (bx0, bx1, by0, by1) in thin_rings:
            # a ring whose box is further away than the best so far cannot win
            gap = max(bx0 - x, x - bx1, by0 - y, y - by1, 0.0)
            if gap >= best:
                continue
            d = _edge_distance(r, x, y)
            if d < best:
                best = d
        return best

    cx, cy = ring_centroid(outer)
    if in_zone(cx, cy) and edge(cx, cy) >= box:
        return cx, cy

    # Full-resolution distance, for the final choice only: the thinned rings
    # rank candidates quickly but can overstate the distance to a coast by an
    # order of magnitude (Norway's 2,356-vertex ring thinned to 300 read 5.8
    # degrees for a point 0.13 from the shore).
    full_rings = [(outer, bbox(outer))] + hole_boxes

    def edge_full(x, y):
        best = float("inf")
        for r, (bx0, bx1, by0, by1) in full_rings:
            gap = max(bx0 - x, x - bx1, by0 - y, y - by1, 0.0)
            if gap >= best:
                continue
            d = _edge_distance(r, x, y)
            if d < best:
                best = d
        return best

    x0, x1, y0, y1 = bbox(outer)
    n = 40
    ranked = []
    for i in range(n):
        x = x0 + (x1 - x0) * (i + 0.5) / n
        for j in range(n):
            y = y0 + (y1 - y0) * (j + 0.5) / n
            if not in_zone(x, y):
                continue
            ranked.append((edge(x, y), x, y))
    if not ranked:
        return cx, cy
    ranked.sort(reverse=True)
    best, best_d = None, -1.0
    for _, x, y in ranked[:40]:
        d = edge_full(x, y)
        if d > best_d:
            best, best_d = (x, y), d
    # Prefer the centroid when it is inside and nearly as good: it is the
    # reader's mental picture of "the middle of the zone".
    if in_zone(cx, cy) and edge_full(cx, cy) >= 0.8 * best_d:
        return cx, cy
    return best


def _grid(dataset, variables, lon, lat, box):
    """Fetch a small box of one ERDDAP grid and return columns of clean floats."""
    lat0, lat1 = round(lat - box, 3), round(lat + box, 3)
    lon0, lon1 = round(lon - box, 3), round(lon + box, 3)
    sel = f"[last][({lat0}):({lat1})][({lon0}):({lon1})]"
    q = ",".join(f"{v}{sel}" for v in variables)
    raw = get_text(f"{ERDDAP}/{dataset}.csv?{q}", tries=2)
    if not raw:
        return None, None

    cols = {v: [] for v in variables}
    when = None
    for line in raw.splitlines()[2:]:
        parts = line.split(",")
        if len(parts) < 3 + len(variables):
            continue
        when = when or parts[0]
        for i, v in enumerate(variables):
            try:
                val = float(parts[3 + i])
            except (ValueError, IndexError):
                continue
            if val == val:  # NaN is the only value not equal to itself
                cols[v].append(val)
    return cols, when


def percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * q))]


def heat(lon, lat, box=0.6):
    """
    Marine heatwave status for one zone, plus coral heat stress where relevant.

    The headline category is a 75th percentile rather than a maximum: a heatwave
    is an area phenomenon, and one hot pixel should not speak for a whole EEZ.
    The share of the box in any heatwave is reported alongside it, because "how
    much of this zone" is the question a fisheries manager actually has.
    """
    out = {}

    cols, when = _grid("mhw_5km", ["heatwave_category"], lon, lat, box)
    if cols is None:
        return {"_no_answer": True}   # the server did not answer: retried in main()
    cats = cols.get("heatwave_category") or []
    if cats:
        out["mhw"] = int(percentile(cats, 0.75))
        out["mhw_max"] = int(max(cats))
        out["mhw_area"] = round(100.0 * sum(1 for c in cats if c >= 1) / len(cats))
        out["date"] = (when or "")[:10]

    # Coral stress is only meaningful where there are reefs. Outside the tropics
    # the query is skipped rather than returning a number nobody should use.
    if abs(lat) <= 35:
        cols, when2 = _grid("dhw_5km", ["CRW_DHW", "CRW_SSTANOMALY"], lon, lat, box)
        dhws = (cols or {}).get("CRW_DHW") or []
        anoms = (cols or {}).get("CRW_SSTANOMALY") or []
        if dhws:
            mean = round(sum(dhws) / len(dhws), 2)  # classify the value the reader sees
            out["dhw"] = mean
            # the warmest tenth can never read below the mean
            out["dhw_high"] = round(max(mean, percentile(dhws, 0.9)), 2)
            # "Coral watch" needs a reading that survives rounding: a mean of
            # 0.003 printed as "0 degree heating weeks" beside a watch label.
            out["coral"] = 4 if mean >= 8 else 3 if mean >= 4 else 2 if mean >= 1 else 1 if mean >= 0.05 else 0
            out.setdefault("date", (when2 or "")[:10])
        if anoms:
            out["sst_anomaly"] = round(sum(anoms) / len(anoms), 2)
    else:
        cols, _ = _grid("dhw_5km", ["CRW_SSTANOMALY"], lon, lat, box)
        anoms = (cols or {}).get("CRW_SSTANOMALY") or []
        if anoms:
            out["sst_anomaly"] = round(sum(anoms) / len(anoms), 2)

    return out or None


def main():
    os.makedirs(OUT, exist_ok=True)

    print("ENSO")
    state = enso()
    if not state.get("state"):
        print("  ! the El Nino index did not answer. climate.json is left as it was; run again later.")
        return 1
    if state.get("state"):
        print(f"  {state['state']}  ONI {state['oni']:+.2f} ({state['oni_season']})")
        if "nino12_anomaly" in state:
            print(f"  Nino 1+2 anomaly {state['nino12_anomaly']:+.1f} C  week of {state['week']}")

    with open(os.path.join(OUT, "eez.geojson")) as f:
        geo = json.load(f)
    feats = geo["features"]
    print(f"\nMarine heatwave + coral stress for {len(feats)} EEZs")

    def one(feat):
        name = feat["properties"]["name"]
        pt = sample_point(feat["geometry"])
        if not pt:
            return name, None
        return name, heat(pt[0], pt[1])

    zones = {}
    unanswered = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (name, h) in enumerate(pool.map(one, feats), 1):
            if h and h.get("_no_answer"):
                unanswered.append(name)
            elif h:
                zones[name] = h
            if i % 40 == 0 or i == len(feats):
                print(f"  {i}/{len(feats)}  ({time.time() - started:.0f}s)")

    # A slow server is not a calm sea. On 6 October 2026 the server took ~45 s a
    # request and 17 zones that had readings came back empty; written as they were,
    # China, Japan and Tanzania would have shown "no reading". Unanswered zones are
    # retried slowly, and if many still fail nothing is written.
    global get_text
    patient, quick = (lambda url, tries=4, timeout=180: quick(url, tries=4, timeout=180)), get_text
    get_text = patient
    for attempt in range(2):
        if not unanswered:
            break
        print(f"  retrying {len(unanswered)} zones the server did not answer")
        time.sleep(20)
        with ThreadPoolExecutor(max_workers=3) as pool:
            again = list(pool.map(one, [f for f in feats if f["properties"]["name"] in set(unanswered)]))
        unanswered = []
        for name, h in again:
            if h and h.get("_no_answer"):
                unanswered.append(name)
            elif h:
                zones[name] = h
    get_text = quick
    if len(unanswered) > 5:
        print(f"\n  ! the server still did not answer for {len(unanswered)} zones "
              f"({', '.join(unanswered[:6])}...). climate.json is left as it was; run again later.")
        return 1
    if unanswered:
        print(f"  ! no answer for {', '.join(unanswered)}; shown as no reading")

    with open(os.path.join(OUT, "climate.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "sources": {
                "enso": "NOAA Climate Prediction Center (public domain)",
                "heat": "NOAA Coral Reef Watch 5km, marine heatwave and degree heating weeks, via PacIOOS ERDDAP",
            },
            "mhw_labels": MHW_LABELS,
            "coral_labels": CORAL_LABELS,
            "note": ("Marine heatwave category compares sea surface temperature with each "
                     "location's own climatology, so it is comparable between oceans. Degree "
                     "heating weeks is calibrated to coral and is reported only within 35 "
                     "degrees of the equator."),
            "enso": state,
            "zones": zones,
        }, f, indent=1)

    withmhw = [z for z in zones.values() if "mhw" in z]
    withcoral = [z for z in zones.values() if "coral" in z]
    print(f"\n  wrote {len(zones)} zones — {len(withmhw)} with a heatwave reading, "
          f"{len(withcoral)} with coral stress")
    from collections import Counter
    dist = Counter(z["mhw"] for z in withmhw)
    print("  heatwave categories:")
    for k in sorted(dist):
        print(f"    {k} {MHW_LABELS[k]:<20}{dist[k]:>4} zones")
    hot = sorted(((n, z) for n, z in zones.items() if z.get("mhw")),
                 key=lambda kv: (-kv[1]["mhw"], -kv[1].get("mhw_area", 0)))[:10]
    if hot:
        print("\n  strongest marine heatwaves right now:")
        for n, z in hot:
            print(f"    {n[:32]:<34}cat {z['mhw']}  {z.get('mhw_area',0):>3}% of zone affected")


if __name__ == "__main__":
    import sys
    sys.exit(main())
