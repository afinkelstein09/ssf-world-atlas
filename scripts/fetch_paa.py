"""
Build the preferential access area layer.

Preferential access areas (PAAs) are nearshore waters that a government has
formally allocated to small-scale fishers - by excluding industrial vessels,
restricting gear, or reserving a band of coast outright. They are the closest
thing that exists to a map of small-scale fishing *rights*, as opposed to
small-scale fishing activity.

Source: DeLand, Vegh, Cleary, Basurto, Virdin & Halpin (2025), "A global dataset
of preferential access areas for small-scale fishing", Duke Research Data
Repository. https://doi.org/10.7924/r40s01h5j  — licensed CC0.
Paper: Basurto et al. (2024), npj Ocean Sustainability, doi:10.1038/s44183-024-00096-0

Two things make this awkward, and both are handled here:

  1. The data ships as a GeoPackage. With no geospatial libraries available we
     read it as the SQLite database it actually is and parse the WKB geometry by
     hand.
  2. The geometry is projected in Eckert IV (ESRI:54012), an equal-area
     projection in metres. Web maps need WGS84 degrees, so it is reprojected
     with the inverse Eckert IV formulas.

Outputs site/data/paa.geojson and site/data/paa.json.
"""

import json
import math
import os
import sqlite3
import struct
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPKG = os.path.join(HERE, "data", "raw", "paa", "paa.gpkg")
OUT = os.path.join(HERE, "site", "data")
TABLE = "PAA_v1_EckertIV"

# Eckert IV constants, spherical form. ESRI:54012 is defined on WGS84 but the
# projection itself is applied spherically, using the semi-major axis.
R = 6378137.0
CX = 2.0 / math.sqrt(4.0 * math.pi + math.pi ** 2)   # 0.42227
CY = 2.0 * math.sqrt(math.pi / (4.0 + math.pi))      # 1.32650


def eckert4_inverse(x, y):
    """Eckert IV (metres) -> (longitude, latitude) in degrees."""
    sin_theta = y / (CY * R)
    # Guard against floating point pushing us just outside asin's domain at the
    # poles, which would raise instead of returning +/-90.
    sin_theta = max(-1.0, min(1.0, sin_theta))
    theta = math.asin(sin_theta)
    cos_theta = math.cos(theta)

    denom = CX * R * (1.0 + cos_theta)
    lon = x / denom if denom != 0 else 0.0

    s = (theta + math.sin(theta) * cos_theta + 2.0 * math.sin(theta)) / (2.0 + math.pi / 2.0)
    s = max(-1.0, min(1.0, s))
    lat = math.asin(s)

    return math.degrees(lon), math.degrees(lat)


def parse_gpkg_geometry(blob):
    """
    Strip the GeoPackage binary header and return the WKB payload.

    Layout: magic 'GP', version, flags, srs_id, then an optional envelope whose
    size is encoded in bits 1-3 of the flags byte.
    """
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob")
    flags = blob[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_doubles = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope_code, 0)
    offset = 8 + envelope_doubles * 8
    return blob[offset:]


def decode_type(geom_type):
    """
    Return (base_type, coordinates_per_point) for a WKB type code.

    This file uses both conventions in the same geometry: the outer type is
    ISO-style (3006 = MultiPolygon ZM), while each inner polygon is EWKB-style
    (0xC0000003 = Polygon with the Z and M high bits set). Getting the dimension
    wrong reads 4-double points as 2-double points and the offsets run away
    into nonsense lengths, so both encodings are decoded explicitly.
    """
    if geom_type & 0x80000000 or geom_type & 0x40000000:  # EWKB high-bit flags
        has_z = bool(geom_type & 0x80000000)
        has_m = bool(geom_type & 0x40000000)
        base = geom_type & 0x0FFFFFFF
    else:  # ISO: +1000 for Z, +2000 for M, +3000 for both
        base = geom_type % 1000
        flag = geom_type // 1000
        has_z = flag in (1, 3)
        has_m = flag in (2, 3)
    return base, 2 + int(has_z) + int(has_m)


