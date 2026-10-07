"""
Build the country organisation profile: who works on small-scale fisheries, by role.

Caleb asked for a country page that reads like a directory:

    Indonesia
    Government:            Ministry of Marine Affairs and Fisheries
    International NGO:     WCS, CI, WWF, Rare, Blue Ventures
    National/Local NGO:    Coral Triangle Center, LMMA...
    Donors:                Bloomberg, Packard, MACP, USAID, GEF...

Nothing publishes that list. It has to be assembled from four sources that each see
a different slice, and none of which agrees on what an organisation is:

  Annex A   120 fisher organisations - the fishers' own representative bodies,
            supplied by Rare from WFFP, ICSF and project files. Nothing else here
            contains these.
  IATI      aid activities, with participating organisations tagged by role, so
            funders and implementers can be separated.
  ISSF      crowdsourced research and organisation records.
  Fish Forever  Rare's own eight countries.

The classifier below is rule-based and deliberately conservative: an organisation
it cannot place lands in 'unclassified' rather than being guessed into a category.
Getting Rare filed as a donor would be worse than leaving it unsorted.

Outputs site/data/profile.json.
"""

import html
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries as iso_lookup

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "site", "data")
RAW = os.path.join(HERE, "data", "raw")

CATEGORIES = ["government", "international_ngo", "national_ngo", "fisher_org",
              "donor", "research", "private_sector", "unclassified"]

# Organisations we can name with confidence. Everything else is decided by rule,
# and anything still ambiguous stays unclassified.
COMPANY_PATTERNS = [
    r"\bb\.?v\.?$", r"\bltd\b", r"\blimited\b", r"\bgmbh\b", r"\bs\.a\.?$",
    r"\binc\.?$", r"\bplc\b", r"\bpty\b", r"\bcorporation\b", r"\bco\.$",
    r"\bconsult(ing|ants?)\b", r"\bholdings?\b",
]

KNOWN_INTL = {
    "wcs", "wildlife conservation society", "wwf", "world wildlife fund",
    "world wide fund", "conservation international", "rare", "blue ventures",
    "the nature conservancy", "nature conservancy", "tnc", "environmental defense fund",
    "edf", "oceana", "fauna & flora", "fauna and flora", "flora & fauna",
    "wetlands international", "birdlife", "iucn", "worldfish", "cgiar",
    "care international", "oxfam", "practical action", "snv", "hivos",
    "solidaridad", "rare inc", "wildaid", "coral reef alliance", "mangrove action",
}
# UN technical agencies implement; development banks lend. Both are multilateral,
# but only one belongs in a donor column.
KNOWN_MULTILATERAL = {
    "fao", "food and agriculture organization", "undp", "unep", "unido", "unops",
    "unicef", "wfp", "ilo", "united nations", "unesco",
}
KNOWN_BANKS = {
    "world bank", "ibrd", "ifc", "ida", "asian development bank", "adb",
    "african development", "inter-american development", "islamic development",
    "european investment bank", "ifad", "gef", "global environment facility",
    "european commission", "european union", "eu-commission",
}
KNOWN_DONORS = {
    "bloomberg", "packard", "david and lucile packard", "macarthur", "moore foundation",
    "gordon and betty moore", "walton family", "oak foundation", "usaid", "sida",
    "danida", "norad", "giz", "bmz", "dfid", "fcdo", "jica", "kfw", "nicfi",
    "margaret a. cargill", "macp", "bezos earth fund", "blue action fund", "baf",
    "adessium", "waitt", "schmidt", "rockefeller", "wellcome", "arcadia",
    "netherlands enterprise agency", "new zealand ministry of foreign affairs",
    "australian aid", "global environment fund", "bmz", "irish aid",
    "swedish international development", "swiss agency for development",
    "agence française de développement", "afd", "koica", "kfw",
    # Donor agencies whose names carry no country word, so the government
    # pattern below would file them as the recipient's own ministry.
    "directorate-general for international partnerships", "dg intpa",
    "directorate-general for neighbourhood", "dg near",
    "directorate-general development cooperation", "directorate-general for development cooperation",
    "development cooperation and humanitarian aid", "veterinary medicines directorate",
    "ministry of foreign affairs (- embassies)",
}
# A demonym in a ministry's name says whose ministry it is: "Norwegian Ministry
# of Foreign Affairs" on Mozambique's page is Norway, giving.
DEMONYMS = {
    "norwegian": "NOR", "danish": "DNK", "swedish": "SWE", "german": "DEU",
    "british": "GBR", "french": "FRA", "belgian": "BEL", "flemish": "BEL",
    "dutch": "NLD", "japanese": "JPN", "korean": "KOR", "australian": "AUS",
    "canadian": "CAN", "finnish": "FIN", "spanish": "ESP", "italian": "ITA",
    "irish": "IRL", "swiss": "CHE", "austrian": "AUT", "portuguese": "PRT",
    "new zealand": "NZL", "luxembourg": "LUX", "icelandic": "ISL",
}


