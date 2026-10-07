"""
Build country landmass polygons for the 'by country' scale.

The atlas is drawn on exclusive economic zones, which are ocean. Switching to
country scale and re-colouring those same ocean shapes answers the question in
the wrong shape - a reader asking for "Indonesia" wants Indonesia, not the water
around it.

Sea Around Us publishes country land geometry alongside its EEZs, keyed by the
same ISO3 codes, so the two scales line up without another source.

Outputs site/data/country.geojson.
"""

import json
import math
import os
import time

import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "sau_country.json")
OUT = os.path.join(HERE, "site", "data")

TOLERANCE = 0.02  # degrees; land outlines need less precision than coastlines do


def simplify(points, tol):
    """Douglas-Peucker, iterative."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x1, y1 = points[a]
        x2, y2 = points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = dx * dx + dy * dy
        worst, wi = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if norm == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / norm))
                d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
            if d > worst:
                worst, wi = d, i
        if worst > tol and wi > 0:
            keep[wi] = True
            stack.append((a, wi))
            stack.append((wi, b))
    return [p for p, k in zip(points, keep) if k]


def main():
    if not os.path.exists(RAW):
        raise SystemExit("country reference not cached - run scripts/countries.py first")
    os.makedirs(OUT, exist_ok=True)

    src = json.load(open(RAW))["data"]["features"]

    # Sea Around Us tags a handful of countries with Natural Earth's "-99" sentinel
    # instead of an ISO code - France and Norway among them - so their landmasses
    # would silently vanish from the country scale. Recover them by name.
    BY_NAME = {"france": "FRA", "norway": "NOR", "kosovo": "XKX", "somaliland": "SOM"}
    feats, skipped, vin, vout = [], [], 0, 0

    for f in src:
        p = f.get("properties") or {}
        iso = (p.get("c_iso_code") or "").strip().upper()
        if iso in ("", "-99"):
            iso = BY_NAME.get(str(p.get("title", "")).strip().lower(), "")
        geom = f.get("geometry")
        if not iso or not geom or not geom.get("coordinates"):
            skipped.append(p.get("title"))
            continue

        rings_in = ([geom["coordinates"]] if geom["type"] == "Polygon"
                    else geom["coordinates"])
        polys = []
        for poly in rings_in:
            out_rings = []
            for ring in poly:
                vin += len(ring)
                # Drop islands too small to see before spending vertices on them.
                xs = [pt[0] for pt in ring]
                ys = [pt[1] for pt in ring]
                if max(max(xs) - min(xs), max(ys) - min(ys)) < 0.05:
                    continue
                thin = simplify([(pt[0], pt[1]) for pt in ring], TOLERANCE)
                if len(thin) < 4:
                    continue
                if thin[0] != thin[-1]:
                    thin.append(thin[0])
                vout += len(thin)
                out_rings.append([[round(x, 3), round(y, 3)] for x, y in thin])
            if out_rings:
                polys.append(out_rings)
        if not polys:
            skipped.append(p.get("title"))
            continue

        # The site prints this name as the country heading, so it gets the
        # atlas's spelling rather than Natural Earth's ("Dem. Rep. Congo").
        feats.append({
            "type": "Feature",
            "properties": {"iso3": iso, "name": iso_lookup.display_name(iso, p.get("title"))},
            "geometry": {"type": "MultiPolygon", "coordinates": polys},
        })

    path = os.path.join(OUT, "country.geojson")
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)

    size = os.path.getsize(path) / 1e6
    print(f"  {len(feats)} countries with land geometry")
    print(f"  vertices {vin:,} -> {vout:,}")
    print(f"  wrote country.geojson ({size:.1f} MB)")
    if skipped:
        print(f"  {len(skipped)} without usable geometry: {', '.join(str(s) for s in skipped[:6])}")


if __name__ == "__main__":
    main()