def parse_wkb(wkb):
    """Parse WKB Polygon / MultiPolygon into a list of polygons (list of rings).

    Z and M values are read and discarded - the atlas only needs x and y."""
    def read_polygon(buf, pos, endian, ndim):
        fmt = "<" if endian else ">"
        (n_rings,) = struct.unpack_from(fmt + "I", buf, pos)
        pos += 4
        rings = []
        for _ in range(n_rings):
            (n_pts,) = struct.unpack_from(fmt + "I", buf, pos)
            pos += 4
            coords = struct.unpack_from(fmt + f"{n_pts * ndim}d", buf, pos)
            pos += n_pts * ndim * 8
            rings.append([(coords[i], coords[i + 1]) for i in range(0, len(coords), ndim)])
        return rings, pos

    pos = 0
    endian = wkb[pos] == 1
    pos += 1
    fmt = "<" if endian else ">"
    (geom_type,) = struct.unpack_from(fmt + "I", wkb, pos)
    pos += 4
    base, ndim = decode_type(geom_type)

    if base == 3:  # Polygon
        rings, _ = read_polygon(wkb, pos, endian, ndim)
        return [rings]

    if base == 6:  # MultiPolygon
        (n_poly,) = struct.unpack_from(fmt + "I", wkb, pos)
        pos += 4
        polys = []
        for _ in range(n_poly):
            sub_endian = wkb[pos] == 1
            pos += 1
            sub_fmt = "<" if sub_endian else ">"
            (sub_type,) = struct.unpack_from(sub_fmt + "I", wkb, pos)
            pos += 4
            _, sub_ndim = decode_type(sub_type)
            rings, pos = read_polygon(wkb, pos, sub_endian, sub_ndim)
            polys.append(rings)
        return polys

    raise ValueError(f"unsupported geometry type {geom_type}")


# Duke's table carries Thailand's Royal Ordinance PDF (tha159730.pdf) as the link
# on Nigeria's row - an upstream slip. The instrument's name is kept; the link is
# dropped so the panel offers a FAOLEX search instead of the wrong document.
# Angola's link (checked 2026-10-06) opens Decreto 41/05, the 2005 General Fisheries
# Regulation, not the 2002 Executive Decree 13/02 the row names.
BAD_LAW_URLS = {"NGA": "tha159730", "AGO": "ang116916"}


def clean_law(iso, law):
    """One line of text, without a link known to point at another country's law."""
    if not law:
        return law
    words = str(law).split()
    bad = BAD_LAW_URLS.get(iso)
    if bad:
        words = [w for w in words if not (w.startswith("http") and bad in w)]
    # The dataset cites FAO's old document host, which stopped answering in 2026.
    # The same PDFs, under the same file names, are served from faolex.fao.org
    # (all six checked 2026-09-20), so the link is rewritten rather than dropped.
    words = [w.replace("http://extwprlegs1.fao.org/docs/pdf/", "https://faolex.fao.org/docs/pdf/")
              .replace("https://extwprlegs1.fao.org/docs/pdf/", "https://faolex.fao.org/docs/pdf/")
             if w.startswith("http") else w for w in words]
    return " ".join(words)


def simplify(points, tolerance):
    """
    Douglas-Peucker, iterative so deep coastlines don't blow the stack.

    The source traces real shorelines at full resolution; the whole file is 71 MB
    and no web map needs that. Tolerance is in degrees.
    """
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        norm = dx * dx + dy * dy

        worst, worst_i = 0.0, -1
        for i in range(start + 1, end):
            px, py = points[i]
            if norm == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / norm))
                d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
            if d > worst:
                worst, worst_i = d, i

        if worst > tolerance and worst_i > 0:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))

    return [p for p, k in zip(points, keep) if k]


