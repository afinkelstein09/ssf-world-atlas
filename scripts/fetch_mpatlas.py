"""
Build the protection layer: protected on paper versus protected in practice.

The atlas already shows "protected waters" from the World Bank, which is what
governments report to the World Database on Protected Areas (WDPA, now WDPCA).
That number counts a marine protected area from the day it is declared. Peru's
WDPA figure is 67,491 km2, and the Marine Protection Atlas finds that its one
assessed zone (62,341 km2) is designated in law but not yet implemented on the
water. The Philippines lists 31,910 km2; MPAtlas has assessed 4,691 km2 of it,
of which 1,609 km2 is fully protected.

MPAtlas (Marine Conservation Institute) re-classifies MPAs with The MPA Guide
(Grorud-Colvert et al. 2021, Science): a stage of establishment (proposed,
designated, implemented, actively managed) and a level of protection (fully,
highly, lightly, minimally). This script reads its per-country summary.

Three things to state wherever this data is shown:

  1. Permission has NOT been given. MPAtlas's data policy page is a placeholder
     ("TODO: content from MCI...") and the endpoint sits under /api/v1/internal/.
     Ask Marine Conservation Institute before anything is published.
  2. Not assessed is not unprotected, and assessed is not protected. In October
     2026, 83 of the atlas's 178 countries had no MPAtlas assessment at all; and
     "assessed" area includes proposals (Papua New Guinea: 2.6 million km2, all
     proposed). Protected in practice means implemented, and fully or highly.
  3. Percentages have two different bases. MPAtlas's own percentages are of
     its marine area (the EEZ, Flanders Marine Institute boundaries v11); the
     WDPA figures carry their own, different, marine area. France is the clearest
     case: MPAtlas's "France" is the mainland and Clipperton (781,000 km2), while
     the atlas's France also holds Reunion, Guadeloupe and the southern islands.

Outputs site/data/mpatlas.json, keyed by ISO3, for the atlas's own countries only.

Sources:
  https://mpatlas.org/api/v1/internal/details/countries/{ISO3}   (keyless JSON)
  https://mpatlas.org/glossary/  https://mpatlas.org/methods/
  https://marine-conservation.org/mpatlas/faq/
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "mpatlas")
OUT = os.path.join(HERE, "site", "data")

SITE = "https://mpatlas.org"
API = SITE + "/api/v1/internal/details/countries/"
HEADERS = {"User-Agent": "ssf-atlas/0.1 (research prototype)", "Accept": "application/json"}

# One request at a time, never closer than this. The API is labelled internal,
# so we knock gently and cache everything.
PAUSE = 1.2

# If more than this many countries get no HTTP answer at all, the problem is the
# connection, and a file with holes in it is worse than the last good one.
MAX_UNANSWERED = 5

LICENCE_STATUS = {
    "status": "not_granted",
    "summary": ("Permission to use or republish MPAtlas data has not yet been given. "
                "Do not publish this file or anything built from it until Marine "
                "Conservation Institute agrees."),
    "evidence": [
        {"url": "https://mpatlas.org/data_policy/",
         "observed": "The data policy page holds only a placeholder ('TODO: content from MCI...')."},
        {"url": API + "{ISO3}",
         "observed": "The endpoint is under /api/v1/internal/: built for mpatlas.org's own pages, not documented for reuse."},
        {"url": "https://marine-conservation.org/mpatlas/mpatlas-and-wdpa/",
         "observed": "MPAtlas asks that any use or citation of its data and statistics be time stamped."},
    ],
    "cite_as": "Marine Conservation Institute (2026). Marine Protection Atlas, mpatlas.org. Accessed {date}.",
}

# Plain-language definitions, paraphrased from MPAtlas's own pages (URLs given).
DEFINITIONS = {
    "stage_of_establishment": {
        "source": "https://mpatlas.org/glossary/ (MPA Guide definitions); The MPA Guide, Grorud-Colvert et al. 2021, https://doi.org/10.1126/science.abf0861",
        "proposed_committed": "The intent to create the MPA has been made public (an official announcement, a submission to the Convention on Biological Diversity, and so on). It has no legal standing yet.",
        "designated": "Established in law or by another recognised, authoritative process. The MPA exists on paper.",
        "implemented": "Operating on the water: a defined boundary, conservation-first objectives, and management in place that aims to secure compliance and enforcement.",
        "actively_managed": "Implemented, with ongoing enforced rules, monitoring, evaluation and adaptive management, and conservation outcomes. The country endpoint does NOT report this stage separately (no status code for it); see notes.",
    },
    "level_of_protection": {
        "source": "https://mpatlas.org/glossary/ and the status legend on mpatlas.org",
        "fully": "No extractive or destructive activity allowed; all impacts minimised.",
        "highly": "Only light extraction allowed; other impacts minimised as far as possible.",
        "lightly": "Some protection, but moderate to substantial extraction and other impacts allowed.",
        "minimally": "Extensive extraction and other impacts allowed, with some conservation benefit still possible. MPAtlas's country data folds 'incompatible with conservation' into this level: its label for code 'im' is 'Implemented: Minimally Protected / Incompatible with Conservation'.",
        "incompatible": "Activity so extractive or destructive that it conflicts directly with conservation. Not a separate code in the country data (inside 'minimally').",
        "unknown": "Level not yet determined. MPAtlas's FAQ calls it 'Unknown' for implemented sites where the information was not available, and 'TBD' for designated or proposed sites whose regulations are not yet set.",
    },
    "assessed_vs_wdpa": {
        "source": "https://mpatlas.org/methods/ and https://marine-conservation.org/mpatlas/faq/",
        "wdpa_listed": "Area governments and agencies report to the WDPA (now WDPCA) as protected. It counts an MPA from the time of designation, whatever the rules on the water.",
        "assessed": "Area MPAtlas has independently classified with The MPA Guide (stage and level). It starts from the WDPA's boundaries and adds zones the WDPA lacks, and it INCLUDES proposed areas that are not protected even on paper (assessed = designated + proposed). So it is not a subset of the WDPA-listed area and can be larger (coverage.assessed_exceeds_wdpa; in October 2026 Papua New Guinea had 2.6 million km2 assessed, all of it proposed). Only a portion of the 18,000+ WDPA marine sites have been assessed.",
        "not_assessed": "WDPA-listed area that MPAtlas has not assessed is unknown to MPAtlas, not unprotected.",
    },
    "status_du": "Code 'du' = Designated, protection level Unknown/TBD: in law (on paper) but not implemented on the water, and its rules not yet classified. Peru's one assessed zone is 'du'. Site label: 'Designated: Unknown Protection'.",
    "percent_base": "MPAtlas percentages are of MPAtlas's marine area for that country: the EEZ from Flanders Marine Institute's Maritime Boundaries Geodatabase v11 (https://mpatlas.org/methods/), shown on mpatlas.org as 'total marine area (to limit of exclusive economic zone)'. The WDPA percentage here uses the WDPA's own marine area instead. The two areas can differ a lot; never divide one source's km2 by the other's area.",
}

# MPAtlas status codes: first letter is the stage, second the level. Labels as
# mpatlas.org's legend prints them. The site's own ranking also allows df, dh,
# dl and dm (designated, level known); none occur in the data as of October 2026.
STAGE_OF = {"i": "implemented", "d": "designated", "p": "proposed", "u": "not_assessed"}
LEVEL_OF = {"f": "fully", "h": "highly", "l": "lightly", "m": "minimally", "u": "unknown"}
STATUS_LABELS = {
    "if": "Implemented: Fully Protected",
    "ih": "Implemented: Highly Protected",
    "il": "Implemented: Lightly Protected",
    "im": "Implemented: Minimally Protected / Incompatible with Conservation",
    "iu": "Implemented: Unknown Protection",
    "df": "Designated: Fully Protected",
    "dh": "Designated: Highly Protected",
    "dl": "Designated: Lightly Protected",
    "dm": "Designated: Minimally Protected / Incompatible with Conservation",
    "du": "Designated: Unknown Protection",
    "pc": "Proposed / Committed",
    "u": "Not Assessed",
}

# Every number below traces to one of these API fields.
RAW_FIELDS = {
    "id": "ISO3 (or MPAtlas region id; 'FRA*' style ids are a sovereign plus all its territories)",
    "assessment_date": "date of MPAtlas's latest assessment for the country -> assessment_date",
    "wdpa_marine_km2": "WDPA's marine area for the country -> marine_km2.wdpa, base of wdpa_listed.pct",
    "wdpa_protected_marine_km2": "WDPA-listed protected marine area -> wdpa_listed.km2",
    "assessed_km2 / _percent / _zones": "area MPAtlas has assessed (= designated + proposed) -> assessed",
    "proposed_km2 / _percent / _zones": "proposed or committed, not yet designated -> stage.proposed",
    "designated_km2 / _percent / _zones": "designated OR further along (includes implemented) -> stage.designated_or_further",
    "implemented_km2 / _percent / _zones": "implemented (actively managed not separable) -> stage.implemented",
    "highly_protected_km2 / _percent / _zones": "FULLY OR HIGHLY protected and implemented (= if + ih), despite the name -> fully_or_highly",
    "mpaguide_status[].key / km2 / percent / zones": "area by status code (stage letter + level letter) -> status, and summed into level and stage.designated_only",
    "num_top_level_mpas": "number of MPAs (a zoned MPA counts once) -> mpas",
    "zones": "number of MPA zones -> zones",
    "has_points": "some sites are mapped as points with no area, so km2 understates them -> has_points",
    "thirty_by_thirty_target / national_target / fully_highly_target / target_year / pledge / pledge_url": "the country's stated targets -> targets",
    "(site) km2": "MPAtlas marine area, from the region list in mpatlas.org's page code -> marine_km2.mpatlas, base of every pct except wdpa_listed.pct",
}

_last_request = [0.0]


def polite_get(url, accept=None):
    """GET with a pause before it. Returns (status, bytes); status None = no answer."""
    wait = PAUSE - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()
    finally:
        _last_request[0] = time.time()


def load_log():
    path = os.path.join(RAW, "fetch_log.json")
    return json.load(open(path)) if os.path.exists(path) else {}


def save_log(log):
    with open(os.path.join(RAW, "fetch_log.json"), "w") as f:
        json.dump(log, f, indent=1, sort_keys=True)


def country_record(iso, log):
    """
    The API's answer for one ISO3, from cache when we have it.

    A 200 is cached byte for byte as countries/ISO3.json. Any other HTTP answer is
    cached as countries/ISO3.status.json so it is not asked again. No answer at
    all is not cached, so the next run tries again.
    Returns (record or None, status).
    """
    folder = os.path.join(RAW, "countries")
    os.makedirs(folder, exist_ok=True)
    ok = os.path.join(folder, f"{iso}.json")
    other = os.path.join(folder, f"{iso}.status.json")
    if os.path.exists(ok):
        return json.load(open(ok)), 200
    if os.path.exists(other):
        return None, json.load(open(other))["status"]

    status, body = polite_get(API + iso)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if status is None:
        print(f"    {iso}: no answer ({body.decode(errors='replace')[:80]})")
        return None, None
    log[iso] = {"url": API + iso, "status": status, "fetched": stamp, "bytes": len(body)}
    if status == 200:
        with open(ok, "wb") as f:
            f.write(body)
        try:
            return json.loads(body), 200
        except ValueError:
            return None, 200
    with open(other, "w") as f:
        json.dump({"status": status, "body": body.decode("utf-8", errors="replace")[:2000],
                   "fetched": stamp}, f, indent=1)
    return None, status


def site_regions(log):
    """
    MPAtlas's marine area for every region, which the API does not return.

    mpatlas.org builds its country pages from a region list compiled into its page
    code (name, sovereign, km2). Every API percentage is km2 divided by this area,
    so it is the only base the API's numbers can be checked against. Reading it
    takes three requests: the home page, the script loader, and the shared bundle.
    If the site's code changes shape, this returns {} and percentages we derive
    ourselves are left empty rather than guessed.
    """
    cache = os.path.join(RAW, "site_regions.json")
    if os.path.exists(cache):
        return {r["id"]: r for r in json.load(open(cache))["regions"]}

    os.makedirs(os.path.join(RAW, "site"), exist_ok=True)
    try:
        status, home = polite_get(SITE + "/", accept="text/html")
        runtime = re.search(r'src="/(webpack-runtime-[0-9a-f]+\.js)"', home.decode("utf-8", "replace")).group(1)
        status, rt = polite_get(f"{SITE}/{runtime}", accept="*/*")
        rt = rt.decode("utf-8", "replace")
        chunk = re.search(r'(\d+):"commons"', rt).group(1)
        digest = re.search(r'\b' + chunk + r':"([0-9a-f]{20})"', rt).group(1)
        bundle_name = f"commons-{digest}.js"
        status, bundle = polite_get(f"{SITE}/{bundle_name}", accept="*/*")
        with open(os.path.join(RAW, "site", bundle_name), "wb") as f:
            f.write(bundle)
        text = bundle.decode("utf-8")
        start = text.index("JSON.parse('[{\"id\":\"") + len("JSON.parse('")
        end = text.index("]')", start) + 1
        regions = json.loads(text[start:end].replace("\\'", "'"))
        if not regions or "km2" not in regions[0]:
            raise ValueError("region list has no km2")
    except Exception as e:
        print(f"  ! could not read MPAtlas's region list from its page code ({e}); "
              "derived percentages will be empty")
        return {}

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    log["_site_regions"] = {"url": f"{SITE}/{bundle_name}", "status": 200, "fetched": stamp}
    with open(cache, "w") as f:
        json.dump({"source": f"{SITE}/{bundle_name}", "fetched": stamp,
                   "regions": regions}, f, indent=0)
    return {r["id"]: r for r in regions}


def atlas_countries():
    """The atlas's ISO3 codes and, per code, its Sea Around Us zones and their EEZ areas."""
    zones = json.load(open(os.path.join(OUT, "countries.json")))["countries"]
    out = {}
    for z in zones:
        iso = z.get("iso3")
        if not iso:
            continue
        km2 = None
        meta = os.path.join(HERE, "data", "raw", "eco_meta", f"{z['region_id']}.json")
        if os.path.exists(meta):
            for m in json.load(open(meta))["data"].get("metrics", []):
                if m.get("title") == "EEZ area":
                    km2 = m.get("value")
        out.setdefault(iso, []).append({"name": z["name"], "region_id": z["region_id"],
                                        "kind": z.get("iso_kind"), "km2": km2})
    return out


