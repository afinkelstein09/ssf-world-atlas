"""
Build the ecosystem layer: what state is the sea these fisheries depend on in?

Catch says what came out of the water. This script collects what is known about
what is left in it, per ocean zone wherever the source allows:

  stock status        Sea Around Us: the share of fished stocks that are
                      developing, exploited, over-exploited, collapsed or
                      rebuilding. Read from catch trends, NOT from stock
                      assessments, and the page has to say so.
  pressure            Sea Around Us: the unreported share of the catch, the
                      discarded share, and the largest catches by taxon.
  the zone itself     Sea Around Us: shelf area, inshore fishing area, share of
                      the world's tropical coral reefs, primary production.
  threatened species  OBIS: species with an IUCN Red List category of Vulnerable,
                      Endangered or Critically Endangered that have been
                      recorded inside the zone. Queried with a simplified
                      outline of the zone itself, so a territory gets its own
                      answer rather than its parent country's.

Two national figures ride along, keyed by ISO3:

  mangroves           Ocean Health Index habitat layer, 1996-2020
  protected waters    World Bank ER.MRN.PTMR.ZS, % of territorial waters

Outputs site/data/ecosystem.json.

Sources:
  https://api.seaaroundus.org/api/v1/eez/...              Sea Around Us, cite per policy
  https://api.obis.org/v3/checklist/redlist               OBIS, CC BY / CC0 by dataset
  https://github.com/OHI-Science/ohi-global               Ocean Health Index, cite
  https://api.worldbank.org/v2/                           World Bank, CC BY 4.0

A species count is a count of what has been looked for and written down. Waters
that have been surveyed more have longer lists, so the number is never painted
on the map - it lives in the panel, next to that caveat.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw")
OUT = os.path.join(HERE, "site", "data")

SAU = "https://api.seaaroundus.org/api/v1"
OBIS = "https://api.obis.org/v3/checklist/redlist"
OHI = "https://raw.githubusercontent.com/OHI-Science/ohi-global/draft/eez"
WB_MPA = ("https://api.worldbank.org/v2/country/all/indicator/ER.MRN.PTMR.ZS"
          "?format=json&per_page=20000&mrnev=1")

WINDOW = 5
STATUS_ORDER = ["Rebuilding", "Developing", "Exploited", "Over-exploited", "Collapsed"]


def get_bytes(url, tries=3, timeout=120):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return e.code, b""
            if attempt == tries - 1:
                return e.code, b""
        except Exception:
            if attempt == tries - 1:
                return None, b""
        time.sleep(2 * (attempt + 1))
    return None, b""


def get_json(url, **kw):
    status, raw = get_bytes(url, **kw)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def cache_path(kind, key):
    folder = os.path.join(RAW, kind)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.json")


def cached_json(kind, key, url, keep=None):
    """Fetch once, keep on disk. `keep` trims a bulky response before caching."""
    path = cache_path(kind, key)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    data = get_json(url)
    if data is None:
        return None
    if keep:
        data = keep(data)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


# --------------------------------------------------------------------------
# Sea Around Us

def series_map(data):
    out = {}
    for s in (data or {}).get("data") or []:
        clean = {}
        for pair in s.get("values") or []:
            if not pair or len(pair) < 2 or pair[1] is None:
                continue
            clean[int(pair[0])] = float(pair[1])
        if clean:
            out[s.get("key")] = clean
    return out


def window_shares(series):
    """Each key's share of the total over the last WINDOW years of record.
    A key absent from a year counted nothing that year (fixed denominator)."""
    years = {y for m in series.values() for y in m}
    if not years:
        return None, None
    last = max(years)
    window = range(last - WINDOW + 1, last + 1)
    means = {k: sum(m.get(y, 0.0) for y in window) / WINDOW for k, m in series.items()}
    total = sum(means.values())
    if total <= 0:
        return None, None
    return {k: 100.0 * v / total for k, v in means.items()}, last


def trim_meta(data):
    d = (data or {}).get("data") or {}
    return {"data": {k: d.get(k) for k in (
        "metrics", "ohi_link", "fishbase_id", "fao_rfb", "intersecting_fao_area_id",
        "estuary_count", "declaration_year", "title")}}


def count_classified(block, n_total):
    """How many populations the latest year's shares are shares OF.

    Sea Around Us gives the year's shares as percentages and, separately, the number
    of populations on record since 1950. The two are not the same: a population with
    no catch in the latest year is on record but not classified that year. The first
    version printed "State of 11 fish populations" over Sudan's bar when the 2019
    shares were eighths - eight populations, not eleven. The shares are published to
    two decimals, so the count they divide into can be recovered in most zones (171 of
    189 at the first run). Where two or more counts fit (59 or 118, say) the first
    value is None, and the smallest and largest fits follow. When the whole year sits
    in one category every count from 1 to n fits, and the range says so."""
    vals = []
    for series in block or []:
        pts = [p for p in (series.get("values") or []) if p and p[1] is not None]
        if pts:
            vals.append(float(pts[-1][1]))
    if not vals or not n_total:
        return None, None
    fits = [d for d in range(1, int(n_total) + 1)
            if all(abs(v * d / 100 - round(v * d / 100)) <= 0.005 * d / 100 + 1e-9 for v in vals)]
    if not fits:
        return None, None, None
    return (fits[0] if len(fits) == 1 else None), fits[0], fits[-1]


def sau_zone(zone):
    rid = zone["region_id"]
    out = {}

    ss = cached_json("eco_stock", rid, f"{SAU}/eez/stock-status/?region_id={rid}")
    d = (ss or {}).get("data") or {}
    n = (d.get("summary") or {}).get("n")
    if n and d.get("nss"):
        def latest(block, raw=None):
            year, vals = None, {}
            for s in block or []:
                pts = [p for p in (s.get("values") or []) if p and p[1] is not None]
                if pts:
                    year = int(pts[-1][0])
                    vals[s.get("key")] = round(float(pts[-1][1]), 1)
                    if raw is not None:
                        raw[s.get("key")] = float(pts[-1][1])
            return year, vals
        raw_count = {}
        y_n, by_count = latest(d.get("nss"), raw_count)
        y_c, by_catch = latest(d.get("css"))
        if by_count and sum(by_count.values()) > 0:
            n_year, n_floor, n_ceil = count_classified(d.get("nss"), n)
            out["stocks"] = {"n": int(n), "year": y_n, "by_count": by_count, "by_catch": by_catch,
                             "n_year": n_year, "n_year_min": n_floor, "n_year_max": n_ceil,
                             # over-exploited + collapsed from the unrounded shares: adding the two
                             # one-decimal shares put Cambodia at 69% when it is 68.5%
                             "depleted_pct": round(raw_count.get("Over-exploited", 0) + raw_count.get("Collapsed", 0), 2)}

    rep, _ = window_shares(series_map(
        cached_json("eco_reporting", rid, f"{SAU}/eez/tonnage/reporting-status/?region_id={rid}")))
    if rep:
        out["unreported_pct"] = round(rep.get("Unreported", 0.0), 1)

    ct, _ = window_shares(series_map(
        cached_json("eco_catchtype", rid, f"{SAU}/eez/tonnage/catchtype/?region_id={rid}")))
    if ct:
        out["discards_pct"] = round(ct.get("Discards", 0.0), 1)

    tx, last = window_shares(series_map(
        cached_json("eco_taxon", rid, f"{SAU}/eez/tonnage/taxon/?region_id={rid}&limit=20")))
    if tx:
        named = [(k, v) for k, v in tx.items() if str(k).strip().lower() != "others"]
        named.sort(key=lambda kv: -kv[1])
        out["top_taxa"] = [{"name": k, "pct": round(v, 1)} for k, v in named[:5] if v >= 0.5]
        out["taxa_year"] = last

    meta = cached_json("eco_meta", rid, f"{SAU}/eez/{rid}", keep=trim_meta)
    m = (meta or {}).get("data") or {}
    metric = {x.get("title"): x.get("value") for x in (m.get("metrics") or [])}
    def num(key, dp=0):
        v = metric.get(key)
        return None if v is None else round(float(v), dp) if dp else round(float(v))
    out["zone"] = {
        "eez_km2": num("EEZ area"),
        "shelf_km2": num("Shelf Area"),
        "ifa_km2": num("Inshore Fishing Area (IFA)"),
        "reef_pct_world": num("Tropical Coral Reefs", 2),
        "primary_production": num("Primary production"),
    }
    if m.get("ohi_link"):
        out["ohi_link"] = m["ohi_link"]
    return zone["name"], out


# --------------------------------------------------------------------------
# OBIS threatened species, queried with the zone's own outline

def ring_area(r):
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


def simplify(pts, tol):
    """Douglas-Peucker, iterative so long coastlines do not hit the recursion limit."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        length2 = (dx * dx + dy * dy) or 1e-18
        best, idx = 0.0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            dist = ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5
            if dist > best:
                best, idx = dist, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def zone_wkt(geom, max_vertices=240):
    """
    The zone's outer rings as WKT, simplified until the request fits in a URL.
    Holes (the land inside an EEZ) are dropped: OBIS records are marine, so the
    landward side does not matter, and the seaward edge moves by at most the
    tolerance returned here.
    """
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    outers = [[(p[0], p[1]) for p in poly[0]] for poly in polys]
    total = sum(ring_area(r) for r in outers) or 1e-9
    outers = [r for r in outers if ring_area(r) >= 0.01 * total]
    tol = 0.02
    while True:
        rings = []
        for r in outers:
            half = len(r) // 2
            s = simplify(r[:half + 1], tol)[:-1] + simplify(r[half:], tol)
            if s[0] != s[-1]:
                s.append(s[0])
            rings.append(s)
        if sum(len(s) for s in rings) <= max_vertices or tol > 2:
            break
        tol *= 1.4
    parts = ["((" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in s) + "))" for s in rings if len(s) >= 4]
    if not parts:
        return None, tol
    wkt = "POLYGON" + parts[0] if len(parts) == 1 else "MULTIPOLYGON(" + ", ".join(parts) + ")"
    return wkt, round(tol, 3)