def _has(n, terms):
    """Whole-word match: 'ida' must not fire inside 'solidaridad', nor 'sida'
    inside 'universidad'."""
    return any(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", n) for k in terms)
GOV_PATTERNS = [
    r"\bministry\b", r"\bminist[eè]re\b", r"\bministerio\b", r"\bminist[eé]rio\b",
    r"\bdepartment of\b", r"\bdepartamento\b", r"\bgovernment of\b", r"\bgobierno\b",
    r"\bnational (agency|authority|institute|directorate)\b", r"\bdirectorate\b",
    r"\bfisheries authority\b", r"\bfisheries department\b", r"\bbureau of\b",
    r"\bstate of\b", r"\bautoridad\b", r"\bsecretaria\b", r"\bagence nationale\b",
]
RESEARCH_PATTERNS = [
    r"\buniversity\b", r"\buniversidad\b", r"\buniversit[eé]\b", r"\binstitute\b",
    r"\binstitut\b", r"\bcollege\b", r"\bacademy\b", r"\bresearch cent(re|er)\b",
    r"\blaborator", r"\bmuseum\b",
]


_COUNTRY_WORDS = None


def _names_another_country(n, home_iso, country_names):
    """True if a government name mentions a country other than the one it is filed under."""
    if not country_names:
        return False
    home = country_names.get(home_iso, "").lower()
    for iso, cname in country_names.items():
        if iso == home_iso:
            continue
        c = cname.lower()
        if len(c) < 4:
            continue
        if re.search(r"\b" + re.escape(c) + r"\b", n):
            # "Republic of Korea" inside "Korea" style overlaps are fine; a home-country
            # mention always wins so a domestic ministry is never exiled as a donor.
            if home and re.search(r"\b" + re.escape(home) + r"\b", n):
                return False
            return True
    return False


PLACEHOLDER = re.compile(r"^(name withheld|not reported|other multilateral institution|"
                         r"other public entities in (donor|recipient|provider) country|"
                         r"private sector( in (donor|recipient|provider) country)?|"
                         r"donor country[- ]based ngo|recipient country[- ]based ngo|"
                         r"international ngo|national ngo|other)$")


def norm(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def clean_name(name):
    """
    Tidy the source strings.

    IATI publishers escape commas as the literal word, so names arrive as
    "Department of Agriculturecomma Fisheries and Forestry". Left alone these
    also defeat de-duplication.
    """
    s = str(name or "").strip()
    # ISSF stores HTML-escaped text, sometimes escaped twice ("&amp;#39;").
    for _ in range(3):
        u = html.unescape(s)
        if u == s:
            break
        s = u
    # A few ISSF names arrive as UTF-8 read through Latin-1 ("PÃªches").
    if "Ã" in s or "â€" in s:
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    # ISSF appends the postal address, founding year and country to the name.
    s = re.split(r"\s+(?:Address|Established in|Country):\s*", s, maxsplit=1)[0]
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"(?<=[a-z])comma(?=\s)", ",", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip(" ,")


def classify(name, hint=None, home_iso=None, country_names=None):
    """
    Decide an organisation's category.

    `hint` carries what the source already knows - IATI's participating-org role,
    or the fact that a record came from the fisher-organisation annex - which is
    stronger evidence than anything the name can tell us.

    `home_iso` is the country whose profile this entry is being filed under. It
    matters because a ministry is only "government" on its own page: Denmark's
    Ministry of Foreign Affairs appearing under Indonesia is a bilateral donor,
    and filing it as government would answer the wrong question entirely.
    """
    n = norm(name)
    if not n or n in ("name withheld", "not reported"):
        return "unclassified"

    if hint == "fisher_org":
        return "fisher_org"

    # Named aid agencies are checked before the government pattern, because most of
    # them are ministries at home - BMZ and Irish Aid are departments of foreign
    # affairs, and matching on shape alone files them as domestic government.
    if _has(n, KNOWN_DONORS):
        return "donor"

    is_gov = any(re.search(pat, n) for pat in GOV_PATTERNS) or n.startswith("government of")
    if is_gov:
        foreign = _names_another_country(n, home_iso, country_names)
        # A ministry that only ever funds, and does not name the home country,
        # is somebody else's ministry: Korea's "Ministry of Oceans and
        # Fisheries" appeared as the government of nine recipient countries.
        home = (country_names or {}).get(home_iso, "").lower()
        names_home = bool(home) and re.search(r"\b" + re.escape(home) + r"\b", n) is not None
        if hint == "funding" and not names_home:
            foreign = True
        # "NOR - Ministry of Foreign Affairs": IATI's own country prefix.
        m = re.match(r"^([a-z]{3}) - ", n)
        if m and home_iso and m.group(1).upper() != home_iso:
            foreign = True
        for word, iso in DEMONYMS.items():
            if iso != home_iso and re.search(r"\b" + word + r"\b", n):
                foreign = True
                break
        return "donor" if foreign else "government"

    if _has(n, KNOWN_BANKS):
        return "donor"
    if _has(n, KNOWN_MULTILATERAL):
        return "donor" if hint == "funding" else "international_ngo"
    if any(re.search(r"\b" + re.escape(k) + r"\b", n) for k in KNOWN_INTL):
        return "international_ngo"

    for pat in RESEARCH_PATTERNS:
        if re.search(pat, n):
            return "research"
    for pat in COMPANY_PATTERNS:
        if re.search(pat, n):
            return "private_sector"

    # A funder we cannot name is still a funder - the role is reported, not inferred.
    if hint == "funding":
        return "donor"
    if hint == "implementing":
        return "national_ngo"
    return "unclassified"


def load_links():
    """
    Hand-checked web pages for organisations, from data/org_links.json.

    Two tables, both keyed by the normalised name: `annex` for the fisher
    organisations in Rare's list, `by_name` for the bodies that recur across
    many countries (FAO, the development banks, the aid agencies). A link is
    only ever read from this file - nothing is guessed at build time - and
    scripts/check_links.py re-tests every one of them.
    """
    path = os.path.join(HERE, "data", "org_links.json")
    if not os.path.exists(path):
        return {}, {}
    d = json.load(open(path))

    # Anything the last link check found dead is left out of the site.
    dead = set()
    check = os.path.join(HERE, "data", "link_check.json")
    if os.path.exists(check):
        dead = {u for u, r in json.load(open(check)).get("links", {}).items()
                if r.get("class") == "dead"}

    def alive(table):
        out = {}
        for key, rec in (table or {}).items():
            rec = dict(rec)
            for field in ("site", "ssf"):
                if rec.get(field) in dead:
                    rec[field] = None
            if rec.get("site") or rec.get("ssf"):
                out[key] = rec
        return out

    return alive(d.get("by_name")), alive(d.get("annex"))


LINKS_BY_NAME, LINKS_ANNEX = {}, {}


def load_fisher_orgs(iso_of):
    """Annex A. Country strings are mostly clean; regional entries list members."""
    path = os.path.join(RAW, "annex", "fisher_orgs.json")
    if not os.path.exists(path):
        print("  ! Annex A not found")
        return {}, []
    recs = json.load(open(path))

    by_country, regional = {}, []
    for r in recs:
        label = (r.get("acronym") or "").strip()
        name = (r.get("name") or "").strip()
        display = f"{label} — {name}" if label and label not in name else (name or label)
        raw_country = r.get("country") or ""

        # Pull every country named in the string; regional entries list their members
        # in parentheses, and a secretariat location is a place, not a membership.
        # The whole string is tried first: splitting "Antigua and Barbuda" on
        # " and " left Rare's Caribbean organisations with no country at all.
        # Annex spellings the zone resolver has no reason to know. Réunion's
        # organisation files under France, where the Réunion zone's data lives.
        ANNEX = {"réunion": "France", "reunion": "France"}
        def place(text):
            text = ANNEX.get(text.strip().lower(), text.strip())
            if not text or len(text) < 3:
                return None
            return iso_lookup.resolve(text)[0]

        isos = []
        whole = raw_country.strip()
        if whole and not re.match(r"^(Regional|Global)\b", whole):
            code = place(whole)
            if code:
                isos.append(code)
        if not isos:
            # Comma-separated parts first, each tried whole, so "Union Island,
            # St. Vincent and the Grenadines" finds St Vincent before " and "
            # is allowed to cut a country name in half.
            parts = re.split(r"[/,;]", re.sub(r"^(Regional|Global)\s*", "", raw_country))
            for part in parts:
                if re.search(r"Secretariat|\bHQ\b|-based", part):
                    continue  # where the office is, not who belongs
                part = re.sub(r"\(|\)", " ", part).strip()
                code = place(part)
                pieces = [part] if code else re.split(r"\s+and\s+", part)
                for c in pieces:
                    code = place(c)
                    if code and code not in isos:
                        isos.append(code)

        entry = {"name": display, "category": "fisher_org",
                 "source": "Annex A (WFFP/ICSF, via Rare)", "region": r.get("region")}
        link = LINKS_ANNEX.get(norm(name)) or LINKS_ANNEX.get(norm(label))
        if link and link.get("site"):
            entry["site"] = link["site"]
            if link.get("kind") and link["kind"] != "website":
                entry["site_kind"] = link["kind"]
        if isos:
            for code in isos:
                by_country.setdefault(code, []).append(entry)
        else:
            regional.append({**entry, "scope": raw_country})
    return by_country, regional


def main():
    global LINKS_BY_NAME, LINKS_ANNEX
    os.makedirs(OUT, exist_ok=True)
    iso_of = {}
    LINKS_BY_NAME, LINKS_ANNEX = load_links()
    print(f"Checked links: {len(LINKS_BY_NAME)} recurring bodies, {len(LINKS_ANNEX)} fisher organisations")

    # ISO3 -> country name, used to tell a domestic ministry from a foreign one.
    country_names = {}
    wb = os.path.join(HERE, "analysis", "wb_meta.json")
    if os.path.exists(wb):
        for iso, m in json.load(open(wb)).items():
            if m.get("name"):
                country_names[iso] = m["name"]

    print("Annex A — fisher organisations")
    fisher_by_country, fisher_regional = load_fisher_orgs(iso_of)
    print(f"  {sum(len(v) for v in fisher_by_country.values())} placed in "
          f"{len(fisher_by_country)} countries, {len(fisher_regional)} regional")

    print("IATI")
    iati = {}
    p = os.path.join(OUT, "orgs.json")
    if os.path.exists(p):
        d = json.load(open(p))
        by_id = {a["id"]: a for a in d["activities"]}
        for iso, ids in d["by_country"].items():
            seen = {}
            for i in ids:
                a = by_id.get(i)
                if not a:
                    continue
                for role in ("funding", "implementing", "accountable", "extending"):
                    for name in (a.get("orgs", {}).get(role) or []):
                        key = norm(clean_name(name))
                        # IATI's stand-ins for an organisation a publisher did not name
                        # ("Name Withheld", "Other multilateral institution", "Private
                        # sector in recipient country") are not organisations to list.
                        if not key or PLACEHOLDER.match(key):
                            continue
                        if key in seen:
                            # the same body on another project here: keep the project,
                            # so its chip can list every piece of work it is named on
                            if i not in seen[key]["acts"]:
                                seen[key]["acts"].append(i)
                            seen[key]["_roles"].add(role)
                            continue
                        clean = clean_name(name)
                        seen[key] = {"name": clean, "source": "IATI", "acts": [i],
                                     "_roles": {role}, "_first": role}
            # One category per body per country, from all the roles it holds here. Taking
            # the role on whichever project was read first filed FAO as a donor in 57
            # countries and an NGO in 39 with the same roles.
            for rec in seen.values():
                roles = rec.pop("_roles")
                first = rec.pop("_first")
                hint = "funding" if "funding" in roles else ("implementing" if "implementing" in roles else first)
                rec["category"] = classify(rec["name"], hint, iso, country_names)
            iati[iso] = list(seen.values())
        print(f"  {sum(len(v) for v in iati.values())} organisations across {len(iati)} countries")

    print("ISSF")
    issf = {}
    p = os.path.join(OUT, "issf.json")
    if os.path.exists(p):
        d = json.load(open(p))
        for r in d["records"]:
            if r["kind"] != "organization" or not r.get("label"):
                continue
            for iso in r["countries"]:
                issf.setdefault(iso, []).append({
                    "name": clean_name(r["label"]),
                    "category": classify(clean_name(r["label"]), None, iso, country_names),
                    "source": "ISSF", "issf": [r["id"]]})
        print(f"  {sum(len(v) for v in issf.values())} organisations across {len(issf)} countries")

    # merge, de-duplicating on normalised name and preferring the more specific
    # category when two sources disagree
    RANK = {c: i for i, c in enumerate(
        ["fisher_org", "government", "international_ngo", "national_ngo",
         "donor", "research", "private_sector", "unclassified"])}

    merged = {}
    for src in (fisher_by_country, iati, issf):
        for iso, entries in src.items():
            slot = merged.setdefault(iso, {})
            for e in entries:
                key = norm(e["name"])
                cur = slot.get(key)
                pointers = {}
                for field in ("acts", "issf"):
                    both = list(dict.fromkeys((cur or {}).get(field, []) + e.get(field, [])))
                    if both:
                        pointers[field] = both
                for field in ("site", "site_kind"):
                    if (cur or {}).get(field) or e.get(field):
                        pointers[field] = (cur or {}).get(field) or e.get(field)
                if cur is None or RANK[e["category"]] < RANK[cur["category"]]:
                    if cur:
                        e = {**e, "source": f'{cur["source"]}, {e["source"]}'}
                    slot[key] = {**e, **pointers}
                else:
                    slot[key] = {**cur, **pointers}
    profile = {}
    for iso, slot in merged.items():
        buckets = {c: [] for c in CATEGORIES}
        for e in slot.values():
            out = {"name": e["name"], "source": e["source"]}
            for field in ("acts", "issf", "site", "site_kind"):
                if e.get(field):
                    out[field] = e[field]
            known = LINKS_BY_NAME.get(norm(e["name"]))
            if known:
                if known.get("ssf"):
                    out["ssf"] = known["ssf"]
                if known.get("site") and not out.get("site"):
                    out["site"] = known["site"]
            buckets[e["category"]].append(out)
        profile[iso] = {c: sorted(v, key=lambda x: x["name"]) for c, v in buckets.items() if v}

    total = sum(len(v) for b in profile.values() for v in b.values())
    with open(os.path.join(OUT, "profile.json"), "w") as f:
        json.dump({
            "generated": time.strftime("%Y-%m-%d"),
            "categories": CATEGORIES,
            "sources": {
                "fisher_org": "Annex A: SSF Organisations by Region (WFFP, ICSF and project files, supplied by Rare)",
                "iati": "IATI Registry via Code for IATI Datastore",
                "issf": "Information System on Small-scale Fisheries (Too Big To Ignore)",
            },
            "note": ("Categories are assigned by rule from organisation names and the roles "
                     "sources report. Anything ambiguous is left unclassified rather than guessed."),
            "count": total,
            "countries": profile,
            "regional": fisher_regional,
        }, f, indent=1)

    from collections import Counter
    cats = Counter()
    for b in profile.values():
        for c, v in b.items():
            cats[c] += len(v)
    print(f"\n  wrote {total} organisation entries across {len(profile)} countries")
    for c in CATEGORIES:
        if cats[c]:
            print(f"    {c:<20}{cats[c]:>5}")
    top = sorted(profile.items(), key=lambda kv: -sum(len(v) for v in kv[1].values()))[:8]
    print("\n  richest country profiles:")
    for iso, b in top:
        print(f"    {iso}  {sum(len(v) for v in b.values()):>3}  " +
              ", ".join(f"{c.split('_')[0]}:{len(v)}" for c, v in b.items()))


if __name__ == "__main__":
    main()
