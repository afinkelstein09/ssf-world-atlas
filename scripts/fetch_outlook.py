"""
Build the outlook layer: what is the ocean forecast to do over the coming year?

Two NOAA forecasts, both stated as chances rather than predictions:

  ENSO odds       NOAA CPC's official chances of El Nino, neutral or La Nina for
                  the next nine overlapping 3-month seasons, and the chances of each
                  strength category (weak to very strong). One set of numbers for the
                  whole tropical Pacific, issued on the second Thursday of each month.
  Heatwave odds   NOAA PSL's forecast chance that each 1-degree patch of ocean is in
                  a marine heatwave in each of the next 12 months. This script turns
                  the grid into one number per ocean zone per month.

Why the heatwave forecast is read from the "with trend" file and not the detrended
one. The atlas's current heatwave layer (fetch_climate.py) is NOAA Coral Reef Watch,
which compares today's sea with a fixed climatology, so long-term warming counts as
heat. The forecast has to ask the same question or the two layers would disagree for
reasons no reader could see. The detrended file asks a different question ("hot even
for today's warmer ocean") and mostly gives lower odds: in the September 2026
forecast it was lower in 72-93% of ocean cells depending on the month ahead, higher
in 5-12%. Jacox et al. use the detrended version in their paper's main text; PSL
publishes both.

How the forecast grid is read without downloading it. PSL's file holds every
forecast since 2021 (265 MB). The newest month is 3 MB of it. PSL's THREDDS server
can cut that month out, but two of its three routes are broken for this file:
OPeNDAP 2 refuses the whole file because one variable is a 64-bit integer, and the
NetCDF Subset Service misreads the order of the dimensions. The third route, DAP4,
works. Its binary format is simple enough to read with the standard library, and it
carries a checksum for every variable, which is checked - and which earned its
keep at once: on 11 October 2026 every answer longer than 65,535 bytes came back
with everything after that point scrambled, though the length was right and the
checksum (computed by the server on the true values) gave it away. So the grid is
asked for in about 60 pieces that each fit under that size, one second apart.

Outputs site/data/outlook.json. Raw responses are kept in data/raw/outlook/ so every
number can be re-derived from what NOAA actually sent.

Sources:
  https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/
  https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/strengths/
      NOAA Climate Prediction Center, US Government work, public domain
  https://psl.noaa.gov/marine-heatwaves/
  https://downloads.psl.noaa.gov/Datasets/marinehw/NMME_prob90_latest.nc
      NOAA Physical Sciences Laboratory, US Government work, public domain.
      Method: Jacox et al. 2022, "Global seasonal forecasts of marine heatwaves",
      Nature 604, 486-490, https://doi.org/10.1038/s41586-022-04573-9
  https://www.weather.gov/media/notification/pdf_2026/pns26-05_Relative_ONI.pdf
      NWS Public Information Statement 26-05: the Relative Oceanic Nino Index (RONI)
      became NOAA's official ENSO index on 1 February 2026.

Standard library only. Takes about two minutes, most of it waiting politely
between requests to PSL.

    python3 scripts/fetch_outlook.py
"""

import json
import math
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from array import array
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from html.parser import HTMLParser

from fetch_climate import _edge_distance, get_text

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "site", "data")
RAW = os.path.join(HERE, "data", "raw", "outlook")

CPC_ODDS = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/"
CPC_STRENGTH = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/strengths/"
RONI_PAGE = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/"
RONI_NOTICE = "https://www.weather.gov/media/notification/pdf_2026/pns26-05_Relative_ONI.pdf"

PSL_FILE = "https://downloads.psl.noaa.gov/Datasets/marinehw/NMME_prob90_latest.nc"
PSL_DAP4 = "https://psl.noaa.gov/thredds/dap4/Datasets/marinehw/NMME_prob90_latest.nc"
PSL_PAGE = "https://psl.noaa.gov/marine-heatwaves/"
PSL_METHOD = "https://doi.org/10.1038/s41586-022-04573-9"
PSL_VAR = "mhw_probability"

# PSL's DAP4 server sends data in chunks of at most 65,535 bytes, and on 11 October
# 2026 anything that spilled into a second chunk came back corrupted (see above).
# Each request is kept to one chunk: values plus their 4-byte checksum.
DAP4_SAFE_BYTES = 65535

# A zone with no ocean cell centre inside it borrows the ocean cells its outline
# touches, and failing that the nearest ocean cell - but only within this many
# degrees (about 165 km). Further than that, the number would describe someone
# else's water, so the zone is listed as missing instead.
NEAREST_MAX_DEG = 1.5

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
LETTERS = "JFMAMJJASOND"


def ym(year, month):
    """(2026, 13) -> '2027-01'. Months past 12 roll into the next year."""
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return f"{year:04d}-{month:02d}"