def group_of(rec):
    """A plain-language group from the WoRMS classification OBIS returns."""
    cls = (rec.get("class") or "").lower()
    order = (rec.get("order") or "").lower()
    phylum = (rec.get("phylum") or "").lower()
    superclass = (rec.get("superclass") or "").lower()
    if order == "testudines":
        return "sea turtles"
    if cls in ("elasmobranchii", "holocephali"):
        return "sharks and rays"
    if cls == "aves":
        return "seabirds and shorebirds"
    if cls == "mammalia":
        return "marine mammals"
    if phylum == "cnidaria":
        return "corals"
    if cls == "holothuroidea":
        return "sea cucumbers"
    if phylum == "mollusca":
        return "molluscs"
    if cls in ("teleostei", "actinopteri", "actinopterygii") or superclass in ("actinopterygii", "pisces"):
        return "bony fish"
    if superclass == "reptilia":
        return "other reptiles"
    return "other"


def obis_zone(args):
    zone, geom = args
    rid = zone["region_id"]
    path = cache_path("obis", rid)
    if os.path.exists(path):
        with open(path) as f:
            return zone["name"], json.load(f)
    wkt, tol = zone_wkt(geom)
    if not wkt:
        return zone["name"], None
    rows, skip, total = [], 0, None
    while True:
        url = f"{OBIS}?size=1000&skip={skip}&geometry={urllib.parse.quote(wkt)}"
        data = get_json(url, timeout=240)
        if data is None:
            return zone["name"], None        # not cached: a later run retries
        total = data.get("total", 0)
        batch = data.get("results") or []
        rows += batch
        skip += len(batch)
        if not batch or skip >= total:
            break
    keep = []
    for r in rows:
        marine = r.get("is_marine") or r.get("is_brackish")
        elsewhere = r.get("is_freshwater") or r.get("is_terrestrial")
        if not marine and elsewhere:
            continue                          # a river fish or a land bird, not these waters
        if r.get("category") not in ("CR", "EN", "VU"):
            continue
        keep.append({"id": r.get("taxonID"), "sci": r.get("scientificName"),
                     "cat": r.get("category"), "records": r.get("records") or 0,
                     "group": group_of(r)})
    rec = {"tolerance_deg": tol, "returned": len(rows), "taxa": keep}
    with open(path, "w") as f:
        json.dump(rec, f)
    return zone["name"], rec