def _in_ring(ring, x, y):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def territory_owners(regions, atlas):
    """
    Which atlas country holds each place MPAtlas reports under its own code.

    MPAtlas gives each territory a point (its island, usually), so the test is
    which atlas zone outline contains that point. Holes are ignored on purpose:
    the island itself is a hole in its own zone. Where outlines overlap (the
    Comoros zone takes in Mayotte, which Comoros claims) the smallest zone wins,
    which is the territory's own zone if the atlas has one.
    """
    km2 = {z["region_id"]: z["km2"] for zs in atlas.values() for z in zs}
    zones = []
    for ft in json.load(open(os.path.join(OUT, "eez.geojson")))["features"]:
        geom, p = ft.get("geometry"), ft["properties"]
        if geom and p.get("iso3"):
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            zones.append((km2.get(p.get("region_id")) or float("inf"), p["iso3"], polys))
    owners = {}
    for rid, r in regions.items():
        if rid.endswith("*") or rid in atlas or r.get("longitude") is None:
            continue
        x0, y = r["longitude"], r["latitude"]
        hits = [(size, iso) for size, iso, polys in zones
                if any(_in_ring(poly[0], x, y) for poly in polys for x in (x0, x0 + 360, x0 - 360))]
        if hits:
            owners[rid] = min(hits)[1]
    return owners


