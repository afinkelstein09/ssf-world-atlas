"""
Build the regulatory layer: what law governs small-scale fishing in each country?

Caleb asked for "any sort of regulatory framework details (applicable laws, regs,
etc.)". Three things are assemblable today and one is not:

  Preferential access law   From the Duke dataset already in the atlas: the named
                            instrument, the year, what it excludes, and how its
                            boundary is defined. 44 countries.
  SSF Guidelines work       The ten countries where FAO reports active support for
                            implementing the Voluntary Guidelines.
  FAOLEX                    A deep link per country. FAOLEX returns 403 to scripts,
                            so this links out rather than pretending to have read it.

  SDG indicator 14.b.1      Blocked. unstats.un.org is unreachable from here - the
                            whole domain times out, not just the API - so the one
                            comparable global measure of SSF policy adoption is
                            missing. Left as a documented gap rather than dropped.

Outputs site/data/regulatory.json.
"""

import json
import os
import time
import urllib.parse

import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "site", "data")

# Countries where FAO reports active work supporting SSF Guidelines implementation.
# Source: https://www.fao.org/voluntary-guidelines-small-scale-fisheries/where-we-work/en
# Read 2026-08-31. Hard-coded because the page is a rendered list, not a dataset;
# it is small and it changes rarely, but it does change - check it on re-runs.
FAO_SSF_IMPLEMENTATION = {
    "GHA": "Ghana", "MDG": "Madagascar", "NAM": "Namibia", "PHL": "Philippines",
    "UGA": "Uganda", "TZA": "United Republic of Tanzania", "COL": "Colombia",
    "SLE": "Sierra Leone", "MWI": "Malawi", "IDN": "Indonesia",
}

FAOLEX = "https://www.fao.org/faolex/results/en/?query="


def main():
    os.makedirs(OUT, exist_ok=True)

    paa = {}
    p = os.path.join(OUT, "paa.json")
    if os.path.exists(p):
        paa = json.load(open(p))["countries"]

    names = {}
    wb = os.path.join(HERE, "analysis", "wb_meta.json")
    if os.path.exists(wb):
        names = {k: v.get("name") for k, v in json.load(open(wb)).items()}

    # The name printed in the panel and fed to the FAOLEX search. The World Bank's
    # house style ("Korea, Rep.", "Bahamas, The", "Naoero") is neither what a
    # reader expects nor what FAOLEX indexes under, so it is the last resort:
    # the atlas's own table first, then the country geometry's label - the same
    # name the panel heading uses, so the two never disagree.
    geo_names = {}
    cg = os.path.join(OUT, "country.geojson")
    if os.path.exists(cg):
        for feat in json.load(open(cg))["features"]:
            # last one wins, matching how the site resolves duplicate codes
            geo_names[feat["properties"]["iso3"]] = feat["properties"]["name"]

    # Every country the map can open gets a row, not just World Bank economies:
    # Cook Islands, Niue, the Falklands and a dozen other zones had no
    # "Search the law" link because the World Bank does not list them.
    zone_isos = set()
    cj = os.path.join(OUT, "countries.json")
    if os.path.exists(cj):
        zone_isos = {c["iso3"] for c in json.load(open(cj))["countries"] if c.get("iso3")}
    isos = set(paa) | set(FAO_SSF_IMPLEMENTATION) | set(names) | zone_isos
    out = {}
    for iso in sorted(isos):
        name = iso_lookup.display_name(
            iso, geo_names.get(iso), names.get(iso), paa.get(iso, {}).get("country"))
        entry = {}

        rec = paa.get(iso)
        if rec:
            law = str(rec.get("law") or "").strip()
            url = None
            import re
            m = re.search(r"(https?://\S+)", law)
            if m:
                url = m.group(1)
                law = law.replace(url, "").strip(" \n\t,")
            entry["access_law"] = {
                "name": law or None,
                "url": url,
                "year": rec.get("year"),
                "excludes": rec.get("excludes"),
                "boundary": rec.get("definition"),
                "percent_eez": rec.get("percent_eez"),
                "level": rec.get("level"),
                "expert_reviewed": rec.get("expert_reviewed"),
            }

        if iso in FAO_SSF_IMPLEMENTATION:
            entry["ssf_guidelines"] = {
                "active": True,
                "note": "FAO reports active support for implementing the SSF Guidelines here.",
            }

        # A search rather than a document: FAOLEX has no public API, and guessing
        # a record id would produce dead links.
        entry["faolex_search"] = FAOLEX + urllib.parse.quote(f"{name} small-scale fisheries")
        entry["country"] = name
        out[iso] = entry

    with open(os.path.join(OUT, "regulatory.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "sources": {
                "access_law": ("DeLand et al. (2025), A global dataset of preferential access "
                               "areas for small-scale fishing, Duke Research Data Repository, CC0"),
                "ssf_guidelines": "FAO, Voluntary Guidelines for Small-Scale Fisheries — Where we work",
                "faolex": "FAOLEX Database, FAO — linked, not harvested",
            },
            "missing": {
                "sdg_14_b_1": ("SDG indicator 14.b.1, the degree of application of a legal framework "
                               "recognising access rights for small-scale fisheries, is the one "
                               "comparable global measure of policy adoption. It is not yet in this "
                               "atlas."),
            },
            "count": len(out),
            "countries": out,
        }, f, indent=1)

    withlaw = sum(1 for v in out.values() if v.get("access_law"))
    withurl = sum(1 for v in out.values() if (v.get("access_law") or {}).get("url"))
    print(f"  wrote {len(out)} countries")
    print(f"    {withlaw} with a named access law ({withurl} with a direct link)")
    print(f"    {len(FAO_SSF_IMPLEMENTATION)} with active FAO SSF Guidelines work")
    print(f"    all with a FAOLEX search link")
    print("\n  sample:")
    for iso in ["IDN", "PHL", "CHL"]:
        e = out.get(iso, {})
        law = (e.get("access_law") or {}).get("name")
        print(f"    {iso} {e.get('country','')[:18]:<20}law={str(law)[:44]:<46}"
              f"fao={'yes' if e.get('ssf_guidelines') else 'no'}")


if __name__ == "__main__":
    main()