# English names, checked by hand against IUCN Red List and FishBase usage.
#
# The first version asked WoRMS for each species' English name and took the first
# one offered. It labelled the whale shark "Basking shark", the Nassau grouper
# "Hamlet" and the blue whale "Blue rorqual". A wrong name on a threatened species
# is worse than a Latin one, so names now come only from this table, and a species
# that is not in it is shown by its scientific name.
COMMON_NAMES = {
    "Eretmochelys imbricata": "Hawksbill turtle", "Chelonia mydas": "Green turtle",
    "Caretta caretta": "Loggerhead turtle", "Lepidochelys olivacea": "Olive ridley turtle",
    "Lepidochelys kempii": "Kemp's ridley turtle",
    "Sphyrna lewini": "Scalloped hammerhead", "Sphyrna mokarran": "Great hammerhead",
    "Sphyrna corona": "Scalloped bonnethead", "Sphyrna media": "Scoophead",
    "Sphyrna tudes": "Smalleye hammerhead", "Carcharhinus longimanus": "Oceanic whitetip shark",
    "Carcharhinus amblyrhynchos": "Grey reef shark", "Carcharhinus porosus": "Smalltail shark",
    "Carcharhinus falciformis": "Silky shark", "Carcharhinus borneensis": "Borneo shark",
    "Carcharhinus hemiodon": "Pondicherry shark", "Carcharhinus leiodon": "Smoothtooth blacktip shark",
    "Carcharias taurus": "Sand tiger shark", "Odontaspis ferox": "Smalltooth sand tiger",
    "Rhincodon typus": "Whale shark", "Cetorhinus maximus": "Basking shark",
    "Galeorhinus galeus": "Tope shark", "Isurus oxyrinchus": "Shortfin mako", "Isurus paucus": "Longfin mako",
    "Triaenodon obesus": "Whitetip reef shark", "Stegostoma tigrinum": "Zebra shark",
    "Glyphis gangeticus": "Ganges shark", "Isogomphodon oxyrhynchus": "Daggernose shark",
    "Paragaleus pectoralis": "Atlantic weasel shark", "Oxynotus centrina": "Angular roughshark",
    "Centrophorus granulosus": "Gulper shark", "Centrophorus uyato": "Little gulper shark",
    "Centrophorus atromarginatus": "Dwarf gulper shark", "Squalus mitsukurii": "Shortspine spurdog",
    "Pseudoginglymostoma brevicaudatum": "Shorttail nurse shark",
    "Cephaloscyllium fasciatum": "Reticulated swellshark",
    "Hemitriakis leucoperiptera": "Whitefin topeshark", "Hemitriakis japanica": "Japanese topeshark",
    "Mustelus mustelus": "Common smooth-hound", "Mustelus schmitti": "Narrownose smooth-hound",
    "Mustelus mento": "Speckled smooth-hound", "Mustelus whitneyi": "Humpback smooth-hound",
    "Squatina squatina": "Angelshark", "Squatina oculata": "Smoothback angelshark",
    "Squatina aculeata": "Sawback angelshark", "Squatina argentina": "Argentine angelshark",
    "Squatina armata": "Chilean angelshark", "Squatina japonica": "Japanese angelshark",
    "Pristis pectinata": "Smalltooth sawfish", "Pristis pristis": "Largetooth sawfish",
    "Pristis zijsron": "Green sawfish", "Anoxypristis cuspidata": "Narrow sawfish",
    "Glaucostegus cemiculus": "Blackchin guitarfish", "Glaucostegus granulatus": "Granulated guitarfish",
    "Glaucostegus thouin": "Clubnose guitarfish", "Glaucostegus halavi": "Halavi guitarfish",
    "Glaucostegus obtusus": "Widenose guitarfish", "Glaucostegus typus": "Giant guitarfish",
    "Rhinobatos rhinobatos": "Common guitarfish", "Rhinobatos albomaculatus": "Whitespotted guitarfish",
    "Rhinobatos schlegelii": "Brown guitarfish", "Rhinobatos irvinei": "Spineback guitarfish",
    "Rhinobatos annandalei": "Annandale's guitarfish", "Acroteriobatus variegatus": "Stripenose guitarfish",
    "Rhina ancylostomus": "Bowmouth guitarfish", "Rhynchobatus australiae": "Bottlenose wedgefish",
    "Rhynchobatus djiddensis": "Whitespotted wedgefish", "Rhynchobatus cooki": "Clown wedgefish",
    "Rhynchobatus springeri": "Broadnose wedgefish",
    "Myliobatis aquila": "Common eagle ray", "Aetomylaeus bovinus": "Bull ray",
    "Aetomylaeus vespertilio": "Ornate eagle ray", "Aetobatus narinari": "Spotted eagle ray",
    "Aetobatus ocellatus": "Ocellated eagle ray", "Rhinoptera marginata": "Lusitanian cownose ray",
    "Mobula birostris": "Giant manta ray", "Mobula thurstoni": "Bentfin devil ray",
    "Mobula tarapacana": "Sicklefin devil ray", "Gymnura altavela": "Spiny butterfly ray",
    "Dipturus batis": "Blue skate", "Dipturus intermedius": "Flapper skate",
    "Leucoraja melitensis": "Maltese skate", "Leucoraja circularis": "Sandy skate",
    "Leucoraja ocellata": "Winter skate", "Raja radula": "Rough ray",
    "Bathyraja griseocauda": "Graytail skate", "Atlantoraja castelnaui": "Spotback skate",
    "Sympterygia acuta": "Bignose fanskate", "Tetronarce puelcha": "Argentine torpedo",
    "Torpedo panthera": "Panther electric ray", "Dasyatis pastinaca": "Common stingray",
    "Himantura uarnak": "Honeycomb stingray", "Hypanus longus": "Longtail stingray",
    "Urotrygon microphthalmum": "Smalleyed round stingray", "Maculabatis bineeshi": "Shorttail whipray",
    "Anguilla anguilla": "European eel", "Anguilla rostrata": "American eel", "Anguilla japonica": "Japanese eel",
    "Epinephelus striatus": "Nassau grouper", "Cheilinus undulatus": "Humphead wrasse",
    "Gadus morhua": "Atlantic cod", "Hippoglossoides platessoides": "American plaice",
    "Coryphaenoides rupestris": "Roundnose grenadier", "Acipenser sturio": "European sturgeon",
    "Huso huso": "Beluga sturgeon", "Alosa alosa": "Allis shad", "Latimeria chalumnae": "Coelacanth",
    "Brachionichthys hirsutus": "Spotted handfish", "Sebastes paucispinis": "Bocaccio",
    "Sebastolobus alascanus": "Shortspine thornyhead", "Stereolepis gigas": "Giant sea bass",
    "Larimichthys crocea": "Large yellow croaker", "Trachurus trachurus": "Atlantic horse mackerel",
    "Thunnus obesus": "Bigeye tuna", "Istiophorus platypterus": "Sailfish",
    "Balistes capriscus": "Grey triggerfish", "Pomatomus saltatrix": "Bluefish",
    "Sardinella maderensis": "Madeiran sardinella", "Lethrinus mahsena": "Sky emperor",
    "Chrysoblephus cristiceps": "Dageraad", "Polysteganus undulosus": "Seventy-four seabream",
    "Pseudochaenichthys georgianus": "South Georgia icefish", "Chaenocephalus aceratus": "Blackfin icefish",
    "Coregonus huntsmani": "Atlantic whitefish", "Coregonus lavaretus": "European whitefish",
    "Takifugu chinensis": "Chinese puffer", "Parahucho perryi": "Sakhalin taimen",
    "Pseudocaranx chilensis": "Juan Fernandez trevally", "Coilia mystus": "Osbeck's grenadier anchovy",
    "Coilia nasus": "Japanese grenadier anchovy", "Scorpaena mellissii": "Melliss's scorpionfish",
    "Canthigaster sanctaehelenae": "St Helena sharpnose pufferfish",
    "Balaenoptera musculus": "Blue whale", "Balaenoptera borealis": "Sei whale",
    "Balaenoptera physalus": "Fin whale", "Physeter macrocephalus": "Sperm whale",
    "Eubalaena glacialis": "North Atlantic right whale", "Eubalaena japonica": "North Pacific right whale",
    "Phocoena sinus": "Vaquita", "Sousa plumbea": "Indian Ocean humpback dolphin",
    "Sousa teuszii": "Atlantic humpback dolphin", "Ursus maritimus": "Polar bear",
    "Enhydra lutris": "Sea otter", "Odobenus rosmarus": "Walrus",
    "Pterodroma magentae": "Magenta petrel", "Pterodroma phaeopygia": "Galápagos petrel",
    "Pterodroma incerta": "Atlantic petrel", "Pterodroma defilippiana": "De Filippi's petrel",
    "Pterodroma externa": "Juan Fernández petrel", "Pseudobulweria aterrima": "Mascarene petrel",
    "Puffinus mauretanicus": "Balearic shearwater", "Puffinus yelkouan": "Yelkouan shearwater",
    "Phoebetria fusca": "Sooty albatross", "Phoebastria irrorata": "Waved albatross",
    "Thalassarche chrysostoma": "Grey-headed albatross",
    "Thalassarche chlororhynchos": "Atlantic yellow-nosed albatross",
    "Thalassarche carteri": "Indian yellow-nosed albatross", "Diomedea dabbenena": "Tristan albatross",
    "Diomedea exulans": "Wandering albatross", "Diomedea sanfordi": "Northern royal albatross",
    "Diomedea amsterdamensis": "Amsterdam albatross", "Fregetta maoriana": "New Zealand storm petrel",
    "Pachyptila macgillivrayi": "MacGillivray's prion", "Papasula abbotti": "Abbott's booby",
    "Morus capensis": "Cape gannet", "Leucocarbo onslowi": "Chatham shag",
    "Spheniscus demersus": "African penguin", "Eudyptes sclateri": "Erect-crested penguin",
    "Eudyptes moseleyi": "Northern rockhopper penguin", "Rissa tridactyla": "Black-legged kittiwake",
    "Clangula hyemalis": "Long-tailed duck", "Melanitta fusca": "Velvet scoter",
    "Polysticta stelleri": "Steller's eider", "Branta ruficollis": "Red-breasted goose",
    "Podiceps auritus": "Horned grebe", "Platalea minor": "Black-faced spoonbill",
    "Pluvialis squatarola": "Grey plover", "Calidris ferruginea": "Curlew sandpiper",
    "Calidris tenuirostris": "Great knot", "Calidris falcinellus": "Broad-billed sandpiper",
    "Numenius madagascariensis": "Far Eastern curlew", "Vanellus gregarius": "Sociable lapwing",
    "Charadrius obscurus": "New Zealand dotterel",
    "Acropora palmata": "Elkhorn coral", "Acropora cervicornis": "Staghorn coral",
    "Pseudodiploria strigosa": "Symmetrical brain coral", "Diploria labyrinthiformis": "Grooved brain coral",
    "Siderastrea siderea": "Massive starlet coral", "Madracis decactis": "Ten-ray star coral",
    "Meandrina meandrites": "Maze coral", "Dendrogyra cylindrus": "Pillar coral",
    "Agaricia tenuifolia": "Thin leaf lettuce coral", "Agaricia lamarcki": "Lamarck's sheet coral",
    "Agaricia humilis": "Lowrelief lettuce coral", "Helioseris cucullata": "Sunray lettuce coral",
    "Scolymia cubensis": "Artichoke coral", "Millepora complanata": "Blade fire coral",
    "Millepora squarrosa": "Box fire coral", "Millepora dichotoma": "Net fire coral",
    "Pocillopora verrucosa": "Rasp coral", "Pocillopora meandrina": "Cauliflower coral",
    "Pocillopora damicornis": "Lace coral", "Montipora capitata": "Rice coral",
    "Ctenella chagius": "Chagos brain coral", "Mussismilia braziliensis": "Brazilian brain coral",
    "Cladocora caespitosa": "Cushion coral", "Tubastraea floreana": "Floreana coral",
    "Rhizopsammia wellingtoni": "Wellington's solitary coral",
    "Tridacna gigas": "Giant clam", "Pinna nobilis": "Noble pen shell",
    "Haliotis rufescens": "Red abalone", "Haliotis cracherodii": "Black abalone",
    "Haliotis fulgens": "Green abalone", "Haliotis sorenseni": "White abalone",
    "Haliotis kamtschatkana": "Pinto abalone", "Pycnopodia helianthoides": "Sunflower sea star",
    "Thelenota ananas": "Prickly redfish", "Holothuria nobilis": "Black teatfish",
    "Holothuria whitmaei": "Black teatfish", "Holothuria scabra": "Sandfish",
    "Actinopyga mauritiana": "Surf redfish", "Apostichopus japonicus": "Japanese sea cucumber",
    "Tachypleus tridentatus": "Tri-spine horseshoe crab",
}


