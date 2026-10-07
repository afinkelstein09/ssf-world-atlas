"""
Resolve Sea Around Us EEZ names to ISO3 country codes.

This is the join that lets everything else work. Sea Around Us names its EEZs for
fishing purposes ("Indonesia (Central)", "USA (Gulf of Mexico)", "Azores Isl.
(Portugal)"), while every other dataset - FAO, IHH, World Bank, the UN - is keyed
by ISO3. Without this bridge the atlas can only ever show catch.

Three kinds of match, and the distinction matters when reporting:
  self       the EEZ is a country          Mozambique        -> MOZ
  split      one country, several EEZs     Indonesia (Central) -> IDN
  territory  an overseas territory         Azores (Portugal) -> PRT

Territory matches inherit their parent country's national statistics, which is
usually wrong at the margin - the Azores are not Portugal - so they are flagged
and the site says so rather than pretending the number is local.
"""

import difflib
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "data", "raw", "sau_country.json")

# Sea Around Us uses Natural Earth's abbreviated spellings. Expand them so a
# plain string comparison has a chance.
ABBREV = {
    r"\bis\b": "islands",
    r"\bisl\b": "islands",
    r"\brep\b": "republic",
    r"\bdem\b": "democratic",
    r"\beq\b": "equatorial",
    r"\bst\b": "saint",
    r"\bfr\b": "french",
    r"\bbarb\b": "barbuda",
    r"\bherz\b": "herzegovina",
    r"\bne\b": "netherlands",
    r"\bsp\b": "spanish",
    r"\bfed\b": "federated",
    r"\bterr\b": "territory",
    r"\bin\b": "indian",
}

# Names no amount of normalising will bridge, and parent-country shorthands that
# appear only inside parentheses.
ALIASES = {
    "uk": "GBR",
    "united kingdom": "GBR",
    "usa": "USA",
    "united states": "USA",
    "france": "FRA",
    "portugal": "PRT",
    "spain": "ESP",
    "netherlands": "NLD",
    "norway": "NOR",
    "australia": "AUS",
    "new zealand": "NZL",
    "chile": "CHL",
    "ecuador": "ECU",
    "india": "IND",
    "japan": "JPN",
    "denmark": "DNK",
    "colombia": "COL",
    "venezuela": "VEN",
    "yemen": "YEM",
    "oman": "OMN",
    "brazil": "BRA",
    "gaza strip": "PSE",
    "west bank": "PSE",
    "timor leste": "TLS",
    "sao tome and principe": "STP",
    "saint vincent and the grenadines": "VCT",
    "french guiana": "GUF",
    "congo r of": "COG",
    "congo ex zaire": "COD",
    "channel islands": "GBR",
    "hawaii main islands": "USA",
    "hawaii northwest islands": "USA",
    "micronesia": "FSM",
    "cape verde": "CPV",
    "ivory coast": "CIV",
    "cote divoire": "CIV",
    "burma": "MMR",
    "dr congo": "COD",
    # Sea Around Us spells these with an extra word that normalisation can't drop
    # safely - "islands" is load-bearing for Solomon Islands and Marshall Islands,
    # so these two are handled by name instead of by rule.
    "comoros islands": "COM",
    "brunei darussalam": "BRN",
    # Sea Around Us drops the "Islands"; without this the zone fell through to
    # its parent and wore US national figures, while Guam, American Samoa and
    # Puerto Rico each kept their own code. MNP has its own polygon and data.
    "northern marianas": "MNP",
    "north marianas": "MNP",  # the fleet, in fetch_fleets.py
    # Sea Around Us names fishing fleets in its own style, which differs from its
    # EEZ names. Without these a country's own fleet in its own waters resolves to
    # nothing and is counted as foreign - Russia read as 100% foreign-fished.
    "russian federation": "RUS",
    "syrian arab republic": "SYR",
    "curacao": "CUW",
    "north cyprus": "CYP",
    "south cyprus": "CYP",
    # Knocked out by the "-99" sentinel above.
    "france": "FRA",
    "norway": "NOR",
    "kosovo": "XKX",
    "somaliland": "SOM",
}

# Names whose parenthetical is not a parent country, so the generic rule below
# gets them wrong. "Korea (North, Yellow Sea)" has base "Korea", which is South
# Korea's polygon - so North Korea's waters were handed to the South and the
# North's landmass painted "no catch data". Ascension and Tristan da Cunha carry
# a "(UK)" tag, but ISO 3166 files both under Saint Helena (SHN) with the main
# island, so the rule split one territory across two codes. Exact Sea Around Us
# names, checked before anything else.
OVERRIDES = {
    "Korea (South)": ("KOR", "self"),
    "Korea (North, Yellow Sea)": ("PRK", "split"),
    "Korea (North, Sea of Japan)": ("PRK", "split"),
    "Korea (North)": ("PRK", "self"),  # the fleet, in fetch_fleets.py
    "Saint Helena (UK)": ("SHN", "split"),
    "Ascension Isl. (UK)": ("SHN", "split"),
    "Tristan da Cunha Isl. (UK)": ("SHN", "split"),
}

