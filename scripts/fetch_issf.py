"""
Harvest the Information System on Small-scale Fisheries (ISSF).

ISSF is the Too Big To Ignore network's crowdsourced repository of small-scale
fisheries knowledge - community profiles, organisations, and research. It matters
to this atlas for one reason: it contains the conservation NGOs that IATI cannot
see. IATI reports aid-funded activity, so privately funded organisations are
absent from it; ISSF is contributed by researchers, so WCS, WorldFish and others
appear here instead.

Two things to state wherever this data is shown:

  1. It is largely dormant. Of 3,469 records, 2,795 were contributed between 2013
     and 2016, and one so far in 2026. This is an archive, not a live feed.
  2. Its coverage is academic, not geographic. Spain holds more organisation
     records than Indonesia or the Philippines - it maps where researchers who
     use the platform work, which is not where small-scale fishing is.

Outputs site/data/issf.json.

Source: https://issfcloud.toobigtoignore.net - public API, no key.
Too Big To Ignore: Global Partnership for Small-Scale Fisheries Research.
"""

import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "issf")
OUT = os.path.join(HERE, "site", "data")
BASE = "https://issfcloud.toobigtoignore.net/backend/public"

# Record types worth mapping. The literature archive (2,058 "State-of-the-Art"
# records) and the people directory are deliberately left out - they describe who
# studies small-scale fisheries, not who works in or on them.
KEEP = {
    "SSF Profile": "profile",
    "SSF Organization": "organization",
    "SSF Blue Justice": "blue_justice",
    "Case Study": "case_study",
}