def get_bytes(url, tries=5, timeout=120):
    """
    Like get_text, but returns bytes and is patient with PSL. PSL's server answers
    "429 Too Many Requests" to a second request that comes too soon, so a 429 is
    waited out rather than treated as a failure. Any other 4xx means the request
    itself is wrong, and asking again will not help.
    """
    for attempt in range(tries):
        wait = 3 * (attempt + 1)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = max(wait, int(e.headers.get("Retry-After") or 0), 10 * (attempt + 1))
            elif e.code < 500:
                body = e.read()[:300].decode("utf-8", errors="replace")
                print(f"  ! HTTP {e.code} for {url[:120]}\n    {body.strip()}")
                return None
        except Exception:
            pass
        if attempt < tries - 1:
            time.sleep(wait)
    return None


def save_raw(name, content):
    path = os.path.join(RAW, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, bytes):
        with open(path, "wb") as f:
            f.write(content)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# Part B: CPC's official ENSO probabilities
# ---------------------------------------------------------------------------

class _CpcPage(HTMLParser):
    """
    Collects the "Issued ..." heading and the rows of the table with
    id="probabilities-table". HTMLParser skips comments, which matters: the
    strengths page keeps an old "Issued April 2026" heading inside a comment.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings, self.rows = [], []
        self._table = False
        self._row = self._cell = self._h2 = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == "probabilities-table":
            self._table = True
        elif self._table and tag == "tr":
            self._row = []
        elif self._table and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "h2":
            self._h2 = []

    def handle_endtag(self, tag):
        if tag == "table":
            self._table = False
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "h2" and self._h2 is not None:
            self.headings.append(" ".join("".join(self._h2).split()))
            self._h2 = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._h2 is not None:
            self._h2.append(data)


def _cpc_page(url, raw_name):
    """Fetch one CPC page; return (issued as printed, 'YYYY-MM', header, rows)."""
    page = get_text(url)
    if not page:
        raise ValueError("the page did not answer")
    save_raw(raw_name, page)
    p = _CpcPage()
    p.feed(page)
    issued = None
    for h in p.headings:
        m = re.match(r"Issued\s+([A-Z][a-z]+)\s+(\d{4})$", h)
        if m and m.group(1) in MONTH_NAMES:
            issued = (f"{m.group(1)} {m.group(2)}",
                      ym(int(m.group(2)), MONTH_NAMES.index(m.group(1)) + 1))
            break
    if not issued:
        raise ValueError("no 'Issued <Month> <Year>' heading")
    if len(p.rows) < 2:
        raise ValueError("the probabilities table is missing or empty")
    return issued[0], issued[1], p.rows[0], p.rows[1:]


def _seasons(rows, issued_month):
    """
    Turn the table's season cells ("SON Sep Oct Nov" - the code plus its tooltip)
    into dated seasons. CPC prints no years, so they are worked out: the first
    season is the one starting nearest the issue month, and each row after it starts
    one month later. Labels follow CPC's ONI table, where a season takes the year of
    its middle month (NDJ 2026 = Nov 2026 to Jan 2027; DJF 2027 = Dec 2026 to Feb 2027).
    """
    iy, im = int(issued_month[:4]), int(issued_month[5:])
    out = []
    start = None
    for row in rows:
        words = row[0].split()
        code = words[0] if words else ""
        if len(code) != 3 or code not in (LETTERS + LETTERS[:2]):
            raise ValueError(f"unexpected season cell {row[0]!r}")
        first = (LETTERS + LETTERS[:2]).index(code) + 1           # 1..12
        # The tooltip spells the months out; if it is there it must agree.
        named = [w for w in words[1:] if w in MONTHS]
        if named and named != [MONTHS[(first - 1 + k) % 12] for k in range(3)]:
            raise ValueError(f"season {code} has months {named}")
        if start is None:
            years = [iy - 1, iy, iy + 1]
            y = min(years, key=lambda yy: abs((yy * 12 + first) - (iy * 12 + im)))
            start = y * 12 + (first - 1)
        else:
            start += 1
            if start % 12 != first - 1:
                raise ValueError(f"season {code} does not follow the row before it")
        months = [ym(start // 12, start % 12 + 1 + k) for k in range(3)]
        out.append({"season": f"{code} {months[1][:4]}", "months": months})
    return out


def _pct(cell):
    if not re.fullmatch(r"\d{1,3}", cell or ""):
        raise ValueError(f"not a percentage: {cell!r}")
    v = int(cell)
    if v > 100:
        raise ValueError(f"percentage over 100: {v}")
    return v


def enso_odds():
    """CPC's chances of La Nina / neutral / El Nino, season by season."""
    issued, month, header, rows = _cpc_page(CPC_ODDS, "cpc_enso_probabilities.html")
    # Columns are found by their headings, not their position.
    cols = {}
    for k, h in enumerate(header):
        h = h.lower().replace("ñ", "n")
        if h.startswith("la nin"):
            cols["la_nina"] = k
        elif h.startswith("neutral"):
            cols["neutral"] = k
        elif h.startswith("el nin"):
            cols["el_nino"] = k
    if len(cols) != 3:
        raise ValueError(f"unexpected table headings {header}")
    seasons = _seasons(rows, month)
    for s, row in zip(seasons, rows):
        for key, k in cols.items():
            s[key] = _pct(row[k])
        # The three chances should add to 100; CPC rounds, so allow a point either way.
        if abs(s["la_nina"] + s["neutral"] + s["el_nino"] - 100) > 1:
            raise ValueError(f"{s['season']} adds to {s['la_nina'] + s['neutral'] + s['el_nino']}")
    return {
        "source": "NOAA Climate Prediction Center, official ENSO probabilities",
        "url": CPC_ODDS,
        "issued": issued,
        "issued_month": month,
        "fetched": time.strftime("%Y-%m-%d"),
        "index": "RONI",
        "index_url": RONI_PAGE,
        "index_notice": RONI_NOTICE,
        "index_official_since": "2026-02-01",
        "definition": ("El Nino: RONI at or above +0.5 C; La Nina: at or below -0.5 C. RONI is the "
                       "3-month mean sea surface temperature anomaly in the Nino-3.4 region "
                       "(5N-5S, 170W-120W) minus the tropical-mean anomaly (20N-20S), rescaled; "
                       "1991-2020 base period."),
        "note": "CPC: a 0% chance is approximate - there is still a small, non-zero chance.",
        "seasons": seasons,
    }


