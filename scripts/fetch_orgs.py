"""
Build the organisation layer: who is working on small-scale fisheries, and where.

This is the layer no existing marine atlas has. Every other global product maps
fish, catch, or vessels; none maps the institutions. There is no registry of it
either - not from the LMMA Network, not from the SSF Hub, which has no map at all.

IATI is the way in. It is the reporting standard donors and NGOs publish aid
activities to, and its records carry sector codes, geocoded locations, funders,
implementers, dates and budgets. Free, no key.

Two filters matter, and both exist because the raw sector query is noisy:

  1. A fisheries share threshold. IATI activities carry several sector codes with
     percentages, so a Niger Basin hydro project appears under "fishery
     development" at 2%. Without a threshold the layer fills with projects that
     merely touch fisheries.
  2. Coastal countries only. The atlas maps exclusive economic zones, so an
     inland fishery project has nowhere to sit.

Outputs site/data/orgs.json.

Source: IATI Registry via the Code for IATI Datastore,
https://datastore.codeforiati.org - open data, no key required.
"""

import json
import re
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "iati")
OUT = os.path.join(HERE, "site", "data")
API = "https://datastore.codeforiati.org/api/1/access/activity.json"

# OECD DAC purpose codes for fisheries.
SECTORS = {
    "31310": "Fishing policy and administration",
    "31320": "Fishery development",
    "31381": "Fishery education and training",
    "31382": "Fishery research",
    "31391": "Fishery services",
}

# An activity must devote at least this share to fisheries to count. Activities
# that report no percentages at all are kept - many small NGOs omit them, and
# dropping those would bias the layer toward large multilaterals.
MIN_SHARE = 25.0

PAGE = 200

# IATI participating-org role codes.
ROLES = {"1": "funding", "2": "accountable", "3": "extending", "4": "implementing"}


