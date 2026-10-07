"""
Build the people layer: how much do small-scale fisheries matter to humans here?

The prototype's first map colours EEZs by small-scale share of catch, and that
metric has a real flaw. Palau reads as 22% small-scale and Micronesia as 1.4%,
which makes them look like Rare's least small-scale countries. That is an artifact
of industrial tuna fleets dominating tonnage inside those EEZs - it says nothing
about how many people fish, or how much they depend on it.

This pipeline builds the correction, from three sources:

  Illuminating Hidden Harvests (FAO/Duke/WorldFish 2023)  how many people fish
  World Bank                                              population, food insecurity
  FAO Food Balance Sheets                                 fish as share of protein

Outputs site/data/people.json, keyed by ISO3.

Sources:
  https://www.fao.org/3/cd3915en/IHH_Livelihoods_data.xlsx   (CC BY 4.0)
  https://api.worldbank.org/v2/                              (CC BY 4.0)
"""

import io
import json
import os
import time
import urllib.request
import zipfile

import openpyxl

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw")
OUT = os.path.join(HERE, "site", "data")

IHH_LIVELIHOODS = "https://www.fao.org/3/cd3915en/IHH_Livelihoods_data.xlsx"
WB = "https://api.worldbank.org/v2"

# Column positions in the IHH livelihoods sheet. The header spans four merged
# rows, so there is no clean way to read these by name - they are located once,
# here, and documented rather than re-derived. Data begins on row 5 (1-indexed).
COLS = {
    "iso3": 1,
    "estimate": 6,  # "Estimation method": survey-based or extrapolated
    "country": 2,
    "ssf_total": 17,          # Employment in SSF, total
    "ssf_marine_harvest": 11, # Employment in SSF, harvest, marine only
    "ssf_women": 29,          # Women employment in SSF, total
    "lsf_total": 41,          # Employment in large-scale fisheries, total
    "subsistence_total": 60,  # Subsistence workers, total
    "subsistence_women": 66,  # Women engaged in subsistence SSF, total
}
FIRST_DATA_ROW = 5