# The strength table's columns are headed by threshold expressions. Each is parsed
# into numeric bounds and named from those bounds, so a reordered or reworded table
# is either read correctly or rejected - never silently mislabelled.
STRENGTH_NAMES = {
    (None, -2.0): "la_nina_very_strong",
    (-2.0, -1.5): "la_nina_strong",
    (-1.5, -1.0): "la_nina_moderate",
    (-1.0, -0.5): "la_nina_weak",
    (-0.5, 0.5): "neutral",
    (0.5, 1.0): "el_nino_weak",
    (1.0, 1.5): "el_nino_moderate",
    (1.5, 2.0): "el_nino_strong",
    (2.0, None): "el_nino_very_strong",
}
_NUM = r"([-+]?\d+(?:\.\d+)?)"
_OP = r"(<=|>=|<|>|≤|≥)"


def _bounds(header):
    """'-1.5°C ≥ Index > -2.0°C' -> (-2.0, -1.5). Returns (lower, upper)."""
    # CPC writes one minus sign as U+2212 ("−0.5°C < Index < 0.5°C") and the rest as "-".
    h = header.replace("\u2212", "-").replace("°C", "").replace("°", "")
    m = re.fullmatch(rf"\s*(?:{_NUM}\s*{_OP}\s*)?Index\s*(?:{_OP}\s*{_NUM})?\s*", h)
    if not m or (m.group(1) is None and m.group(4) is None):
        raise ValueError(f"cannot read strength heading {header!r}")
    lo = hi = None
    if m.group(1) is not None:                 # "A op Index"
        a = float(m.group(1))
        if m.group(2) in ("<", "<=", "≤"):
            lo = a
        else:
            hi = a
    if m.group(4) is not None:                 # "Index op B"
        b = float(m.group(4))
        if m.group(3) in ("<", "<=", "≤"):
            hi = b
        else:
            lo = b
    return lo, hi


def enso_strength(odds):
    """CPC's chances of each El Nino / La Nina strength category, season by season."""
    issued, month, header, rows = _cpc_page(CPC_STRENGTH, "cpc_enso_strengths.html")
    cols, categories = {}, {}
    for k, h in enumerate(header[1:], 1):
        name = STRENGTH_NAMES.get(_bounds(h))
        if not name or name in cols:
            raise ValueError(f"unexpected strength heading {h!r}")
        cols[name] = k
        categories[name] = h          # exactly as CPC prints it; "Index" is the RONI, in C
    if len(cols) != len(STRENGTH_NAMES):
        raise ValueError(f"expected {len(STRENGTH_NAMES)} strength columns, got {len(cols)}")
    seasons = _seasons(rows, month)
    for s, row in zip(seasons, rows):
        for name in STRENGTH_NAMES.values():   # weakest La Nina ... strongest El Nino
            s[name] = _pct(row[cols[name]])
        total = sum(s[n] for n in STRENGTH_NAMES.values())
        if abs(total - 100) > 1:
            raise ValueError(f"{s['season']} adds to {total}")

    # The two pages are the same forecast cut two ways, so the categories should add
    # up to the El Nino / La Nina chances on the other page. Checked, and recorded.
    agree = None
    if odds and odds.get("issued_month") == month:
        by_season = {s["season"]: s for s in odds["seasons"]}
        agree = True
        for s in seasons:
            o = by_season.get(s["season"])
            if not o:
                agree = False
                continue
            el = sum(v for n, v in s.items() if n.startswith("el_nino_"))
            la = sum(v for n, v in s.items() if n.startswith("la_nina_"))
            if abs(el - o["el_nino"]) > 1 or abs(la - o["la_nina"]) > 1 or abs(s["neutral"] - o["neutral"]) > 1:
                print(f"  ! {s['season']}: strengths add to El Nino {el}, La Nina {la}; "
                      f"the probabilities page says {o['el_nino']}, {o['la_nina']}")
                agree = False
    return {
        "source": "NOAA Climate Prediction Center, official ENSO strength probabilities",
        "url": CPC_STRENGTH,
        "issued": issued,
        "issued_month": month,
        "fetched": time.strftime("%Y-%m-%d"),
        "index": "RONI",
        "categories": categories,
        "category_note": ("'Index' is the Relative Oceanic Nino Index (RONI), a 3-month mean in "
                          "degrees C. CPC names the bands weak, moderate, strong and very strong, "
                          "in 0.5 C steps. CPC: strength does not necessarily match the strength "
                          "of the impact."),
        "matches_odds": agree,
        "seasons": seasons,
    }