# Species in the OBIS answers that do not live in the sea. The zone outline is
# queried without its land holes (see zone_wkt), so a record made on the coast or
# an island inside it comes back too, and WoRMS flags most birds "marine" whether
# they are albatrosses or steppe lapwings. The first build named the sociable
# lapwing, a bird of the Central Asian steppe, among Germany's threatened marine
# species. Coastal animals stay: shorebirds that feed on tidal flats, sea ducks,
# mangroves, crocodiles, anchialine cave crustaceans. Gone are the species that
# only live in fresh water or on land. Checked by hand against the IUCN Red List.
NOT_MARINE = {
    # birds of steppe, river and marsh
    "Vanellus gregarius", "Branta ruficollis", "Anser erythropus", "Ardeola idae",
    "Sterna aurantia", "Sterna acuticauda", "Rynchops albicollis",
    # a dragonfly and a freshwater plant
    "Orthetrum poecilops", "Alisma wahlenbergii",
    # freshwater fish
    "Atractosteus tristoechus", "Lampetra lanceolata", "Channa orientalis", "Bagarius bagarius",
    "Wallago attu", "Cyprinodon tularosa", "Salvelinus confluentus", "Hucho taimen",
    "Acheilognathus melanogaster", "Horadandia atukorali", "Aplocheilus dayi", "Cirrhinus cirrhosus",
    "Pseudohemiculter dispar", "Horabagrus brachysoma", "Nannoperca obscura", "Pseudomugil mellis",
    "Ptychochromis oligacanthus", "Ptychochromis inornatus", "Silhouettea sibayi", "Gobiomorphus hubbsi",
    "Limia rivasi", "Dermogenys orientalis",
    # a hillstream loach and a river damselfish, found by a second review
    "Plesiomyzon baotingensis", "Neopomacentrus aquadulcis",
    # the yellow-spotted Amazon river turtle, which OBIS holds from aquarium records
    "Podocnemis unifilis",
}
# Turtles that are not sea turtles but do live on the coast: kept, filed with the
# other reptiles rather than with the green and hawksbill turtles. group_of() files
# every turtle as a sea turtle because the family is not kept in the cache.
REGROUP = {"Malaclemys terrapin": "other reptiles",
           # sturgeons and coelacanths are fish; group_of() missed their classes
           "Acipenser sturio": "bony fish", "Acipenser oxyrinchus": "bony fish", "Huso huso": "bony fish",
           "Latimeria chalumnae": "bony fish", "Latimeria menadoensis": "bony fish"}