def get(path, cache_name, tries=3):
    cache = os.path.join(RAW, cache_name)
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    os.makedirs(RAW, exist_ok=True)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(f"{BASE}{path}",
                                         headers={"User-Agent": "ssf-atlas/0.1",
                                                  "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            with open(cache, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            if attempt == tries - 1:
                print(f"  ! {path} failed: {e}")
                return None
            time.sleep(3 * (attempt + 1))
    return None


def strip_html(text):
    """Record summaries arrive as HTML fragments; the map needs plain text."""
    if not text:
        return None
    import re
    t = re.sub(r"<[^>]+>", " ", str(text))
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def label_from_summary(summary, record_type):
    """
    Pull a usable name out of the record summary.

    Summaries are formatted as "<strong>Field: </strong>value..." so the first
    value after the first label is the record's name in practice.
    """
    plain = strip_html(summary)
    if not plain:
        return None
    # Summaries begin with a field label ending in a colon.
    if ":" in plain:
        after = plain.split(":", 1)[1].strip()
        # Cut at the next field label, which reads as "Word Word:" mid-string.
        import re
        cut = re.split(r"\s{2,}|(?<=[a-z])\s(?=[A-Z][a-z]+:)", after)
        candidate = cut[0].strip() if cut else after
        # Some names carry the address after them ("... Address: ... Country: ..."),
        # and one record is named "As Above"; the directory already cleaned these.
        candidate = re.split(r"\s+(?:Address|Established in|Country):\s*", candidate, maxsplit=1)[0].strip()
        if candidate.lower() in ("as above", "n/a", "na", "-"):
            return None
        return candidate[:120] or None
    return plain[:120]


def _in_ring(ring, x, y):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def bbox(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def in_country(geom, lon, lat):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return any(_in_ring(poly[0], lon, lat) for poly in polys)


def main():
    os.makedirs(OUT, exist_ok=True)

    print("ISSF reference data")
    countries = get("/issf-base/get-all-countries", "countries.json") or []
    name_to_iso = {}
    iso_point = {}
    # Country outlines, to catch points with latitude and longitude swapped.
    country_shape, swapped, dropped_far = {}, [0], [0]
    shapes = os.path.join(OUT, "country.geojson")
    if os.path.exists(shapes):
        with open(shapes) as f:
            for ft in json.load(f)["features"]:
                iso3 = ft["properties"].get("iso3")
                if iso3 and ft.get("geometry"):
                    country_shape[iso3] = ft["geometry"]
    for c in countries:
        iso = (c.get("iso3") or "").strip().upper()
        if not iso:
            continue
        for key in (c.get("short_name"), c.get("official_name")):
            if key:
                name_to_iso[key.strip().lower()] = iso
        pt = c.get("country_point") or {}
        if pt.get("coordinates"):
            iso_point[iso] = pt["coordinates"]
    print(f"  {len(name_to_iso)} country names -> {len(iso_point)} centroids")

    print("ISSF contributions")
    raw = get("/issf-base/get-all-contributions", "contributions.json")
    if not raw:
        raise SystemExit("could not fetch contributions")
    records = list(raw.values()) if isinstance(raw, dict) else raw
    print(f"  {len(records)} records total")

    out = []
    by_country = {}
    years = {}
    unmatched = set()

    for r in records:
        rtype = r.get("core_record_type")
        if rtype not in KEEP:
            continue

        isos = []
        for name in (r.get("countries") or []):
            iso = name_to_iso.get(str(name).strip().lower())
            if iso:
                isos.append(iso)
            else:
                unmatched.add(str(name))

        points = []
        for p in (r.get("points") or []):
            coords = (p or {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            if lon == 0 and lat == 0:
                continue
            points.append([round(lon, 4), round(lat, 4)])

        # Five records arrive with latitude and longitude the wrong way round: a
        # Peruvian raft fishery and three Colombian university records plotted in
        # Antarctica, a Spanish lagoon in Kenya. A point outside its named country
        # whose swapped twin is inside it is swapped back.
        # The test is the country's bounding box, not its outline, so that a point at
        # sea or on a small island (San Andres, Colombia) still counts as inside. A
        # point that is nowhere near its one named country either way round is not
        # used, and the record falls back to the country centre, marked approximate.
        geom = country_shape.get(isos[0]) if len(isos) == 1 else None
        if geom:
            x0, y0, x1, y1 = bbox(geom)
            near = lambda lon, lat, m: x0 - m <= lon <= x1 + m and y0 - m <= lat <= y1 + m
            fixed = []
            for lon, lat in points:
                if near(lon, lat, 3.0):   # generous: Puerto Rico sits just outside the USA box
                    fixed.append([lon, lat])
                elif -90 <= lon <= 90 and near(lat, lon, 0.1):
                    fixed.append([lat, lon])
                    swapped[0] += 1
                else:
                    dropped_far[0] += 1
            points = fixed

        # A record whose scope is national, regional or global has no site by
        # definition, and ISSF stores a country centroid for it - eleven Nigerian
        # records all sit on exactly [8.0, 10.0], the middle of the country, and
        # one of them is a lagoon fishery on the coast. Those points arrive looking
        # like coordinates, so they have to be caught by scope rather than by
        # absence, or the map shows lagoon fisheries in the Sahara.
        scope = (r.get("geographic_scope_type") or "").strip().lower()
        approximate = scope in ("national", "regional", "global", "not specific")

        # Records with a country but no point at all fall back to the country
        # centroid, flagged the same way.
        if not points and isos:
            c = iso_point.get(isos[0])
            if c:
                points = [[round(float(c[0]), 4), round(float(c[1]), 4)]]
                approximate = True
                scope = scope or "not specific"
        if not points:
            continue

        date = (r.get("contribution_date") or "")[:10]
        year = date[:4]
        if year.isdigit():
            years[year] = years.get(year, 0) + 1

        rec = {
            "id": r.get("issf_core_id"),
            "kind": KEEP[rtype],
            "label": label_from_summary(r.get("core_record_summary"), rtype),
            "countries": list(dict.fromkeys(isos)),  # a record naming a country twice counts once
            "scope": r.get("geographic_scope_type"),
            "date": date,
            "points": points,
            "approx": approximate,
        }
        out.append(rec)
        for iso in rec["countries"]:
            by_country.setdefault(iso, {"profile": 0, "organization": 0,
                                        "blue_justice": 0, "case_study": 0})
            by_country[iso][rec["kind"]] += 1

    exact = sum(1 for r in out if not r["approx"])
    print(f"  swapped back {swapped[0]} points that had latitude and longitude reversed; "
          f"{dropped_far[0]} points nowhere near their country were not used")
    print(f"\n  kept {len(out)} mappable records ({exact} at a real site, "
          f"{len(out) - exact} national/regional records placed on a centroid)")
    counts = {}
    for r in out:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {k:<16}{v:>5}")
    print(f"  {len(by_country)} countries covered")
    if unmatched:
        print(f"  {len(unmatched)} country names unmatched, e.g. {sorted(unmatched)[:4]}")

    recent = sum(v for y, v in years.items() if y >= "2020")
    with open(os.path.join(OUT, "issf.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": ("Information System on Small-scale Fisheries (ISSF), "
                       "Too Big To Ignore: Global Partnership for Small-Scale "
                       "Fisheries Research, issfcloud.toobigtoignore.net"),
            "note": ("Crowdsourced and largely dormant: most records date from "
                     "2013-2016. Coverage reflects where contributing researchers "
                     "work, not where small-scale fishing is concentrated."),
            "contributions_by_year": dict(sorted(years.items())),
            "since_2020": recent,
            "count": len(out),
            "records": out,
            "by_country": by_country,
        }, f)

    print(f"\n  contribution years: {min(years)}–{max(years)}, "
          f"{recent} records since 2020 ({100*recent/max(1,len(out)):.0f}%)")
    top = sorted(by_country.items(), key=lambda kv: -sum(kv[1].values()))[:10]
    print("\n  most records:")
    for iso, c in top:
        print(f"    {iso}  profiles={c['profile']:>3}  orgs={c['organization']:>3}  "
              f"justice={c['blue_justice']:>2}")


if __name__ == "__main__":
    main()