# ---------------------------------------------------------------------------
# Part A: PSL's marine heatwave forecast, per ocean zone
# ---------------------------------------------------------------------------

_DAP4_NS = "{http://xml.opendap.org/ns/DAP/4.0#}"
_DAP4_TYPES = {  # DAP4 type -> (array typecode, bytes)
    "Float32": ("f", 4), "Float64": ("d", 8), "Int8": ("b", 1), "UInt8": ("B", 1),
    "Int16": ("h", 2), "UInt16": ("H", 2), "Int32": ("i", 4), "UInt32": ("I", 4),
    "Int64": ("q", 8), "UInt64": ("Q", 8),
}


def _dmr(xml_bytes):
    """
    Read DAP4 metadata (the "DMR", an XML document): the size of each dimension,
    and each variable's type, shape, dimension names and attributes - in document
    order, which is the order the values arrive in.
    """
    root = ET.fromstring(xml_bytes)
    dims = {"/" + d.get("name"): int(d.get("size")) for d in root.findall(_DAP4_NS + "Dimension")}
    out = {"dims": dims, "vars": [], "attrs": {}}
    for el in root:
        tag = el.tag.replace(_DAP4_NS, "")
        if tag == "Attribute":
            out["attrs"][el.get("name")] = [v.get("value") for v in el.findall(_DAP4_NS + "Value")]
        elif tag in _DAP4_TYPES:
            shape, names = [], []
            for d in el.findall(_DAP4_NS + "Dim"):
                if d.get("size") is not None:       # a subset: the dimension is anonymous
                    shape.append(int(d.get("size")))
                    names.append(None)
                else:
                    shape.append(dims[d.get("name")])
                    names.append(d.get("name"))
            attrs = {a.get("name"): [v.get("value") for v in a.findall(_DAP4_NS + "Value")]
                     for a in el.findall(_DAP4_NS + "Attribute")}
            out["vars"].append({"name": el.get("name"), "type": tag, "shape": shape,
                                "dims": names, "attrs": attrs})
    return out


def dap4_get(base, ce):
    """
    Ask a THREDDS DAP4 server for the variables (and index ranges) in `ce`.

    The answer is a run of chunks. Each starts with 4 bytes: one of flags
    (1 = last chunk, 2 = error, 4 = little-endian) and three of length. The first
    chunk is the DMR describing what follows; the rest, joined, is the values of
    each variable in turn, each followed by a CRC-32 checksum of its bytes.
    Returns ({name: array of values}, dmr, raw bytes).
    """
    url = base + ".dap?dap4.ce=" + urllib.parse.quote(ce, safe="/;:")
    raw = get_bytes(url)
    if not raw:
        raise ValueError("PSL's server did not answer")
    chunks, pos = [], 0
    while pos + 4 <= len(raw):
        head = struct.unpack(">I", raw[pos:pos + 4])[0]
        flags, n = head >> 24, head & 0xFFFFFF
        body = raw[pos + 4:pos + 4 + n]
        if flags & 2:
            raise ValueError("server error: " + body[:300].decode("utf-8", errors="replace"))
        chunks.append(body)
        pos += 4 + n
        if flags & 1:
            break
    if len(chunks) < 2:
        raise ValueError("the answer has no data")
    meta = _dmr(chunks[0])
    data = b"".join(chunks[1:])
    little = (meta["attrs"].get("_DAP4_Little_Endian") or ["1"])[0] == "1"
    sizes = []
    for v in meta["vars"]:
        n = 1
        for s in v["shape"]:
            n *= s
        sizes.append(n * _DAP4_TYPES[v["type"]][1])
    with_crc = len(data) == sum(sizes) + 4 * len(sizes)
    if not with_crc and len(data) != sum(sizes):
        raise ValueError(f"expected {sum(sizes)} bytes of values, got {len(data)}")
    values, pos = {}, 0
    for v, size in zip(meta["vars"], sizes):
        block = data[pos:pos + size]
        pos += size
        if with_crc:
            want = struct.unpack("<I" if little else ">I", data[pos:pos + 4])[0]
            pos += 4
            if zlib.crc32(block) != want:
                raise ValueError(f"checksum mismatch in {v['name']}: the download is damaged")
        code, width = _DAP4_TYPES[v["type"]]
        arr = array(code)
        if arr.itemsize != width:
            raise ValueError(f"this Python's {code!r} is {arr.itemsize} bytes, not {width}")
        arr.frombytes(block)
        if little != (sys.byteorder == "little"):
            arr.byteswap()
        values[v["name"]] = arr
    return values, meta, raw