# Records OBIS places far outside a species' known range: a museum or dataset with
# bad coordinates, not an animal in these waters. The first build showed a Tasmanian
# spotted handfish as a critically endangered chip for Finland and Poland, and
# counted a polar bear, a walrus, a sea otter and a vaquita in India's waters. Like
# NOT_MARINE this is the clearest cases noticed so far (an audit on 6 Oct 2026), not
# a guarantee that the lists are clean, and the page says so.
#   species -> the only zones it is kept in
RANGE_ONLY = {
    "Brachionichthys hirsutus": {"Australia"},                     # Tasmania only
    "Phocoena sinus": {"Mexico (Pacific)"},                        # vaquita, Gulf of California
    "Porites sverdrupi": {"Mexico (Pacific)"},                     # Gulf of California
    "Haliotis sorenseni": {"USA (West Coast)", "Mexico (Pacific)"},  # white abalone
}
#   species -> zones it is dropped from
OUT_OF_RANGE = {
    "Pristis pectinata": {"China", "India (mainland)", "Oman", "Philippines", "Réunion (France)",   # Atlantic only
                          "Saudi Arabia (Red Sea)", "Taiwan", "Viet Nam", "Yemen (Socotra)", "Mozambique",
                          "South Africa (Indian Ocean Coast)", "Costa Rica (Pacific)"},
    "Madracis decactis": {"Crete (Greece)", "Svalbard Isl. (Norway)", "France (Atlantic Coast)"},
    "Montipora peltiformis": {"Poland", "Crete (Greece)"},
    "Hemitriakis japanica": {"Crete (Greece)", "Denmark (North Sea)", "France (Atlantic Coast)", "Slovenia",
                             "Sweden (West Coast)", "United Kingdom (UK)"},
    "Eubalaena glacialis": {"Australia", "India (mainland)", "South Africa (Atlantic and Cape)"},
    "Enhydra lutris": {"India (mainland)", "Norway"},
    # one set of two or three records each, all placed in India's waters
    **{sp: {"India (mainland)"} for sp in (
        "Latimeria chalumnae", "Anguilla anguilla", "Anguilla rostrata", "Gadus morhua", "Odobenus rosmarus",
        "Ursus maritimus", "Trichechus manatus", "Thunnus maccoyii", "Callorhinus ursinus", "Squalus acanthias")},
}