def get(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(3 * (attempt + 1))
    return None


def fetch_sector(code):
    """All activities for one sector code, paged and cached."""
    cache = os.path.join(RAW, f"{code}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    os.makedirs(RAW, exist_ok=True)
    out, offset = [], 0
    while True:
        params = urllib.parse.urlencode({"sector": code, "limit": PAGE, "offset": offset})
        data = get(f"{API}?{params}")
        if not data:
            break
        batch = data.get("iati-activities", [])
        out.extend(batch)
        total = data.get("total-count", 0)
        offset += PAGE
        print(f"    {code}: {len(out)}/{total}")
        if offset >= total or not batch:
            break
        time.sleep(0.6)

    with open(cache, "w") as f:
        json.dump(out, f)
    return out


def narrative(node):
    """IATI narratives appear as a string, a dict, or a list of either."""
    if node is None:
        return None
    if isinstance(node, str):
        return node.strip() or None
    if isinstance(node, list):
        for item in node:
            v = narrative(item)
            if v:
                return v
        return None
    if isinstance(node, dict):
        for key in ("narrative", "text"):
            if key in node:
                v = narrative(node[key])
                if v:
                    return v
    return None


def fisheries_share(activity):
    """
    Percentage of this activity attributed to fisheries purpose codes.

    Returns None when the activity reports no usable percentages, which the
    caller treats as 'keep' rather than 'drop'.
    """
    sectors = activity.get("sector")
    if not sectors:
        return None
    if isinstance(sectors, dict):
        sectors = [sectors]

    total_pct, fish_pct, saw_pct = 0.0, 0.0, False
    for s in sectors:
        # Vocabulary 1 is the OECD DAC purpose list. Publishers also attach their
        # own taxonomies with their own percentages, which must not be mixed in.
        if str(s.get("vocabulary", "1")) != "1":
            continue
        code = str(s.get("code", ""))
        try:
            pct = float(s.get("percentage"))
        except (TypeError, ValueError):
            pct = None
        if pct is None:
            continue
        saw_pct = True
        total_pct += pct
        if code in SECTORS:
            fish_pct += pct

    if not saw_pct or total_pct <= 0:
        return None
    return 100.0 * fish_pct / total_pct


# Country names as IATI publishers write them as place names ("Senegal", "KH -
# Cambodia", "Republic of Kenya"), from the atlas's own country outlines.
def _country_words():
    words = {"dr congo", "drc", "png"}
    path = os.path.join(HERE, "site", "data", "country.geojson")
    if os.path.exists(path):
        with open(path) as f:
            for ft in json.load(f)["features"]:
                n = (ft["properties"].get("name") or "").strip().lower()
                if n:
                    words.add(n)
    return words


COUNTRY_WORDS = _country_words()


def locations(activity):
    """Geocoded points, converting IATI's 'lat lon' string to (lon, lat)."""
    locs = activity.get("location")
    if not locs:
        return []
    if isinstance(locs, dict):
        locs = [locs]

    out = []
    for loc in locs:
        pos = ((loc.get("point") or {}).get("pos") or "").strip()
        if not pos:
            continue
        parts = pos.split()
        if len(parts) < 2:
            continue
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if lat == 0 and lon == 0:  # null island - a common placeholder
            continue
        # IATI says how precise a point is: exactness 2 is "approximate", location
        # class 1 is an administrative region, and a feature designation such as PCLI
        # (a country) or PPLC (a capital) is a stand-in, not a site. The first map drew
        # "Republic of Kenya" and Brasilia (26 projects) as if they were project sites.
        exact = str(((loc.get("exactness") or {}).get("code")) or "")
        klass = str(((loc.get("location-class") or {}).get("code")) or "")
        feature = str(((loc.get("feature-designation") or {}).get("code")) or "").upper()
        # World Bank tags nearly every point "approximate", towns included, so exactness
        # alone is not used: a town, village, beach or landing site (class 2 or 4) is a
        # place; a region, a capital standing in for a country, or a point named after
        # the country itself is not.
        name = narrative(loc.get("name"))
        bare = re.sub(r"^[A-Z]{2}\s*-\s*", "", (name or "")).strip().lower()
        approx = (klass == "1" or feature in ("PCLI", "PCL", "PPLC", "ADM1", "ADM2", "ADMD")
                  or (klass in ("", "0") and exact == "2")
                  or bare.startswith("republic of") or bare in COUNTRY_WORDS or " region" in bare)
        out.append({"name": name, "lon": round(lon, 4), "lat": round(lat, 4), "approx": approx})
    return out


def orgs(activity):
    """Participating organisations grouped by role."""
    parts = activity.get("participating-org")
    if not parts:
        return {}
    if isinstance(parts, dict):
        parts = [parts]
    grouped = {}
    for p in parts:
        role = ROLES.get(str(p.get("role")), None)
        name = narrative(p)
        if role and name:
            grouped.setdefault(role, [])
            if name not in grouped[role]:
                grouped[role].append(name)
    return grouped


def recipient_isos(activity):
    """ISO3 codes for the countries an activity reports as recipients."""
    rc = activity.get("recipient-country")
    if not rc:
        return []
    if isinstance(rc, dict):
        rc = [rc]
    out = []
    for c in rc:
        code = (c.get("code") or "").strip().upper()
        if len(code) == 2:
            out.append(code)
    return out


def dates(activity):
    ad = activity.get("activity-date")
    if not ad:
        return None, None
    if isinstance(ad, dict):
        ad = [ad]
    start = end = None
    for d in ad:
        t, iso = str(d.get("type")), d.get("iso-date")
        # A few publishers use 1900-01-01 as "unknown"; it would otherwise win
        # as the earliest start.
        if not iso or iso < "1950":
            continue
        if t in ("1", "2") and (start is None or iso < start):
            start = iso
        if t in ("3", "4") and (end is None or iso > end):
            end = iso
    return start, end


def main():
    os.makedirs(OUT, exist_ok=True)

    print("Fetching IATI activities by fisheries sector")
    raw = {}
    for code in SECTORS:
        for a in fetch_sector(code):
            act = a.get("iati-activity", a)
            ident = narrative(act.get("iati-identifier")) or json.dumps(act.get("title"))[:80]
            raw[ident] = act
    print(f"  {len(raw)} unique activities across {len(SECTORS)} sector codes\n")

    # ISO2 -> ISO3 from the World Bank's country list, which is live and
    # complete for its members - and silent about places that are not, so the
    # atlas zones it lacks are added by hand. Without that, 27 activities in
    # the Cook Islands, Niue, Saint Helena and North Korea were dropped as
    # having no recipient country.
    wb = json.load(open(os.path.join(HERE, "analysis", "wb_meta.json")))  # names for the summary
    wb_iso2 = {}
    data = get("https://api.worldbank.org/v2/country?format=json&per_page=400")
    if data and len(data) > 1:
        for c in data[1]:
            if c.get("id") and c.get("iso2Code"):
                wb_iso2[c["iso2Code"].upper()] = c["id"]
    if not wb_iso2:
        raise SystemExit("World Bank country list unreachable; orgs.json left as it was.")
    # Tokelau and Pitcairn are filed under their parents everywhere else in the
    # atlas (the zones resolve to NZL and GBR), so their activities go there too
    # rather than being dropped as "not coastal".
    for iso2, iso3 in {"CK": "COK", "NU": "NIU", "SH": "SHN", "KP": "PRK",
                       "PS": "PSE", "TW": "TWN", "AI": "AIA", "FK": "FLK",
                       "MS": "MSR", "PN": "GBR", "WF": "WLF", "PM": "SPM",
                       "GF": "GUF", "TK": "NZL"}.items():
        wb_iso2.setdefault(iso2, iso3)

    coastal = {z["iso3"] for z in json.load(open(f"{OUT}/countries.json"))["countries"] if z.get("iso3")}

    kept, dropped_share, dropped_inland, no_country = [], 0, 0, 0
    for ident, act in raw.items():
        share = fisheries_share(act)
        if share is not None and share < MIN_SHARE:
            dropped_share += 1
            continue

        isos2 = recipient_isos(act)
        isos3 = [wb_iso2.get(i) for i in isos2]
        isos3 = [i for i in isos3 if i]
        if not isos3:
            no_country += 1
            continue
        isos3 = [i for i in isos3 if i in coastal]
        if not isos3:
            dropped_inland += 1
            continue

        start, end = dates(act)
        kept.append({
            "id": ident,
            "title": narrative(act.get("title")),
            "countries": isos3,
            "orgs": orgs(act),
            "reporter": narrative(act.get("reporting-org")),
            "locations": locations(act),
            "start": start, "end": end,
            "fisheries_share": round(share) if share is not None else None,
        })

    print(f"  kept {len(kept)}")
    print(f"  dropped {dropped_share} below {MIN_SHARE:.0f}% fisheries")
    print(f"  dropped {dropped_inland} non-coastal, {no_country} with no recipient country")

    by_country = {}
    for a in kept:
        for iso in a["countries"]:
            by_country.setdefault(iso, []).append(a["id"])

    geocoded = [a for a in kept if a["locations"]]
    print(f"  {len(geocoded)} geocoded ({100*len(geocoded)/max(1,len(kept)):.0f}%), "
          f"{sum(len(a['locations']) for a in kept)} points total")
    print(f"  {len(by_country)} coastal countries covered")

    with open(os.path.join(OUT, "orgs.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "source": "IATI Registry via the Code for IATI Datastore (datastore.codeforiati.org)",
            "sectors": SECTORS,
            "min_fisheries_share": MIN_SHARE,
            "count": len(kept),
            "activities": kept,
            "by_country": by_country,
        }, f)

    top = sorted(by_country.items(), key=lambda kv: -len(kv[1]))[:10]
    print("\n  most activities:")
    for iso, ids in top:
        print(f"    {wb.get(iso,{}).get('name', iso)[:28]:<30}{len(ids):>4}")


if __name__ == "__main__":
    main()