# How close counts as "on" an edge, in degrees (about 0.1 mm).
EDGE_EPS = 1e-9


def _crossings(ring, row_ys):
    """
    For each grid row (a latitude): the longitudes where the ring's edges cross
    it, and the stretches of the row the ring runs along (flat edges, and corners
    that sit exactly on the row, as zero-length stretches).

    Same crossing rule as fetch_climate._inside(), turned around: instead of
    testing each cell against every edge, each edge is visited once and dropped
    into the rows it spans. A cell centre is then inside the ring when an odd
    number of crossings lie east of it. Over 145,000 vertices and 65,000 cells
    this takes about a second instead of minutes.
    """
    cross, along = {}, {}
    n = len(ring)
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[i - 1][0], ring[i - 1][1]
        k = bisect_left(row_ys, yi)
        if k < len(row_ys) and row_ys[k] == yi:
            along.setdefault(yi, []).append((xi, xi))
        if yi == yj:
            if k < len(row_ys) and row_ys[k] == yi:
                along[yi].append((min(xi, xj), max(xi, xj)))
            continue
        lo, hi = (yi, yj) if yi < yj else (yj, yi)
        # (yi > y) != (yj > y) holds exactly for lo <= y < hi
        for k in range(bisect_left(row_ys, lo), bisect_left(row_ys, hi)):
            y = row_ys[k]
            cross.setdefault(y, []).append((xj - xi) * (y - yi) / (yj - yi) + xi)
    for xs in cross.values():
        xs.sort()
    return cross, along


def _odd_east(xs, x):
    """True when an odd number of crossings lie strictly east of x (x < crossing)."""
    return bool(xs) and (len(xs) - bisect_right(xs, x)) % 2 == 1


def _on_edge(xs, stretches, x):
    """True when x is on the ring: at a crossing, or on a stretch the ring runs along."""
    if xs:
        k = bisect_left(xs, x - EDGE_EPS)
        if k < len(xs) and xs[k] <= x + EDGE_EPS:
            return True
    return any(a - EDGE_EPS <= x <= b + EDGE_EPS for a, b in stretches or ())


def _polys(geometry):
    t = geometry.get("type")
    if t == "Polygon":
        return [geometry["coordinates"]]
    if t == "MultiPolygon":
        return geometry["coordinates"]
    return []


def _bbox(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), max(xs), min(ys), max(ys)


def cells_inside(geometry, lats, cols):
    """
    Grid cells (row, column) whose centres fall inside the zone, holes (land)
    excluded. `lats` is the grid's latitudes in ascending order; `cols` is
    (longitude, column) pairs sorted by longitude, in -180..180.

    A centre exactly on the zone's edge counts as inside. Many sea boundaries run
    along whole degrees, right through cell centres, and so does the date line
    where zones like Fiji's are cut in two. Counting edge cells for every zone that
    touches them is the only choice that is the same for both neighbours, and it
    keeps the result reproducible with standard tools (shapely's "covers").
    """
    row_of = {y: i for i, y in enumerate(lats)}
    found = set()
    for poly in _polys(geometry):
        outer, holes = poly[0], poly[1:]
        x0, x1, y0, y1 = _bbox(outer)
        rows = [y for y in lats if y0 <= y <= y1]
        if not rows:
            continue
        outer_x, outer_along = _crossings(outer, rows)
        hole_x = []
        for h in holes:
            hx0, hx1, hy0, hy1 = _bbox(h)
            if hy1 >= y0 and hy0 <= y1:
                hole_x.append(_crossings(h, [y for y in rows if hy0 <= y <= hy1]))
        for y in rows:
            xs, along = outer_x.get(y), outer_along.get(y)
            ends = (xs or []) + [v for st in (along or []) for v in st]
            if not ends:
                continue
            i = row_of[y]
            lo_x, hi_x = min(ends) - EDGE_EPS, max(ends) + EDGE_EPS
            for k in range(bisect_left(cols, (lo_x,)), bisect_right(cols, (hi_x, 10 ** 9))):
                x, j = cols[k]
                if not (_odd_east(xs, x) or _on_edge(xs, along, x)):
                    continue
                # Out only if strictly inside a hole; a centre on the coastline stays.
                if any(_odd_east(hx.get(y), x) and not _on_edge(hx.get(y), ha.get(y), x)
                       for hx, ha in hole_x):
                    continue
                found.add((i, j))
    return found


def _segment_hits_box(ax, ay, bx, by, x0, x1, y0, y1):
    """Does the segment a-b touch the box? (Liang-Barsky clipping.)"""
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return True