def misplaced(sci, zone):
    if sci in RANGE_ONLY and zone not in RANGE_ONLY[sci]:
        return True
    return zone in OUT_OF_RANGE.get(sci, ())


def pick_species(taxa, n=5):
    """Up to three critically endangered species first, then endangered, then
    vulnerable - each by how often it has been recorded here, so the names
    shown are the ones people actually meet in these waters."""
    rank = {"CR": 0, "EN": 1, "VU": 2}
    crs = sorted((t for t in taxa if t["cat"] == "CR"), key=lambda t: -t["records"])[:3]
    rest = sorted((t for t in taxa if t not in crs), key=lambda t: (rank[t["cat"]], -t["records"]))
    return (crs + rest)[:n]


# --------------------------------------------------------------------------
# National context

def mangroves():
    _, raw = get_bytes(f"{OHI}/layers/hab_mangrove_extent.csv")
    _, reg = get_bytes(f"{OHI}/spatial/regions_list.csv")
    if not raw or not reg:
        return {}
    iso_of = {r["rgn_id"]: r["eez_iso3"] for r in csv.DictReader(io.StringIO(reg.decode("utf-8")))
              if r.get("eez_iso3")}
    by_iso = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        iso = iso_of.get(r["rgn_id"])
        if not iso:
            continue
        try:
            by_iso.setdefault(iso, {}).setdefault(int(r["year"]), 0.0)
            by_iso[iso][int(r["year"])] += float(r["km2"])
        except ValueError:
            continue
    out = {}
    for iso, years in by_iso.items():
        first, last = min(years), max(years)
        if years[last] < 1 and years[first] < 1:
            continue                           # no mangroves to speak of
        rec = {"km2": round(years[last]), "year": last, "base_km2": round(years[first]), "base_year": first}
        if years[first] >= 1:
            rec["change_pct"] = round(100.0 * (years[last] / years[first] - 1), 1)
        out[iso] = rec
    return out