def main():
    if not os.path.exists(GPKG):
        raise SystemExit(f"missing {GPKG} - download it first (see README)")
    os.makedirs(OUT, exist_ok=True)

    con = sqlite3.connect(GPKG)
    cur = con.cursor()
    fields = ["ISO_TER1", "Country", "Percent_EEZ", "Year_Enacted",
              "Boundary_Creation_Source", "Local_expert_review", "Designation_level",
              "Law_or_Regulation", "PAA_prohibits_or_excludes", "PAA_Definition",
              "PAA_Area_sqkm", "EEZ_Area_sqkm"]
    rows = cur.execute(f'SELECT Shape,{",".join(fields)} FROM "{TABLE}"').fetchall()

    features = []
    table = {}
    dropped_rings = 0
    total_in = total_out = 0

    for row in rows:
        blob, values = row[0], dict(zip(fields, row[1:]))
        polys = parse_wkb(parse_gpkg_geometry(blob))

        out_polys = []
        for rings in polys:
            out_rings = []
            for i, ring in enumerate(rings):
                is_hole = i > 0
                lonlat = [eckert4_inverse(x, y) for x, y in ring]
                total_in += len(lonlat)

                # Decide by how big the ring actually is, not by how many points
                # survive simplification. An archipelago's preferential access area
                # is mostly small rings; simplifying them out of existence would
                # quietly delete real policy coverage in exactly the countries where
                # small-scale fishing matters most. But a ring a few hundred metres
                # across can never be seen at any zoom this map allows, so carrying
                # its vertices is pure weight.
                #
                # Holes get a coarser limit. A hole is an island inside the coastal
                # band, and Greenland's band has three thousand of them; the map
                # renderer's triangulation gave up on that many and filled the whole
                # island green. Below about five kilometres an island is invisible
                # at this map's maximum zoom, and the basemap draws it anyway.
                xs = [p[0] for p in lonlat]
                ys = [p[1] for p in lonlat]
                extent = max(max(xs) - min(xs), max(ys) - min(ys))
                if extent < (0.05 if is_hole else 0.01):
                    dropped_rings += 1
                    if not is_hole:
                        out_rings = None  # no outer ring, so no polygon
                        break
                    continue

                thin = simplify(lonlat, 0.01)
                if len(thin) < 4:
                    step = max(1, len(lonlat) // 6)
                    thin = lonlat[::step]
                    if len(thin) < 4:
                        dropped_rings += 1
                        if not is_hole:
                            out_rings = None
                            break
                        continue
                if thin[0] != thin[-1]:
                    thin.append(thin[0])
                total_out += len(thin)
                out_rings.append([[round(lon, 4), round(lat, 4)] for lon, lat in thin])
            if out_rings:
                out_polys.append(out_rings)

        if not out_polys:
            continue

        iso = values["ISO_TER1"]
        props = {
            "iso3": iso,
            "country": values["Country"],
            "percent_eez": round(values["Percent_EEZ"], 2) if values["Percent_EEZ"] is not None else None,
            "year": int(values["Year_Enacted"]) if values["Year_Enacted"] else None,
            "area_km2": round(values["PAA_Area_sqkm"]) if values["PAA_Area_sqkm"] else None,
            "level": values["Designation_level"],
            "expert_reviewed": values["Local_expert_review"] == "Yes",
            "boundary_source": values["Boundary_Creation_Source"],
            "excludes": values["PAA_prohibits_or_excludes"],
            "definition": values["PAA_Definition"],
            "law": clean_law(iso, values["Law_or_Regulation"]),
        }

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "MultiPolygon", "coordinates": out_polys},
        })
        table[iso] = props

    geo = {"type": "FeatureCollection", "features": features}
    geo_path = os.path.join(OUT, "paa.geojson")
    with open(geo_path, "w") as f:
        json.dump(geo, f)

    with open(os.path.join(OUT, "paa.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": ("DeLand et al. (2025), A global dataset of preferential access "
                       "areas for small-scale fishing, Duke Research Data Repository"),
            "doi": "10.7924/r40s01h5j",
            "paper_doi": "10.1038/s44183-024-00096-0",
            "license": "CC0",
            "count": len(table),
            "countries": table,
        }, f, indent=1)

    size = os.path.getsize(geo_path) / 1e6
    print(f"  {len(features)} countries with preferential access areas")
    print(f"  vertices {total_in:,} -> {total_out:,} after simplification")
    if dropped_rings:
        print(f"  {dropped_rings} slivers dropped as too small to draw")
    print(f"  wrote paa.geojson ({size:.1f} MB)")

    reviewed = sum(1 for p in table.values() if p["expert_reviewed"])
    print(f"  {reviewed}/{len(table)} boundaries reviewed by a local expert")
    top = sorted(table.values(), key=lambda p: -(p["percent_eez"] or 0))[:6]
    print("\n  largest share of EEZ reserved for small-scale fishers:")
    for p in top:
        print(f"    {str(p['country'])[:26]:<26} {p['percent_eez']:5.1f}%  since {p['year']}")


if __name__ == "__main__":
    main()