def cells_near(geometry, ocean, lat_of, lon_of, half):
    """
    For a zone with no ocean cell centre inside it: first the ocean cells whose
    square the zone's outline passes through, else the nearest ocean cell(s)
    within NEAREST_MAX_DEG. Returns (cells, how).
    """
    rings = [r for poly in _polys(geometry) for r in poly]
    boxes = [_bbox(r) for r in rings]
    x0 = min(b[0] for b in boxes)
    x1 = max(b[1] for b in boxes)
    y0 = min(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)

    touching = set()
    for (i, j) in ocean:
        cx, cy = lon_of[j], lat_of[i]
        if not (x0 - half <= cx <= x1 + half and y0 - half <= cy <= y1 + half):
            continue
        bx0, bx1, by0, by1 = cx - half, cx + half, cy - half, cy + half
        for r, (rx0, rx1, ry0, ry1) in zip(rings, boxes):
            if rx1 < bx0 or rx0 > bx1 or ry1 < by0 or ry0 > by1:
                continue
            if any(_segment_hits_box(r[k - 1][0], r[k - 1][1], r[k][0], r[k][1], bx0, bx1, by0, by1)
                   for k in range(1, len(r))):
                touching.add((i, j))
                break
    if touching:
        return touching, "overlap"

    best, near = None, set()
    for (i, j) in ocean:
        cx, cy = lon_of[j], lat_of[i]
        if not (x0 - NEAREST_MAX_DEG <= cx <= x1 + NEAREST_MAX_DEG
                and y0 - NEAREST_MAX_DEG <= cy <= y1 + NEAREST_MAX_DEG):
            continue
        d = min(_edge_distance(r, cx, cy) for r in rings)
        if d > NEAREST_MAX_DEG:
            continue
        if best is None or d < best - 1e-9:
            best, near = d, {(i, j)}
        elif abs(d - best) <= 1e-9:
            near.add((i, j))
    return near, ("nearest" if near else None)