def protected_waters():
    data = get_json(WB_MPA)
    out = {}
    for row in (data[1] if isinstance(data, list) and len(data) > 1 else []) or []:
        iso, val = row.get("countryiso3code"), row.get("value")
        if iso and val is not None:
            out[iso] = {"pct": round(float(val), 1), "year": int(row.get("date"))}
    return out


# --------------------------------------------------------------------------

def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "countries.json")) as f:
        zones = json.load(f)["countries"]
    with open(os.path.join(OUT, "eez.geojson")) as f:
        geoms = {ft["properties"]["name"]: ft["geometry"] for ft in json.load(f)["features"]}

    print(f"Sea Around Us ecosystem products for {len(zones)} zones")
    started = time.time()
    eco = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (name, rec) in enumerate(pool.map(sau_zone, zones), 1):
            eco[name] = rec
            if i % 40 == 0 or i == len(zones):
                print(f"  {i}/{len(zones)}  ({time.time() - started:.0f}s)")

    print("OBIS threatened species, one query per zone outline")
    started = time.time()
    jobs = [(z, geoms[z["name"]]) for z in zones if z["name"] in geoms]
    obis = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (name, rec) in enumerate(pool.map(obis_zone, jobs), 1):
            obis[name] = rec
            if i % 40 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  ({time.time() - started:.0f}s)")

    shown, dropped, strays = {}, 0, 0
    for name, rec in obis.items():
        if rec:
            dropped += sum(1 for t in rec["taxa"] if t["sci"] in NOT_MARINE)
            strays += sum(1 for t in rec["taxa"] if misplaced(t["sci"], name))
            rec["taxa"] = [dict(t, group=REGROUP.get(t["sci"], t["group"])) for t in rec["taxa"]
                           if t["sci"] not in NOT_MARINE and not misplaced(t["sci"], name)]
        if rec and rec["taxa"]:
            shown[name] = pick_species(rec["taxa"])
    if dropped:
        print(f"  left out {dropped} records of species that live in fresh water or on land")
    if strays:
        print(f"  left out {strays} zone records far outside the species' known range")
    failed = []
    for name, rec in obis.items():
        if rec is None:
            failed.append(name)
            continue
        taxa = rec["taxa"]
        cats = {"CR": 0, "EN": 0, "VU": 0}
        groups, by_group = {}, {}
        for t in taxa:
            cats[t["cat"]] += 1
            groups[t["group"]] = groups.get(t["group"], 0) + 1
            by_group.setdefault(t["group"], {"CR": 0, "EN": 0, "VU": 0})[t["cat"]] += 1
        species = []
        for t in shown.get(name, []):
            species.append({"sci": t["sci"], "common": COMMON_NAMES.get(t["sci"]),
                            "cat": t["cat"], "records": t["records"], "id": t["id"]})
        eco.setdefault(name, {})["threatened"] = {
            "total": len(taxa), "cr": cats["CR"], "en": cats["EN"], "vu": cats["VU"],
            "groups": sorted(groups.items(), key=lambda kv: -kv[1]),
            # the same groups again, each split by Red List category, for the bars
            "by_group": [[g, by_group[g]] for g, _ in sorted(groups.items(), key=lambda kv: -kv[1])],
            "species": species, "tolerance_deg": rec["tolerance_deg"],
        }

    print("National context: mangroves (Ocean Health Index), protected waters (World Bank)")
    mang, mpa = mangroves(), protected_waters()
    # A failed download must not quietly erase figures the page already shows.
    prev_path = os.path.join(OUT, "ecosystem.json")
    if (not mang or not mpa) and os.path.exists(prev_path):
        with open(prev_path) as f:
            prev = (json.load(f).get("countries") or {})
        if not mang:
            print("  ! mangrove download failed; keeping the previous figures")
            mang = {iso: r["mangrove"] for iso, r in prev.items() if r.get("mangrove")}
        if not mpa:
            print("  ! protected-waters download failed; keeping the previous figures")
            mpa = {iso: r["mpa"] for iso, r in prev.items() if r.get("mpa")}
    print(f"  mangroves {len(mang)} countries, protected waters {len(mpa)} countries")
    national = {}
    for iso in sorted(set(mang) | set(mpa)):
        rec = {}
        if iso in mang:
            rec["mangrove"] = mang[iso]
        if iso in mpa:
            rec["mpa"] = mpa[iso]
        national[iso] = rec

    with open(os.path.join(OUT, "ecosystem.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "sources": {
                "stocks": "Sea Around Us stock-status plots (catch-based; Kleisner et al. 2013)",
                "pressure": "Sea Around Us, catch by reporting status, catch type and taxon",
                "zone": "Sea Around Us EEZ metrics",
                "threatened": "OBIS checklist of IUCN Red List species (CR, EN, VU) recorded inside the zone outline, coast and islands included; the freshwater and land species noticed so far are left out by hand (NOT_MARINE); English names from a hand-checked table",
                "mangrove": "Ocean Health Index habitat layer hab_mangrove_extent",
                "mpa": "World Bank ER.MRN.PTMR.ZS, marine protected areas as % of territorial waters",
            },
            "notes": {
                "stocks": "Stock status is inferred from each stock's catch history relative to its peak, not from stock assessments. n is the number of populations on record since 1950; n_year is how many the year's shares divide into (null where more than one count fits the published shares; n_year_min and n_year_max are then the smallest and largest fits, and a year that sits wholly in one category fits every count from 1 to n).",
                "threatened": "A count of species that have been recorded and assessed. More surveying means a longer list. The outline queried includes the zone's coast and islands.",
            },
            "status_order": STATUS_ORDER,
            "count": len(eco),
            "zones": eco,
            "countries": national,
        }, f)

    have_stock = sum(1 for v in eco.values() if v.get("stocks"))
    have_sp = sum(1 for v in eco.values() if v.get("threatened"))
    print(f"\n  wrote {len(eco)} zones: {have_stock} with stock status, {have_sp} with a species list")
    if failed:
        print(f"  OBIS gave no answer for {len(failed)} zones (re-run to retry): {', '.join(failed[:8])}")
    worst = sorted(((v["stocks"]["by_count"].get("Collapsed", 0) + v["stocks"]["by_count"].get("Over-exploited", 0), n, v["stocks"]["n"])
                    for n, v in eco.items() if v.get("stocks") and v["stocks"]["n"] >= 30), reverse=True)[:8]
    print("\n  largest share of stocks over-exploited or collapsed (30+ stocks):")
    for pct, n, k in worst:
        print(f"    {n[:34]:<36}{pct:5.1f}%  of {k} stocks")


if __name__ == "__main__":
    main()