def r1(x):
    return round(float(x), 1) if x is not None else None


def r2(x):
    return round(float(x), 2) if x is not None else None


def summarise(iso, rec, region, zones, regions, owners):
    """One country's entry. `rec` is the API answer, `region` MPAtlas's area for it."""
    area = region.get("km2") if region else None

    def pct(km2):
        # Our own percentage, on MPAtlas's base, for totals the API does not give.
        return round(100.0 * km2 / area, 2) if (area and km2 is not None) else None

    def block(prefix):
        return {"km2": r1(rec.get(f"{prefix}_km2")),
                "pct": r2(rec.get(f"{prefix}_percent")),
                "zones": rec.get(f"{prefix}_zones")}

    statuses = rec.get("mpaguide_status") or []
    assessed = bool(rec.get("assessment_date")) or (rec.get("assessed_km2") or 0) > 0

    # Area by level, summed across stages; and area designated but not implemented.
    level = {lv: {"km2": 0.0, "zones": 0} for lv in ("fully", "highly", "lightly", "minimally", "unknown")}
    designated_only = {"km2": 0.0, "zones": 0}
    status_out = []
    for s in statuses:
        key = s.get("key") or ""
        km2, zones_n = float(s.get("km2") or 0), int(s.get("zones") or 0)
        status_out.append({"key": key, "label": STATUS_LABELS.get(key, key),
                           "stage": STAGE_OF.get(key[:1]), "level": LEVEL_OF.get(key[1:2]) if len(key) == 2 and key != "pc" else None,
                           "km2": r1(km2), "pct": r2(s.get("percent")), "zones": zones_n})
        if len(key) == 2 and key != "pc" and key[1] in LEVEL_OF:
            lv = level[LEVEL_OF[key[1]]]
            lv["km2"] += km2
            lv["zones"] += zones_n
        if key.startswith("d"):
            designated_only["km2"] += km2
            designated_only["zones"] += zones_n
    for lv in level.values():
        lv["km2"] = r1(lv["km2"])
        lv["pct"] = pct(lv["km2"])
    designated_only["km2"] = r1(designated_only["km2"])
    designated_only["pct"] = pct(designated_only["km2"])

    wdpa_area = rec.get("wdpa_marine_km2")
    wdpa_km2 = rec.get("wdpa_protected_marine_km2")
    wdpa_pct = round(100.0 * wdpa_km2 / wdpa_area, 2) if (wdpa_area and wdpa_km2 is not None) else None

    # Does MPAtlas's "country" cover the same water as the atlas's? Compare its
    # area with the Sea Around Us EEZ areas of the atlas zones filed under this code,
    # and name the territories MPAtlas reports under their own code. A territory
    # counts only if its point falls inside one of the atlas's zones for this code:
    # MPAtlas files Mayotte under Comoros as well as France (a claim), and South
    # Georgia under Argentina as well as the UK, but the atlas maps both elsewhere.
    atlas_km2 = sum(z["km2"] or 0 for z in zones) or None
    ratio = round(area / atlas_km2, 2) if (area and atlas_km2) else None
    separate = sorted(f"{rid} {regions[rid]['name']}" for rid, owner in owners.items()
                      if owner == iso and f"{iso}*" in (regions[rid].get("sovereigns") or []))
    aggregate = f"{iso}*" if f"{iso}*" in regions else None
    warning = None
    if separate:
        sizes = (f" ({area:,.0f} km2 against {atlas_km2:,.0f} km2 for the atlas's {iso} zones)"
                 if (area and atlas_km2) else "")
        warning = (f"MPAtlas's {iso} record covers {(region or {}).get('name', iso)} only{sizes}. "
                   f"MPAtlas gives these places their own codes, not fetched here: {', '.join(separate)}."
                   + (f" It also has {aggregate}, the sovereign with every territory, including ones the atlas maps on their own." if aggregate else ""))
    elif ratio is not None and not (0.85 <= ratio <= 1.15):
        warning = (f"MPAtlas's marine area for {iso} is {ratio:.2f} times the atlas's "
                   "(Sea Around Us) EEZ area for the same code: boundaries or disputed "
                   "waters are drawn differently, so the two cover different water.")

    entry = {
        "name": (region or {}).get("name") or iso,
        "url": f"{SITE}/countries/{iso}",
        "assessed": assessed,
        "assessment_date": rec.get("assessment_date"),
        "marine_km2": {"mpatlas": r1(area), "wdpa": r1(wdpa_area), "atlas_sau": r1(atlas_km2)},
        "wdpa_listed": {"km2": r1(wdpa_km2), "pct": wdpa_pct},
        "assessed_area": block("assessed"),
        "stage": {
            "proposed": block("proposed"),
            "designated_or_further": block("designated"),
            "designated_only": designated_only,
            "implemented": block("implemented"),
        },
        "fully_or_highly": block("highly_protected"),
        "level": level,
        "status": status_out,
        "mpas": rec.get("num_top_level_mpas"),
        "zones": rec.get("zones"),
        "targets": {k: rec.get(k) for k in ("thirty_by_thirty_target", "national_target",
                                             "fully_highly_target", "target_year",
                                             "pledge", "pledge_url")},
        "scope": {"mpatlas_vs_atlas_area": ratio, "separate_in_mpatlas": separate or None,
                  "sovereign_aggregate": aggregate, "warning": warning},
    }
    if rec.get("has_points") or any(s.get("has_points") for s in statuses):
        entry["has_points"] = True
    return entry