def mhw_forecast():
    """PSL's newest marine heatwave forecast, as one series per ocean zone."""
    # 1. What is in the file: dimension sizes, the variable's dimension order.
    raw_dmr = get_bytes(PSL_DAP4 + ".dmr")
    if not raw_dmr:
        raise ValueError("PSL's server did not answer")
    meta = _dmr(raw_dmr)
    var = next((v for v in meta["vars"] if v["name"] == PSL_VAR), None)
    want = {"/lead_time", "/lat", "/lon", "/start_time"}
    if not var or set(var["dims"]) != want:
        raise ValueError(f"{PSL_VAR} is missing or no longer has dimensions {sorted(want)}")
    n_init = meta["dims"]["/start_time"]

    # 2. The coordinates: when each forecast started, the leads, the grid.
    time.sleep(1)  # PSL rate-limits back-to-back requests
    vals, meta2, raw = dap4_get(PSL_DAP4, "/start_time;/lead_time;/lat;/lon")

    # 3. When the newest forecast was started. Stored as days since a base date.
    units = (next(v for v in meta2["vars"] if v["name"] == "start_time")["attrs"].get("units") or [""])[0]
    m = re.match(r"days since (\d{4})-(\d{2})-(\d{2})", units)
    if not m:
        raise ValueError(f"start_time has units {units!r}")
    if len(vals["start_time"]) != n_init:
        raise ValueError("start_time changed length between two requests")
    init = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) + timedelta(days=int(vals["start_time"][-1]))
    if init.day != 1:
        raise ValueError(f"newest forecast starts on {init}, not the 1st of a month")
    init_ym = ym(init.year, init.month)
    rawdir = f"psl_mhw_prob90_{init_ym}"
    save_raw("psl_mhw_prob90_latest.dmr.xml", raw_dmr)
    save_raw(f"{rawdir}/coordinates.dap", raw)

    # 4. Leads are 0.5, 1.5 ... 11.5 months: the first is the month the forecast
    # starts in (PSL and Jacox et al.: a 1 June start's 0.5-month lead is June).
    leads = [float(x) for x in vals["lead_time"]]
    if any(abs(L - (math.floor(L) + 0.5)) > 1e-6 for L in leads):
        raise ValueError(f"unexpected lead times {leads}")
    months = [ym(init.year, init.month + int(math.floor(L))) for L in leads]
    lats = [float(x) for x in vals["lat"]]
    lons = [float(x) for x in vals["lon"]]
    nlat, nlon = len(lats), len(lons)

    # 5. The newest forecast only (the last start_time), every lead, the whole globe,
    # one lead and a band of latitudes at a time so each answer fits in one chunk.
    width = _DAP4_TYPES[var["type"]][1]           # 4 bytes today (Float32)
    rows_per = (DAP4_SAFE_BYTES - 4) // (width * nlon)
    if rows_per < 1:
        raise ValueError("a single row of the grid is too big to fetch safely")
    grid = [array("d", [float("nan")]) * (nlat * nlon) for _ in leads]
    for k in range(len(leads)):
        for r0 in range(0, nlat, rows_per):
            r1 = min(nlat, r0 + rows_per) - 1
            pick = {"/lead_time": f"[{k}]", "/lat": f"[{r0}:{r1}]",
                    "/lon": f"[0:{nlon - 1}]", "/start_time": f"[{n_init - 1}]"}
            ce = f"/{PSL_VAR}" + "".join(pick[d] for d in var["dims"])
            for attempt in range(3):
                time.sleep(1)
                try:
                    got, _, raw = dap4_get(PSL_DAP4, ce)
                    break
                except ValueError as e:
                    if attempt == 2:
                        raise ValueError(f"{ce}: {e}")
            save_raw(f"{rawdir}/lead{k:02d}_lat{r0:03d}-{r1:03d}.dap", raw)
            # Within the piece, values run in the variable's own dimension order;
            # lead and start_time have length 1 here, so only lat and lon move.
            piece = got[PSL_VAR]
            if len(piece) != (r1 - r0 + 1) * nlon:
                raise ValueError(f"{ce}: expected {(r1 - r0 + 1) * nlon} values, got {len(piece)}")
            lon_first = var["dims"].index("/lon") < var["dims"].index("/lat")
            for a in range(r1 - r0 + 1):
                for j in range(nlon):
                    v = piece[j * (r1 - r0 + 1) + a] if lon_first else piece[a * nlon + j]
                    grid[k][(r0 + a) * nlon + j] = v

    # A value is data only if it is a number between 0 and 1. NaN marks land and sea
    # ice. Anything else would be a fill value nobody told us about.
    series, odd = {}, 0
    for i in range(nlat):
        for j in range(nlon):
            row = []
            for k in range(len(leads)):
                v = grid[k][i * nlon + j]
                if v != v:
                    row.append(None)
                elif 0.0 <= v <= 1.0:
                    row.append(v)
                else:
                    row.append(None)
                    odd += 1
            if any(v is not None for v in row):
                series[(i, j)] = row
    if odd:
        print(f"  ! {odd} values outside 0-1 were treated as blank")
    if len(series) < 30000 or odd > 100:
        raise ValueError(f"only {len(series)} ocean cells ({odd} odd values): not trusting this grid")

    def cell(lat, lon):
        i = min(range(len(lats)), key=lambda a: abs(lats[a] - lat))
        j = min(range(len(lons)), key=lambda b: abs(lons[b] - lon % 360))
        return series.get((i, j))

    print(f"  newest forecast starts {init_ym}; {len(leads)} leads {months[0]} to {months[-1]}; "
          f"{len(series)} ocean cells")
    for label, lat, lon in (("9N 120E (Tubbataha)", 9, 120), ("12S 78W (Peru)", -12, -78)):
        s = cell(lat, lon)
        print(f"  cell {label}: " + " ".join("--" if v is None else f"{v:.2f}" for v in (s or [])))

    # 6. Per zone. Longitudes go to -180..180 to match the zone outlines. The column
    # on the date line is listed at both -180 and +180, because the zones that cross
    # it are cut in two there and either half may hold the cell.
    if lats != sorted(lats):
        raise ValueError("latitudes are not in ascending order")
    lon_of = {j: (x - 360 if x >= 180 else x) for j, x in enumerate(lons)}
    cols = sorted((x, j) for j, x in lon_of.items())
    cols += [(180.0, j) for j, x in lon_of.items() if x == -180.0]
    cols.sort()
    lat_of = dict(enumerate(lats))
    half = abs(lats[1] - lats[0]) / 2
    weight = {i: math.cos(math.radians(y)) for i, y in enumerate(lats)}
    ocean = set(series)

    with open(os.path.join(OUT, "eez.geojson")) as f:
        feats = json.load(f)["features"]

    zones, missing, approx = {}, [], []
    for feat in feats:
        name = feat["properties"]["name"]
        geom = feat["geometry"]
        use = cells_inside(geom, lats, cols) & ocean
        how = None
        if not use:
            use, how = cells_near(geom, ocean, lat_of, lon_of, half)
        if not use:
            missing.append(name)
            continue
        p, top = [], []
        for k in range(len(leads)):
            got = [(series[c][k], weight[c[0]]) for c in use if series[c][k] is not None]
            wsum = sum(w for _, w in got)
            if not got or wsum <= 0:
                p.append(None)
                top.append(None)
                continue
            p.append(round(sum(v * w for v, w in got) / wsum, 2))
            top.append(round(max(v for v, _ in got), 2))
        z = {"p": p, "max": top, "cells": len(use), "approx": how is not None}
        if how:
            z["approx_basis"] = how
            approx.append(f"{name} ({how}, {len(use)})")
        zones[name] = z

    print(f"  {len(zones)} zones, {len(approx)} approximate, {len(missing)} missing")
    if approx:
        print("  approximate: " + "; ".join(approx))
    if missing:
        print("  missing: " + ", ".join(missing))

    return {
        "source": "NOAA Physical Sciences Laboratory, NMME marine heatwave forecast",
        "url": PSL_FILE,
        "subset_url": (PSL_DAP4 + ".dap?dap4.ce=/" + PSL_VAR + "".join(
            f"[{n_init - 1}]" if d == "/start_time" else f"[0:{s - 1}]"
            for d, s in zip(var["dims"], var["shape"]))),
        "subset_note": ("The newest forecast only (last start_time), fetched from PSL's DAP4 "
                        "server one lead and band of latitudes at a time, because answers over "
                        "65,535 bytes came back corrupted; every piece's checksum is verified."),
        "page": PSL_PAGE,
        "method_url": PSL_METHOD,
        "variant": "with trend (not detrended)",
        "threshold": "90th percentile",
        "init": init_ym,
        "fetched": time.strftime("%Y-%m-%d"),
        "leads": leads,
        "months": months,
        "models": (meta["attrs"].get("model_use") or [None])[0],
        "note": (
            "Chance that the month's average sea surface temperature is in a marine heatwave: "
            "above the 90th percentile of 1991-2020 anomalies for that time of year (3-month "
            "window), computed from the North American Multi-Model Ensemble, with each model "
            "judged against its own forecast climate. Kept with the long-term warming trend "
            "(not detrended), so it asks the same question as the atlas's current heatwave layer "
            "(NOAA Coral Reef Watch, fixed climatology); the detrended version asks 'hot even for "
            "today's warmer ocean' and mostly gives lower odds. Per zone: the area-weighted (cos "
            "latitude) mean, and the maximum, over the 1-degree cells whose centres fall inside "
            "the zone or on its edge; land, sea-ice and blank cells excluded. 'approx' zones "
            "have no ocean cell centre inside them and use the ocean cells their outline passes "
            "through (approx_basis 'overlap') or the nearest ocean cell within 1.5 degrees "
            "('nearest'). "
            "The first month is the month the forecast started in. Models run 9-11 months "
            "ahead, so the last months rest on fewer models. PSL calls these forecasts "
            "experimental."
        ),
        "zones": zones,
        "missing": missing,
    }