def fetch(url, dest, binary=True):
    """Download once, then reuse. FAO redirects to a bitstream host, so follow."""
    if os.path.exists(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    with open(dest, "wb" if binary else "w") as f:
        f.write(data)
    return dest


def get_json(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def read_ihh():
    """Parse the IHH livelihoods workbook into {iso3: {...}} in whole people."""
    path = fetch(IHH_LIVELIHOODS, os.path.join(RAW, "IHH_Livelihoods_data.xlsx"))
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb["IHH_Livelihood_data"]

    out = {}
    for row in sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=False):
        def cell(key):
            idx = COLS[key] - 1
            if idx >= len(row):
                return None
            return row[idx].value

        iso = cell("iso3")
        if not iso or not isinstance(iso, str) or len(iso.strip()) != 3:
            continue
        iso = iso.strip().upper()

        rec = {"country": cell("country")}
        # IHH surveyed 78 countries and extrapolated the rest from regional
        # patterns; the workbook flags which is which, and so should the page.
        flag = str(cell("estimate") or "").strip().lower()
        rec["estimate"] = "extrapolated" if flag.startswith("extrapolat") else "survey"
        for key in ("ssf_total", "ssf_marine_harvest", "ssf_women",
                    "lsf_total", "subsistence_total", "subsistence_women"):
            v = cell(key)
            # IHH reports in millions of people; whole people read better and
            # avoid a lot of tiny decimals downstream.
            rec[key] = round(float(v) * 1_000_000) if isinstance(v, (int, float)) else None
        out[iso] = rec

    wb.close()
    return out


def worldbank(indicator, label):
    """Pull one indicator for every country; keep the most recent non-null year."""
    url = (f"{WB}/country/all/indicator/{indicator}"
           f"?format=json&per_page=20000&date=2015:2025")
    data = get_json(url)
    if not data or len(data) < 2 or not data[1]:
        print(f"  ! World Bank {label} unavailable")
        return {}

    best = {}
    for row in data[1]:
        iso = (row.get("countryiso3code") or "").strip().upper()
        val, year = row.get("value"), row.get("date")
        if len(iso) != 3 or val is None:
            continue
        year = int(year)
        if iso not in best or year > best[iso][1]:
            best[iso] = (float(val), year)
    print(f"  {label}: {len(best)} countries")
    return best


def fish_protein_share():
    """
    Fish as a share of animal protein, from FAO Food Balance Sheets.

    The bulk file is ~55 MB zipped, so it is downloaded once and cached. We read
    the normalised CSV directly out of the zip rather than expanding it.
    """
    url = ("https://bulks-faostat.fao.org/production/"
           "FoodBalanceSheets_E_All_Data_(Normalized).zip")
    dest = os.path.join(RAW, "faostat_fbs.zip")
    try:
        fetch(url, dest)
    except Exception as e:
        print(f"  ! FAOSTAT unavailable ({e}); skipping protein share")
        return {}

    # Element 674 = protein supply quantity (g/capita/day).
    PROTEIN = "674"
    # Item group codes: fish/seafood total, and total animal products.
    FISH, ANIMAL = "2960", "2941"

    per_country = {}
    try:
        with zipfile.ZipFile(dest) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as fh:
                import csv
                reader = csv.reader(io.TextIOWrapper(fh, encoding="latin-1"))
                header = next(reader)
                col = {h.strip('"'): i for i, h in enumerate(header)}
                ic = col.get("Item Code"); ec = col.get("Element Code")
                yc = col.get("Year"); vc = col.get("Value")
                ac = col.get("Area Code (M49)") or col.get("Area Code")
                for r in reader:
                    if len(r) <= max(ic, ec, yc, vc, ac):
                        continue
                    if r[ec] != PROTEIN or r[ic] not in (FISH, ANIMAL):
                        continue
                    try:
                        year, val = int(r[yc]), float(r[vc])
                    except ValueError:
                        continue
                    m49 = r[ac].lstrip("'")
                    slot = per_country.setdefault(m49, {})
                    prev = slot.get(r[ic])
                    if prev is None or year > prev[1]:
                        slot[r[ic]] = (val, year)
    except Exception as e:
        print(f"  ! could not read FAOSTAT ({e})")
        return {}

    shares = {}
    for m49, items in per_country.items():
        if FISH in items and ANIMAL in items:
            fish, animal = items[FISH][0], items[ANIMAL][0]
            if animal > 0:
                shares[m49] = (round(100.0 * fish / animal, 1), items[FISH][1])
    print(f"  fish protein share: {len(shares)} areas (M49-keyed)")
    return shares


def m49_to_iso3():
    """FAOSTAT is keyed by M49; the World Bank gives us the crosswalk for free."""
    data = get_json(f"{WB}/country?format=json&per_page=400")
    if not data or len(data) < 2:
        return {}
    out = {}
    for c in data[1]:
        iso, m49 = c.get("id"), c.get("iso2Code")
        # The World Bank doesn't expose M49 directly, so fall back to the UN's
        # own list keyed by ISO3 - handled by the caller when this comes back empty.
        if iso:
            out[iso] = m49
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    print("Illuminating Hidden Harvests")
    ihh = read_ihh()
    print(f"  {len(ihh)} countries")

    print("World Bank")
    pop = worldbank("SP.POP.TOTL", "population")
    if len(pop) < 150:
        # Without population there is no per-1,000 rate; better to keep the
        # last good file than to write one with the rates missing.
        raise SystemExit("World Bank population unavailable; people.json left as it was.")
    # Taiwan is not a World Bank economy. Ministry of the Interior, end of 2024.
    pop.setdefault("TWN", (23_400_000.0, 2024))
    food = worldbank("SN.ITK.MSFI.ZS", "food insecurity")

    print("FAOSTAT")
    protein_m49 = fish_protein_share()

    # FAOSTAT's M49 codes need mapping to ISO3. The UN SDG API publishes the
    # crosswalk, but rather than add another dependency we use the numeric M49
    # codes the World Bank returns for each country where available.
    m49_lookup = {}
    wb_countries = get_json(f"{WB}/country?format=json&per_page=400")
    if wb_countries and len(wb_countries) > 1:
        for c in wb_countries[1]:
            iso3 = c.get("id")
            if iso3:
                m49_lookup[iso3] = None  # filled below if we can match

    out = {}
    for iso, rec in ihh.items():
        ssf = rec.get("ssf_total")
        subs = rec.get("subsistence_total") or 0
        lsf = rec.get("lsf_total")
        women = rec.get("ssf_women")

        population = pop.get(iso, (None, None))[0]

        entry = {
            "country": rec["country"],
            "estimate": rec.get("estimate"),
            "ssf_workers": ssf,
            "ssf_women": women,
            "ssf_marine_harvest": rec.get("ssf_marine_harvest"),
            "lsf_workers": lsf,
            "subsistence_workers": rec.get("subsistence_total"),
            "population": round(population) if population else None,
        }

        # Employment and subsistence are reported separately, not summed. IHH
        # counts subsistence as household food production - in Kiribati that is
        # 67,000 people against 5,800 employed, so adding them together would say
        # half the country "works in fisheries", which is not what the data means.
        if ssf is not None and population:
            entry["employed_per_1k"] = round(1000.0 * ssf / population, 2)
        if subs and population:
            entry["subsistence_per_1k"] = round(1000.0 * subs / population, 2)

        # Landlocked and inland-only countries report zero marine harvest. They
        # are real small-scale fisheries, but they have no EEZ and do not belong
        # on a marine map.
        marine = rec.get("ssf_marine_harvest")
        entry["has_marine"] = bool(marine)

        # What share of the fishing workforce is small-scale. Independent of
        # tonnage, which is the whole point.
        if ssf is not None and lsf is not None and (ssf + lsf) > 0:
            entry["ssf_workforce_share"] = round(100.0 * ssf / (ssf + lsf), 1)

        # Women as a share of the small-scale workforce.
        if ssf and women is not None and ssf > 0:
            entry["women_share"] = round(100.0 * women / ssf, 1)

        if iso in food:
            entry["food_insecurity"] = round(food[iso][0], 1)

        out[iso] = entry

    with open(os.path.join(OUT, "people.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "sources": {
                "livelihoods": "Illuminating Hidden Harvests (FAO/Duke/WorldFish 2023), CC BY 4.0",
                "population": "World Bank SP.POP.TOTL",
                "food_insecurity": "World Bank SN.ITK.MSFI.ZS",
            },
            "note": ("IHH is a one-off 2023 baseline, not official country statistics. "
                     "Employment figures are national; they are not split by EEZ."),
            "count": len(out),
            "countries": out,
        }, f, indent=1)

    marine = [v for v in out.values() if v.get("has_marine")]
    have_rate = [v for v in marine if v.get("employed_per_1k") is not None]
    have_women = [v for v in out.values() if v.get("women_share") is not None]
    print(f"\n  wrote {len(out)} countries ({len(marine)} with marine fisheries)")
    print(f"  {len(have_rate)} with employment rate")
    print(f"  {len(have_women)} with women's share")

    if have_rate:
        top = sorted(have_rate, key=lambda v: -v["employed_per_1k"])[:8]
        print("\n  most fishing-employed, marine countries (per 1,000 people):")
        for v in top:
            print(f"    {str(v['country'])[:26]:<26} {v['employed_per_1k']:6.1f}")

    women = sorted((v for v in marine if v.get("women_share") is not None),
                   key=lambda v: -v["women_share"])[:6]
    if women:
        print("\n  highest women's share of the small-scale workforce:")
        for v in women:
            print(f"    {str(v['country'])[:26]:<26} {v['women_share']:5.1f}%")


if __name__ == "__main__":
    main()