def main():
    os.makedirs(RAW, exist_ok=True)
    log = load_log()

    atlas = atlas_countries()
    isos = sorted(atlas)
    print(f"Atlas: {len(isos)} ISO3 codes")

    print("MPAtlas region areas (from mpatlas.org's page code)")
    regions = site_regions(log)
    print(f"  {len(regions)} regions")

    print(f"MPAtlas country details, one request at least {PAUSE}s apart (cached in data/raw/mpatlas/)")
    records, no_record, unanswered = {}, {}, []
    for n, iso in enumerate(isos, 1):
        rec, status = country_record(iso, log)
        if status is None:
            unanswered.append(iso)
        elif rec and isinstance(rec, dict) and rec.get("id"):
            records[iso] = rec
        else:
            no_record[iso] = status
        if n % 25 == 0:
            save_log(log)
            print(f"  {n}/{len(isos)}")
    save_log(log)

    if len(unanswered) > MAX_UNANSWERED:
        raise SystemExit(f"{len(unanswered)} countries got no answer ({unanswered[:8]}...); "
                         "mpatlas.json left as it was. Run again.")

    out = {}
    owners = territory_owners(regions, atlas)
    for iso, rec in records.items():
        out[iso] = summarise(iso, rec, regions.get(iso), atlas[iso], regions, owners)

    assessed = sorted(i for i, e in out.items() if e["assessed"])
    not_assessed = sorted(i for i, e in out.items() if not e["assessed"])
    fetched = sorted(v["fetched"][:10] for k, v in log.items() if k in records)
    today = time.strftime("%Y-%m-%d")

    with open(os.path.join(OUT, "mpatlas.json"), "w") as f:
        json.dump({
            "generated": today,
            "fetched": {"first": fetched[0] if fetched else None, "last": fetched[-1] if fetched else None},
            "licence_status": {**LICENCE_STATUS,
                               "cite_as": LICENCE_STATUS["cite_as"].format(date=fetched[-1] if fetched else today)},
            "source": "Marine Protection Atlas (MPAtlas), Marine Conservation Institute, https://mpatlas.org",
            "endpoint": API + "{ISO3}",
            "definitions": DEFINITIONS,
            "status_codes": STATUS_LABELS,
            "raw_fields": RAW_FIELDS,
            "notes": [
                "Not assessed is not unprotected: a country with assessed=false has WDPA-listed area that MPAtlas has not classified.",
                "Assessed is not protected: assessed_area includes proposed areas (stage.proposed). For 'protected in practice' use stage.implemented and fully_or_highly; for 'on paper only' use stage.designated_only.",
                "pct fields are % of marine_km2.mpatlas, except wdpa_listed.pct (% of marine_km2.wdpa). Where the API gives a percent it is copied (2 decimals); level.*.pct and designated_only.pct are computed here from km2 on the same base.",
                "Stages are cumulative: designated_or_further includes implemented; designated_only = designated but not implemented ('on paper').",
                "fully_or_highly is the API's highly_protected_* field, which is fully + highly protected implemented area (codes if + ih).",
                "Actively managed is not reported separately by the country endpoint; it has no status code, and implemented is cumulative, so it is presumably inside implemented. The API does not say.",
                "scope.warning flags countries where MPAtlas's area and the atlas's differ: territories MPAtlas reports separately, or different EEZ boundaries.",
            ],
            "coverage": {
                "atlas_countries": len(isos),
                "with_record": len(out),
                "assessed": len(assessed),
                "record_but_not_assessed": not_assessed,
                "assessed_exceeds_wdpa": sorted(i for i, e in out.items() if e["assessed"] and
                                                (e["assessed_area"]["km2"] or 0) > (e["wdpa_listed"]["km2"] or 0)),
                "scope_warnings": sorted(i for i, e in out.items() if e["scope"]["warning"]),
                "no_record": {iso: status for iso, status in sorted(no_record.items())},
                "unanswered": unanswered,
            },
            "countries": out,
        }, f, indent=1, ensure_ascii=False)

    print(f"\n  wrote {len(out)} of {len(isos)} atlas countries: {len(assessed)} assessed, "
          f"{len(not_assessed)} with a record but no assessment")
    print(f"  no MPAtlas record: {sorted(no_record)}" + (f"; unanswered: {unanswered}" if unanswered else ""))
    flagged = sorted(i for i, e in out.items() if e["scope"]["warning"])
    print(f"  {len(flagged)} countries cover different water in MPAtlas and the atlas: {flagged}")
    gap = sorted(((i, e) for i, e in out.items() if e["assessed"] and e["wdpa_listed"]["km2"]),
                 key=lambda kv: -(kv[1]["wdpa_listed"]["km2"] or 0))[:8]
    print("\n  largest WDPA-listed areas, and how much is implemented and fully/highly protected:")
    for iso, e in gap:
        print(f"    {iso}  WDPA {e['wdpa_listed']['km2']:>12,.0f} km2   assessed {e['assessed_area']['km2']:>12,.0f}"
              f"   implemented {e['stage']['implemented']['km2']:>12,.0f}   fully/highly {e['fully_or_highly']['km2']:>11,.0f}")


if __name__ == "__main__":
    main()