# ---------------------------------------------------------------------------

def _dump(doc):
    """indent=1 like climate.json, but short lists of numbers stay on one line."""
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    return re.sub(r"\[\s+([^\[\]{}]*?)\s+\]",
                  lambda m: "[" + " ".join(m.group(1).split()) + "]", text)


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "outlook.json")
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}

    fresh, failed = {}, []

    print("ENSO probabilities (CPC)")
    try:
        fresh["enso_odds"] = enso_odds()
        o = fresh["enso_odds"]
        print(f"  issued {o['issued']}: " + ", ".join(
            f"{s['season']} El Nino {s['el_nino']}%" for s in o["seasons"][:5]))
    except Exception as e:
        print(f"  ! {e}")
        failed.append("enso_odds")

    print("ENSO strength probabilities (CPC)")
    try:
        fresh["enso_strength"] = enso_strength(fresh.get("enso_odds"))
        s = fresh["enso_strength"]
        print(f"  issued {s['issued']}: " + ", ".join(
            f"{r['season']} very strong {r['el_nino_very_strong']}%" for r in s["seasons"][:4])
            + f"; matches the probabilities page: {s['matches_odds']}")
    except Exception as e:
        print(f"  ! {e}")
        failed.append("enso_strength")

    print("Marine heatwave forecast (PSL)")
    started = time.time()
    try:
        fresh["mhw_forecast"] = mhw_forecast()
        print(f"  ({time.time() - started:.0f}s)")
    except Exception as e:
        print(f"  ! {e}")
        failed.append("mhw_forecast")

    # A part that failed, or came back older or thinner than what is already on
    # the site, does not replace it: the previous part is kept, with its own dates.
    out = {"generated": time.strftime("%Y-%m-%d")}
    for key in ("enso_odds", "enso_strength", "mhw_forecast"):
        new, prev = fresh.get(key), old.get(key)
        if new and prev:
            stamp = "init" if key == "mhw_forecast" else "issued_month"
            if (new.get(stamp) or "") < (prev.get(stamp) or ""):
                print(f"  ! {key}: the server sent {new.get(stamp)}, older than the "
                      f"{prev.get(stamp)} already saved; keeping the saved one")
                new = None
            elif key == "mhw_forecast" and len(new["zones"]) < len(prev.get("zones", {})) - 5:
                print(f"  ! {key}: only {len(new['zones'])} zones against {len(prev['zones'])} "
                      f"saved; keeping the saved one")
                new = None
            if new is None and key not in failed:
                failed.append(key)
        if new:
            out[key] = new
        elif prev:
            out[key] = prev
            print(f"  {key}: kept the saved copy (issued/started "
                  f"{prev.get('issued_month') or prev.get('init')})")

    if not any(k in fresh and out.get(k) is fresh[k] for k in fresh):
        print("\n  ! nothing new to write. outlook.json is left as it was; run again later.")
        return 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(_dump(out) + "\n")
    print(f"\n  wrote {os.path.relpath(path, HERE)}"
          + (f"  (kept saved copies of: {', '.join(failed)})" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