# What the atlas prints for a country. Sea Around Us's country geometry carries
# Natural Earth's abbreviated labels ("Dem. Rep. Congo", "S. Geo. and S. Sandw.
# Is.") and a few outdated ones (Swaziland, Macedonia); the World Bank metadata
# behind the regulatory layer has its own house style ("Korea, Rep.", "Bahamas,
# The", "Naoero"). None of that belongs in a heading, so every script that prints
# a country name goes through display_name(). Everyday English short names as in
# ISO 3166 / UN usage - "Bolivia", not "Plurinational State of Bolivia".
DISPLAY_NAMES = {
    # abbreviated
    "ATF": "French Southern and Antarctic Lands",
    "ATG": "Antigua and Barbuda",
    "BIH": "Bosnia and Herzegovina",
    "BLM": "Saint Barthélemy",
    "CAF": "Central African Republic",
    "COD": "Democratic Republic of the Congo",
    "COK": "Cook Islands",
    "CYM": "Cayman Islands",
    "DOM": "Dominican Republic",
    "ESH": "Western Sahara",
    "FLK": "Falkland Islands",
    "GNQ": "Equatorial Guinea",
    "HMD": "Heard Island and McDonald Islands",
    "IOT": "British Indian Ocean Territory",
    "KNA": "Saint Kitts and Nevis",
    "LAO": "Laos",
    "MAF": "Saint Martin",
    "MHL": "Marshall Islands",
    "MNP": "Northern Mariana Islands",
    "PCN": "Pitcairn Islands",
    "PYF": "French Polynesia",
    "SGS": "South Georgia and the South Sandwich Islands",
    "SLB": "Solomon Islands",
    "SPM": "Saint Pierre and Miquelon",
    "SSD": "South Sudan",
    "TCA": "Turks and Caicos Islands",
    "VCT": "Saint Vincent and the Grenadines",
    "VGB": "British Virgin Islands",
    "VIR": "U.S. Virgin Islands",
    "WLF": "Wallis and Futuna",
    # ambiguous - the geometry calls the South just "Korea"
    "KOR": "South Korea",
    "PRK": "North Korea",
    "SHN": "Saint Helena, Ascension and Tristan da Cunha",
    # outdated or misspelt
    "ALA": "Åland Islands",
    "CPV": "Cabo Verde",
    "CZE": "Czechia",
    "FRO": "Faroe Islands",
    "MKD": "North Macedonia",
    "STP": "São Tomé and Príncipe",
    "SWZ": "Eswatini",
    # no landmass polygon, so nothing to fall back on
    "SXM": "Sint Maarten",
    "GUF": "French Guiana",
}


def display_name(iso3, *fallbacks):
    """The name the atlas prints for a country: the table above, else the first
    non-empty fallback the caller has (usually the geometry's own label), else
    the code itself."""
    if iso3 in DISPLAY_NAMES:
        return DISPLAY_NAMES[iso3]
    for name in fallbacks:
        if name:
            return name
    return iso3


def _norm(name):
    """Lowercase, drop punctuation, expand Natural Earth abbreviations."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[.,'’`]", " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, full in ABBREV.items():
        s = re.sub(pat, full, s)
    return re.sub(r"\s+", " ", s).strip()


def _load_reference():
    """SAU's own country list carries ISO3 codes; cache it locally."""
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            data = json.load(f)
    else:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        req = urllib.request.Request(
            "https://api.seaaroundus.org/api/v1/country/",
            headers={"User-Agent": "ssf-atlas/0.1"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        with open(CACHE, "w") as f:
            json.dump(data, f)

    ref = {}
    for feat in data["data"]["features"]:
        p = feat["properties"]
        code = p.get("c_iso_code")
        # Sea Around Us carries Natural Earth's "-99" sentinel for records it has no
        # code for - and it uses it for France and Norway, not just disputed rocks.
        # Accepting it silently merges every French and Norwegian zone into one
        # fictitious country, so it is rejected here and handled by alias instead.
        if code and code != "-99" and len(code) == 3 and code.isalpha():
            ref[_norm(p["title"])] = code
    return ref


_REF = None


def resolve(eez_name):
    """
    Map one EEZ name to (iso3, kind). Returns (None, None) if unresolvable.

    kind is 'self', 'split', or 'territory'.
    """
    global _REF
    if _REF is None:
        _REF = _load_reference()

    raw = eez_name.strip()
    if raw in OVERRIDES:
        return OVERRIDES[raw]

    # "Something (Parent)" - could be a split of one country, or a territory of
    # another. Which one depends on whether the base name is itself a country.
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw)
    base = m.group(1).strip() if m else raw
    parent = m.group(2).strip() if m else None

    for candidate, kind in ((raw, "self"), (base, "split" if parent else "self")):
        key = _norm(candidate)
        if key in _REF:
            return _REF[key], kind
        if key in ALIASES:
            return ALIASES[key], kind

    if parent:
        key = _norm(parent)
        if key in _REF:
            return _REF[key], "territory"
        if key in ALIASES:
            return ALIASES[key], "territory"

    # Last resort: closest spelling. Cutoff is deliberately high - a wrong country
    # silently attached to a fishery is worse than an honest blank.
    for candidate, kind in ((base, "split" if parent else "self"), (raw, "self")):
        near = difflib.get_close_matches(_norm(candidate), _REF.keys(), n=1, cutoff=0.9)
        if near:
            return _REF[near[0]], kind

    return None, None


if __name__ == "__main__":
    path = os.path.join(HERE, "site", "data", "countries.json")
    with open(path) as f:
        eezs = json.load(f)["countries"]

    counts = {"self": 0, "split": 0, "territory": 0}
    unresolved = []
    for c in eezs:
        code, kind = resolve(c["name"])
        if kind:
            counts[kind] += 1
        else:
            unresolved.append(c["name"])

    total = len(eezs)
    matched = total - len(unresolved)
    print(f"resolved {matched}/{total} EEZs to ISO3")
    for k, v in counts.items():
        print(f"  {k:<10} {v}")
    if unresolved:
        print(f"\nunresolved ({len(unresolved)}):")
        for n in unresolved:
            print("  ", n)
