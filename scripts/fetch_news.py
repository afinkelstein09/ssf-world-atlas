"""
Build the news layer: what is happening to fishers here, right now?

Two kinds of source, merged per country:

  sector feeds    RSS from outlets that cover fisheries and the ocean (Mongabay,
                  the Guardian's fishing desk, CFFA on West African artisanal
                  fishing, the Pacific Forum Fisheries Agency, Blue Ventures,
                  Oceana, Global Fishing Watch, plus two regional wires). Every
                  item is tagged with the countries its headline or summary names.

  news search     One Google News RSS search per country, in the language the
                  country's press writes in: "pesca artesanal" for Chile,
                  "peche artisanale" for Senegal, "nelayan" for Indonesia. This
                  is what makes the layer work for every country rather than the
                  handful a sector outlet happens to cover that month.

Both are filtered the same way: the HEADLINE has to be about fishing. The first
version of this script used GDELT and matched phrases anywhere in an article's
text, which filed a lobster restaurant guide under Belize and Tanzanian politics
under Brazil. A headline filter is blunt, and it is the reason the list reads
as fisheries news.

There is no official Google News API (Google closed it in 2011). The RSS search
feed is public and keyless, and its terms are written for personal, non-commercial
use - fine for a prototype, worth checking before an organisation hosts this
publicly. It sits behind one switch, USE_NEWS_SEARCH, and the sector feeds work
without it.

Headlines are collected by machine and nobody has read them. The page says so.

Outputs site/data/news.json.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "news")
OUT = os.path.join(HERE, "site", "data")

USE_NEWS_SEARCH = True      # the one switch: False leaves only the sector feeds
WINDOW_DAYS = 60            # nothing older than this is shown
PER_COUNTRY = 6
SEARCH_DELAY = 1.3          # seconds between searches; slow on purpose

# Headlines are translated into English once, at build time, so an English reader
# gets English in any browser. MyMemory is the one free, keyless translation service
# that answered when five were tested (20 Sep 2026): the unofficial Google endpoint
# was blocked and is outside Google's terms, no public LibreTranslate or Lingva
# mirror worked, and the offline Argos models got two of six test headlines wrong,
# one by reversing who accused whom.
#
# MyMemory allows 5,000 characters a day without an address and 50,000 with a contact
# email in the request. The address is sent in the URL and kept by MyMemory, so it is
# left empty here on purpose: whoever runs this decides whether to give one. Every
# translation is kept in data/news_translations.json, so a headline is only ever
# translated once and a nightly run costs a few hundred characters.
MYMEMORY = "https://api.mymemory.translated.net/get"
TRANSLATE_CONTACT_EMAIL = ""
TRANSLATE_BUDGET = 4500 if not TRANSLATE_CONTACT_EMAIL else 45000      # characters per run
TRANSLATIONS = os.path.join(HERE, "data", "news_translations.json")

UA = {"User-Agent": "Mozilla/5.0 (compatible; ssf-atlas/0.1; local research prototype)",
      "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}

# name, url, and whether everything in the feed is already about fishing or the sea.
# General wires (topical=False) are only kept when the headline passes the filter.
FEEDS = [
    ("Mongabay", "https://news.mongabay.com/feed/?topic=fisheries", True),
    ("Mongabay", "https://news.mongabay.com/feed/?topic=oceans", False),
    ("The Guardian", "https://www.theguardian.com/environment/fishing/rss", True),
    ("CFFA", "https://www.cffacape.org/news-blog?format=rss", True),
    ("Pacific Islands Forum Fisheries Agency", "https://www.ffa.int/feed/", True),
    ("Blue Ventures", "https://blueventures.org/feed/", True),
    ("Oceana", "https://oceana.org/feed/", False),
    ("Global Fishing Watch", "https://globalfishingwatch.org/feed/", True),
    ("RNZ Pacific", "https://www.rnz.co.nz/rss/pacific.xml", False),
    ("AllAfrica", "https://allafrica.com/tools/headlines/rdf/environment/headlines.rdf", False),
]

# The headline has to be about fishing, in any of the languages searched.
ABOUT_FISHING = re.compile(
    r"\b(fish\w*|pesca\w*|pesque\w*|p[eê]che\w*|p[eê]cheur\w*|nelayan|perikanan|"
    r"seafood|marisc\w*|tuna|at[uú]n\w*|thon\w*|sardin\w*|anchov\w*|shrimp\w*|camar[oó]n\w*|"
    r"crevette\w*|lobster\w*|langost\w*|trawl\w*|arrastre|chalut\w*|aquacult\w*|acuicult\w*|"
    r"aquicult\w*|overfish\w*|sobrepesca|surp[eê]che|iuu|marine protected)\b", re.I)
NOT_NEWS = re.compile(
    r"\b(recipe|restaurant|fish and chips|fishing trip|sport ?fishing|fly fishing|angler|angling|"
    r"tournament|derby|phishing|fisher-price|video game|horoscope|gone fishing|fishing for compliments|lodges?|resorts?|vacation|travel guide|guide to|hotels?|journal no|best fishing|fishing charters?|swoons|bikini|honeymoon|c o r r e c t i o n)\b", re.I)

SEARCHES = {
    "en": ('("small-scale fisheries" OR "small-scale fishers" OR "artisanal fishing" OR "artisanal fishers" '
           'OR "artisanal fishermen" OR "fishing communities" OR fisherfolk) "{name}"', "hl=en-US&gl=US&ceid=US:en"),
    "en_broad": ('(fishing OR fisheries OR fishers OR fishermen) "{name}"', "hl=en-US&gl=US&ceid=US:en"),
    "es": ('("pesca artesanal" OR "pescadores artesanales") "{name}"', "hl=es-419&gl=US&ceid=US:es-419"),
    "pt": ('("pesca artesanal" OR "pescadores artesanais") "{name}"', "hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    "fr": ('("pêche artisanale" OR "pêcheurs artisanaux" OR "pêcheurs artisans") "{name}"', "hl=fr&gl=FR&ceid=FR:fr"),
    "id": ('(nelayan OR "perikanan skala kecil") "{name}"', "hl=id&gl=ID&ceid=ID:id"),
    # For the El Nino card: the phenomenon and fishing together. Spanish as well as
    # English, because the fisheries it hits hardest report in Spanish.
    "en_enso": ('"{name}" (fishing OR fisheries OR fishers OR fishermen OR anchovy OR tuna)', "hl=en-US&gl=US&ceid=US:en"),
    "es_enso": ('"{name}" (pesca OR pescadores OR anchoveta OR pesquería)', "hl=es-419&gl=US&ceid=US:es-419"),
}
ABOUT_ENSO = re.compile(r"\b(el ni[ñn]o|la ni[ñn]a|enso|fen[oó]meno del? ni[ñn]o)\b", re.I)
# Outlets whose whole beat is the sea: an El Nino headline from them belongs on the
# card even when the word "fishing" is not in it.
OCEAN_OUTLETS = {"Mongabay", "The Guardian", "CFFA", "Pacific Islands Forum Fisheries Agency",
                 "Blue Ventures", "Oceana", "Global Fishing Watch"}

# The language a country's press writes in, and the country's name in it.
LOCAL = {
    "MEX": ("es", "México"), "GTM": ("es", "Guatemala"), "HND": ("es", "Honduras"),
    "SLV": ("es", "El Salvador"), "NIC": ("es", "Nicaragua"), "CRI": ("es", "Costa Rica"),
    "PAN": ("es", "Panamá"), "COL": ("es", "Colombia"), "VEN": ("es", "Venezuela"),
    "ECU": ("es", "Ecuador"), "PER": ("es", "Perú"), "CHL": ("es", "Chile"),
    "ARG": ("es", "Argentina"), "URY": ("es", "Uruguay"), "CUB": ("es", "Cuba"),
    "DOM": ("es", "República Dominicana"), "ESP": ("es", "España"), "GNQ": ("es", "Guinea Ecuatorial"),
    "BRA": ("pt", "Brasil"), "PRT": ("pt", "Portugal"), "MOZ": ("pt", "Moçambique"),
    "AGO": ("pt", "Angola"), "CPV": ("pt", "Cabo Verde"), "GNB": ("pt", "Guiné-Bissau"),
    "STP": ("pt", "São Tomé e Príncipe"), "TLS": ("pt", "Timor-Leste"),
    "FRA": ("fr", "France"), "SEN": ("fr", "Sénégal"), "MRT": ("fr", "Mauritanie"),
    "GIN": ("fr", "Guinée"), "CIV": ("fr", "Côte d'Ivoire"), "BEN": ("fr", "Bénin"),
    "TGO": ("fr", "Togo"), "CMR": ("fr", "Cameroun"), "GAB": ("fr", "Gabon"),
    "COG": ("fr", "Congo"), "COD": ("fr", "RDC"), "MDG": ("fr", "Madagascar"),
    "COM": ("fr", "Comores"), "DJI": ("fr", "Djibouti"), "HTI": ("fr", "Haïti"),
    "MAR": ("fr", "Maroc"), "TUN": ("fr", "Tunisie"), "DZA": ("fr", "Algérie"),
    "IDN": ("id", "Indonesia"),
}

# How the press names a country, where the atlas's heading is more formal.
ENGLISH = {
    "USA": "United States", "GBR": "United Kingdom", "RUS": "Russia", "KOR": "South Korea",
    "PRK": "North Korea", "COD": "DR Congo", "COG": "Republic of Congo", "FSM": "Micronesia",
    "CIV": "Ivory Coast", "TLS": "Timor-Leste", "CPV": "Cape Verde", "SYR": "Syria",
    "IRN": "Iran", "VNM": "Vietnam", "TZA": "Tanzania", "BRN": "Brunei", "VEN": "Venezuela",
    "STP": "Sao Tome and Principe", "BHS": "Bahamas", "GMB": "Gambia",
}
# Other ways a feed item may name the country.
ALIASES = {
    "CIV": ["Côte d'Ivoire", "Cote d'Ivoire"], "TLS": ["East Timor"], "CPV": ["Cabo Verde"],
    "GBR": ["UK", "Britain", "Scotland", "England", "Wales"], "USA": ["U.S.", "US", "America"],
    "COD": ["Democratic Republic of Congo", "DRC"], "PNG": ["PNG"], "SLB": ["Solomon Islands", "Solomons"],
    "FSM": ["Federated States of Micronesia", "FSM"], "MHL": ["Marshall Islands"], "MMR": ["Burma"],
    "STP": ["São Tomé"], "KNA": ["St Kitts"], "VCT": ["St Vincent"], "LCA": ["St Lucia"],
}
# Words that place a headline in a country without naming it: what its people and
# its best-known fishing coasts are called.
TITLE_WORDS = {
    "PHL": ["Philippine", "Filipino", "Palawan", "Mindanao", "Visayas"], "IDN": ["Indonesian", "Sulawesi", "Maluku", "Java"],
    "CHL": ["Chilean", "chileno", "chilena"], "PER": ["Peruvian", "peruano", "peruana"], "ECU": ["Ecuadorian", "Galápagos", "Galapagos"],
    "MEX": ["Mexican", "mexicano", "mexicana", "Baja California", "Yucatán"], "COL": ["Colombian", "colombiano"],
    "BRA": ["Brazilian", "brasileiro", "brasileira"], "ARG": ["Argentine", "argentino"], "SEN": ["Senegalese", "sénégalais", "Dakar"],
    "GHA": ["Ghanaian"], "NGA": ["Nigerian"], "KEN": ["Kenyan", "Lamu", "Mombasa"], "TZA": ["Tanzanian", "Zanzibar"],
    "MOZ": ["Mozambican", "moçambicano"], "MDG": ["Malagasy", "malgache"], "ZAF": ["South African", "Western Cape"],
    "NAM": ["Namibian"], "MAR": ["Moroccan", "marocain"], "MRT": ["Mauritanian", "mauritanien"], "IND": ["Indian", "Kerala", "Tamil Nadu"],
    "LKA": ["Sri Lankan", "Lanka"], "BGD": ["Bangladeshi"], "VNM": ["Vietnamese"], "THA": ["Thai"], "MYS": ["Malaysian", "Sabah", "Sarawak"],
    "JPN": ["Japanese"], "CHN": ["Chinese"], "KOR": ["Korean"], "NOR": ["Norwegian"], "ISL": ["Icelandic"],
    "GBR": ["British", "Scottish", "Cornish", "Cornwall", "Shetland", "Welsh"], "IRL": ["Irish"], "FRA": ["French", "français", "Bretagne", "Brittany"],
    "ESP": ["Spanish", "español", "Galicia", "gallego"], "PRT": ["Portuguese", "português", "Açores"], "ITA": ["Italian", "Sicilian"],
    "GRC": ["Greek"], "TUR": ["Turkish"], "CAN": ["Canadian", "Newfoundland", "Nova Scotia", "British Columbia"],
    "USA": ["American", "Alaska", "Alaskan", "Maine", "Gulf of Mexico", "NOAA"], "AUS": ["Australian", "Queensland", "Tasmania"],
    "NZL": ["New Zealand", "Kiwi", "Māori"], "FJI": ["Fijian"], "WSM": ["Samoan"], "TON": ["Tongan"], "PLW": ["Palauan"],
    "PNG": ["Papua New Guinean"], "SLB": ["Solomon"], "PSE": ["Gaza", "Palestinian"], "YEM": ["Yemeni"], "SOM": ["Somali"],
    "MDV": ["Maldivian"], "SYC": ["Seychellois"], "MUS": ["Mauritian"], "JAM": ["Jamaican"], "HTI": ["Haitian", "haïtien"],
    "HND": ["Honduran", "hondureño"], "GTM": ["Guatemalan", "guatemalteco"], "NIC": ["Nicaraguan"], "CRI": ["Costa Rican", "costarricense"],
    "PAN": ["Panamanian", "panameño"], "VEN": ["Venezuelan", "venezolano"], "URY": ["Uruguayan", "uruguayo"], "CUB": ["Cuban", "cubano"],
    "DOM": ["Dominican Republic", "dominicano"], "RUS": ["Russian", "Kamchatka"], "DNK": ["Danish"], "SWE": ["Swedish"],
    "NLD": ["Dutch"], "DEU": ["German"], "POL": ["Polish"], "HRV": ["Croatian"], "EGY": ["Egyptian"], "TUN": ["Tunisian", "tunisien"],
    "DZA": ["Algerian", "algérien"], "LBY": ["Libyan"], "CIV": ["Ivorian", "ivoirien", "Abidjan"], "CMR": ["Cameroonian", "camerounais"],
    "GIN": ["Guinean", "guinéen", "Conakry"], "SLE": ["Sierra Leonean"], "LBR": ["Liberian"], "GMB": ["Gambian"], "AGO": ["Angolan", "angolano"],
    "CPV": ["Cape Verdean", "cabo-verdiano"], "GNB": ["Bissau"], "PAK": ["Pakistani", "Karachi", "Balochistan"], "IRN": ["Iranian"],
    "OMN": ["Omani"], "MMR": ["Myanmar", "Burmese"], "KHM": ["Cambodian"], "TWN": ["Taiwanese"], "TLS": ["Timorese"],
}
# Country-code web domains that are sold to anyone, so they say nothing about where an outlet is.
GENERIC_TLDS = {"co", "io", "tv", "me", "fm", "ai", "ly", "to", "nu", "ws", "cc", "gg", "im", "sh", "st", "la", "vc", "ag", "sc", "ac", "cx", "tk", "ms", "bz"}

# Names that are also something else in a headline: a US state, a person, an island
# in another country. Feed items are never tagged to these; the search still runs.
DO_NOT_TAG = {"GEO", "JEY", "GGY", "TCD", "JOR", "MCO"}
# Pages that turn up in a news search and are not news. Social posts are on the
# list because a search returns them with the first hundred characters of the post
# as their "headline", cut mid-word.
NOT_PRESS = re.compile(r"britannica|wikipedia|a-z animals|wansom|tripadvisor|booking\.com|youtube|"
                       r"facebook|instagram|tiktok|linkedin|reddit|twitter|(^|[\s/.])x\.com", re.I)
# A country's name inside a longer name is somewhere else. "Guinée" is in
# "Guinée-Bissau", "Sudan" in "South Sudan", "Samoa" in "American Samoa", and the
# first full run filed a Guinea-Bissau shipwreck under Guinea and a South Sudan
# story under Sudan. Each pattern is blanked out of the text before that country's
# own name is looked for.
NOT_THIS_COUNTRY = {iso: re.compile(pat, re.I) for iso, pat in {
    "GIN": r"(equatorial |papua new |gulf of |new )guinea|guinea[- ]bissau|guin[ée]e[- ](bissau|[ée]quatoriale)|"
           r"golfe de guin[ée]e|nouvelle[- ]guin[ée]e|guinea ecuatorial|(equatorial|new) guinean|guin[ée]-bissau|"
           r"bissau[- ]guin(ean|[ée]en)",
    "SDN": r"south sudan|soudan du sud|sud[aá]n del sur",
    "WSM": r"american samoa|samoa americana",
    "COG": r"dr congo|rd congo|\brdc\b|democratic republic of (the )?congo|congo[- ]kinshasa|"
           r"r[ée]publique d[ée]mocratique du congo",
    "IRL": r"northern ir(eland|ish)",
    "IND": r"indian ocean|west indian|east indian",
    "KOR": r"north korean?",
    "PRK": r"south korean?",
    "USA": r"us ?\$|(latin|south|central|north) american?|american samoa|us virgin",
    "NER": r"niger delta",
    "DMA": r"dominican",
    "MEX": r"new mexic(o|an)|nuevo m[eé]xico",
}.items()}


def fetch(url, timeout=30):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def when(text):
    """RSS dates are RFC 822, Atom dates are ISO. Returns an aware datetime or None."""
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        rec = {"title": "", "url": "", "summary": "", "date": None, "publisher": "", "publisher_url": ""}
        for ch in node:
            tag = ch.tag.split("}")[-1]
            if tag == "title":
                rec["title"] = clean(ch.text)
            elif tag == "link":
                rec["url"] = rec["url"] or (ch.text or ch.attrib.get("href") or "").strip()
            elif tag in ("description", "summary", "encoded", "content"):
                rec["summary"] = rec["summary"] or clean(ch.text)[:600]
            elif tag in ("pubDate", "published", "updated", "date"):
                rec["date"] = rec["date"] or when(ch.text)
            elif tag == "source":
                rec["publisher"] = clean(ch.text)
                rec["publisher_url"] = ch.attrib.get("url", "")
        if rec["title"] and rec["url"]:
            items.append(rec)
    return items


STOPWORDS = {"el", "la", "los", "las", "del", "para", "con", "por", "que", "niño", "nino", "niña", "nina",
             "the", "and", "for", "with", "from", "that", "this", "des", "les", "pour", "dans", "sur", "une"}


# Words every headline for a country already shares because they were the search:
# the fishing vocabulary (the country's own name is passed in by the caller).
SEARCH_WORDS = re.compile(r"^(fish|pesca|pesque|p[eê]ch|nelayan|perikanan|artisan|artesan)", re.I)


def same_story(a, b, ignore=frozenset()):
    """Two headlines for one wire story share most of their content words, whatever the
    masthead. Overlap is measured against the shorter headline, after the words the
    search itself put there are set aside, and it takes three shared words: the first
    version let a three-word junk headline swallow two real stories about Canada."""
    def words(t):
        return {w for w in re.findall(r"[^\W\d_]{4,}", t.lower())
                if w not in STOPWORDS and w not in ignore and not SEARCH_WORDS.match(w)}
    wa, wb = words(a), words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    shared = wa & wb
    return len(shared) >= 3 and len(shared) / min(len(wa), len(wb)) >= 0.5


def translate_to_english(text, src, cache, spent):
    """
    English for one headline, or None. Never raises and never invents: anything that
    is not a clean machine translation is refused, and the headline then stays in its
    own language on the page. `spent` is a one-item list: characters used this run.
    """
    key = f"{src}|{text}"
    if key in cache:
        return cache[key]["en"]
    if spent[0] + len(text) > TRANSLATE_BUDGET or len(text.encode("utf-8")) > 500:
        return None
    params = {"q": text, "langpair": f"{src}|en", "mt": "1"}
    if TRANSLATE_CONTACT_EMAIL:
        params["de"] = TRANSLATE_CONTACT_EMAIL
    spent[0] += len(text)
    status, raw = fetch(MYMEMORY + "?" + urllib.parse.urlencode(params), timeout=30)
    time.sleep(1.0)
    if status != 200 or not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    if str(d.get("responseStatus")) != "200" or d.get("quotaFinished"):
        spent[0] = TRANSLATE_BUDGET          # out of quota: stop asking for today
        return None
    # The service can answer from a crowd-sourced memory of other people's translations,
    # which can be anything. Only its machine translation is accepted.
    out = next((m.get("translation") for m in d.get("matches") or [] if m.get("created-by") == "MT!"), None)
    out = html.unescape((out or "").strip())
    if (not out or "MYMEMORY WARNING" in out.upper() or out.casefold() == text.casefold()
            or not 0.4 <= len(out) / max(len(text), 1) <= 2.5):
        return None
    cache[key] = {"en": out, "by": "MyMemory machine translation", "on": time.strftime("%Y-%m-%d")}
    return out


def is_fishing_news(title):
    return bool(ABOUT_FISHING.search(title)) and not NOT_NEWS.search(title)


def country_patterns(names):
    pats = {}
    for iso, name in names.items():
        if iso in DO_NOT_TAG:
            continue
        words = {name, ENGLISH.get(iso, name)} | set(ALIASES.get(iso, []))
        if iso in LOCAL:
            words.add(LOCAL[iso][1])
        words = sorted((w for w in words if w and len(w) >= 2), key=len, reverse=True)
        # Short all-capital aliases (US, UK, PNG) only match as written; names match any case.
        strict = [w for w in words if w.isupper() or "." in w]
        loose = [w for w in words if w not in strict]
        parts = []
        if loose:
            parts.append(r"(?i:\b(?:" + "|".join(re.escape(w) for w in loose) + r")\b)")
        if strict:
            parts.append(r"(?<![\w.])(?:" + "|".join(re.escape(w) for w in strict) + r")(?![\w$])")
        pats[iso] = re.compile("|".join(parts))
    return pats


def masked(text, iso):
    """The text with other places' names blanked, so that "Sudan" is not found inside
    "South Sudan" and "Samoa" is not found inside "American Samoa"."""
    pat = NOT_THIS_COUNTRY.get(iso)
    return pat.sub(" ", text) if pat else text


def tag_countries(text, pats):
    return [iso for iso, pat in pats.items() if pat.search(masked(text, iso))]


def not_press(item):
    """The outlet is press, judged by its name and by its web address."""
    return not NOT_PRESS.search((item.get("publisher") or "") + " " + (item.get("publisher_url") or ""))


def country_domains():
    """ISO3 -> the country's web domain ending (".cl", ".ph"), from the World Bank's
    country list, which carries the two-letter codes the domains are built from."""
    cache = os.path.join(RAW, "wb_countries.json")
    if os.path.exists(cache):
        rows = json.load(open(cache))
    else:
        status, raw = fetch("https://api.worldbank.org/v2/country?format=json&per_page=400", timeout=60)
        rows = (json.loads(raw)[1] if raw else []) or []
        if rows:
            os.makedirs(RAW, exist_ok=True)
            json.dump(rows, open(cache, "w"))
    out = {r["id"]: r["iso2Code"].lower() for r in rows if r.get("id") and r.get("iso2Code") and len(r["iso2Code"]) == 2}
    out.update({"GBR": "uk", "COK": "ck", "NIU": "nu", "SHN": "sh", "PRK": "kp", "TWN": "tw", "MTQ": "mq", "GLP": "gp",
                "REU": "re", "GUF": "gf", "MYT": "yt", "FLK": "fk", "AIA": "ai", "MSR": "ms", "WLF": "wf", "TKL": "tk",
                "PCN": "pn", "NFK": "nf", "ESH": "eh", "JEY": "je", "GGY": "gg", "BES": "bq", "BLM": "bl", "SPM": "pm"})
    return out


def is_local(publisher_url, tld):
    """Is this outlet on the country's own web domain? (elmostrador.cl, gov.ph, news.co.ke)"""
    if not publisher_url or not tld:
        return False
    host = urllib.parse.urlparse(publisher_url).netloc.lower().split(":")[0]
    if not host.endswith("." + tld):
        return False
    if tld not in GENERIC_TLDS:
        return True
    return bool(re.search(r"\.(com|org|net|gov|gob|edu|ac|co)\." + re.escape(tld) + "$", host))


def search(iso, lang, name, today):
    """One news search, cached for the day so a re-run costs nothing."""
    cache = os.path.join(RAW, f"{today}_v2_{iso}_{lang}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f), True
    query, edition = SEARCHES[lang]
    q = urllib.parse.quote(query.format(name=name) + f" when:{WINDOW_DAYS}d")
    status, raw = fetch(f"https://news.google.com/rss/search?q={q}&{edition}")
    if status != 200:
        return status, False
    # A 200 that is not a feed - a consent page, an interstitial - is not "no news
    # here". It is not cached, and the country does not count as reached.
    try:
        root_tag = ET.fromstring(raw).tag.split("}")[-1].lower()
    except ET.ParseError:
        root_tag = ""
    if root_tag not in ("rss", "feed", "rdf"):
        return "not a feed", False
    items = []
    for it in parse_feed(raw):
        title = it["title"]
        if it["publisher"] and title.endswith(" - " + it["publisher"]):
            title = title[: -len(" - " + it["publisher"])]
        items.append({"title": title, "url": it["url"], "publisher": it["publisher"],
                      "publisher_url": it["publisher_url"],
                      "date": it["date"].date().isoformat() if it["date"] else None,
                      "lang": lang.split("_")[0]})
    os.makedirs(RAW, exist_ok=True)
    with open(cache, "w") as f:
        json.dump(items, f)
    return items, False


def main():
    os.makedirs(OUT, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).date().isoformat()

    # Which countries: every ISO3 the atlas has a country page for, with the name
    # the page uses. Territory zones inherit their parent's page, so they are not
    # searched separately.
    with open(os.path.join(OUT, "countries.json")) as f:
        zones = json.load(f)["countries"]
    isos = sorted({z["iso3"] for z in zones if z.get("iso3")})
    names = {}
    geo_path = os.path.join(OUT, "country.geojson")
    if os.path.exists(geo_path):
        with open(geo_path) as f:
            for ft in json.load(f)["features"]:
                p = ft["properties"]
                if p.get("iso3") in isos and p.get("name"):
                    names[p["iso3"]] = p["name"]
    for z in zones:                      # no land polygon: fall back to the zone's own name
        if z.get("iso3") and z["iso3"] not in names and z.get("iso_kind") != "territory":
            names[z["iso3"]] = re.sub(r"\s*\([^)]*\)\s*$", "", z["name"]).strip()
    # `python3 fetch_news.py CHL SEN` is a dry run for those countries: it prints
    # what would be kept and leaves news.json alone.
    only = {a.upper() for a in sys.argv[1:]}
    if only:
        names = {k: v for k, v in names.items() if k in only}
    print(f"News for {len(names)} countries, last {WINDOW_DAYS} days")

    found = {iso: [] for iso in names}

    # ---- sector feeds -------------------------------------------------------
    pats = country_patterns(names)
    tlds = country_domains()
    # A search result has to belong to the country it is filed under: either the
    # HEADLINE places it there (the country, its people, a well-known coast) or the
    # outlet sits on the country's own web domain. A search matches words anywhere
    # in an article, and an article that mentions Japan in passing is not Japanese
    # fisheries news - the first full run filed Trump's fishing orders under the UK.
    def in_title(item, iso):
        if iso in pats and tag_countries(item["title"], {iso: pats[iso]}):
            return True
        words = TITLE_WORDS.get(iso)
        return bool(words and re.search("(?i)\\b(?:" + "|".join(re.escape(w) for w in words) + ")\\b", masked(item["title"], iso)))

    def belongs(item, iso, strict=False):
        # strict: the wide fallback search matches so loosely that only a headline
        # naming the country counts; a local outlet also covers the rest of the world.
        if in_title(item, iso):
            return True
        return (not strict) and is_local(item.get("publisher_url"), tlds.get(iso))
    feed_names = []
    enso_found = []          # headlines for the El Nino card, from feeds and from search
    for label, url, topical in FEEDS:
        status, raw = fetch(url)
        items = parse_feed(raw) if raw else []
        kept = 0
        for it in items:
            if not it["date"] or it["date"].date().isoformat() < cutoff:
                continue
            if NOT_NEWS.search(it["title"]):
                continue
            if ABOUT_ENSO.search(it["title"]) and (label in OCEAN_OUTLETS or ABOUT_FISHING.search(it["title"])):
                enso_found.append({"title": it["title"], "url": it["url"], "publisher": label,
                                   "date": it["date"].date().isoformat(), "lang": "en", "via": "feed"})
            if not topical and not ABOUT_FISHING.search(it["title"]):
                continue
            # The headline names the place; failing that the summary may, but a
            # summary that lists four countries is a regional round-up, and filing
            # it under each of them would fill small countries with other people's news.
            where = tag_countries(it["title"], pats)
            if not where:
                where = tag_countries(it["summary"], pats)
                if len(where) > 3:
                    where = []
            for iso in where:
                found[iso].append({"title": it["title"], "url": it["url"], "publisher": label,
                                   "date": it["date"].date().isoformat(), "lang": "en", "via": "feed"})
                kept += 1
        print(f"  {label:<40} {len(items):>3} items, {kept:>3} country tags" + ("" if items else f"   (HTTP {status})"))
        if items and label not in feed_names:
            feed_names.append(label)

    # ---- news search --------------------------------------------------------
    searched = throttled = 0
    reached = set()          # countries whose searches actually got an answer
    if USE_NEWS_SEARCH:
        print("\n  searching Google News RSS, one country at a time")
        for i, (iso, name) in enumerate(sorted(names.items()), 1):
            english = ENGLISH.get(iso, name)
            plan = ([(LOCAL[iso][0], LOCAL[iso][1])] if iso in LOCAL else []) + [("en", english)]
            got = []
            for lang, label in plan:
                res, was_cached = search(iso, lang, label, today)
                if not isinstance(res, list):
                    throttled += 1
                    print(f"  [{i}/{len(names)}] {name:<28} {lang}: {'HTTP ' + str(res) if isinstance(res, int) else res} - backing off 60s")
                    time.sleep(60)
                    continue
                got += res
                reached.add(iso)
                searched += 0 if was_cached else 1
                if not was_cached:
                    time.sleep(SEARCH_DELAY)
            good = [g for g in got if is_fishing_news(g["title"]) and not_press(g)
                    and belongs(g, iso)]
            if len(good) < 3:             # a small country: widen the net, keep the filter
                res, was_cached = search(iso, "en_broad", english, today)
                if isinstance(res, list):
                    good += [g for g in res if is_fishing_news(g["title"]) and not_press(g)
                             and belongs(g, iso, strict=True)]
                    if not was_cached:
                        time.sleep(SEARCH_DELAY)
            for g in good:
                g = {k: v for k, v in g.items() if k != "publisher_url"}
                found[iso].append(dict(g, via="search"))
            if i % 20 == 0 or i == len(names):
                print(f"  [{i}/{len(names)}] {name:<28} {len(good):>2} headlines kept")
            if throttled >= 6:
                print("  ! throttled repeatedly - stopping the search early; what was found is kept")
                break

    # A dropped connection must not wipe what the last run found. If nothing at all
    # answered, news.json is left exactly as it was. Otherwise a country the search
    # never reached keeps its previous headlines, a feed that did not answer keeps its
    # previous items, and the El Nino card keeps its headlines if its searches failed.
    # The file records how much was carried over, and from which run.
    prev_path = os.path.join(OUT, "news.json")
    prev_file = {}
    if not only and os.path.exists(prev_path):
        with open(prev_path) as f:
            prev_file = json.load(f)
    if not only and not feed_names and not reached:
        print("\n  ! no feed and no search answered. news.json is left as it was; run again later.")
        return 1
    # The date each country's search last answered. For a country reached today that
    # is today; for one not reached it is carried forward unchanged from the previous
    # file, however many runs miss it, so a page never claims a fresher search than
    # the one that found its headlines.
    prev_answered = prev_file.get("searched") or {}
    last_answered = {}
    for iso in names:
        if not USE_NEWS_SEARCH or iso in reached:
            last_answered[iso] = today
        else:
            last_answered[iso] = prev_answered.get(iso) or prev_file.get("generated") or today
    carried = {"not_reached": sorted(set(names) - reached) if USE_NEWS_SEARCH else [],
               "kept": {}, "feeds": {}, "enso": None}
    if not only:
        prev = prev_file.get("countries") or {}
        silent_feeds = {label for label, _, _ in FEEDS if label not in feed_names}
        for iso, items in prev.items():
            if iso not in found:
                continue
            if USE_NEWS_SEARCH and iso not in reached:
                # held to the strict rule: the headline itself has to name the country
                kept = [i for i in items if i.get("via") == "search" and in_title(i, iso)]
                if kept:
                    found[iso] += kept
                    carried["kept"][iso] = last_answered[iso]
            old_feed = [i for i in items if i.get("via") == "feed" and i.get("publisher") in silent_feeds]
            for i in old_feed:
                found[iso].append(i)
                carried["feeds"][i["publisher"]] = carried["feeds"].get(i["publisher"], 0) + 1
        if carried["not_reached"]:
            print(f"  ! the search did not answer for {len(carried['not_reached'])} countries; "
                  f"{len(carried['kept'])} of them keep earlier headlines")
        if carried["feeds"]:
            print(f"  ! {sum(carried['feeds'].values())} headlines kept from feeds that did not answer this run")

    # ---- the El Nino card ---------------------------------------------------
    # Which phenomenon to search for comes from the atlas's own reading of the index.
    phenomenon = "El Niño"
    try:
        with open(os.path.join(OUT, "climate.json")) as f:
            state = str((json.load(f).get("enso") or {}).get("state") or "")
        if "nina" in state.lower():
            phenomenon = "La Niña"
    except (OSError, ValueError):
        pass
    enso_answered = False
    if USE_NEWS_SEARCH and not only:
        for lang in ("en_enso", "es_enso"):
            res, was_cached = search("ENSO", lang, phenomenon, today)
            if isinstance(res, list):
                enso_answered = True
                for g in res:
                    if (ABOUT_ENSO.search(g["title"]) and ABOUT_FISHING.search(g["title"])
                            and not NOT_NEWS.search(g["title"]) and not_press(g)):
                        enso_found.append(dict({k: v for k, v in g.items() if k != "publisher_url"}, via="search"))
                if not was_cached:
                    time.sleep(SEARCH_DELAY)
        if not enso_answered and prev_file.get("enso"):
            enso_found += prev_file["enso"]
            carried["enso"] = ((prev_file.get("carried_over") or {}).get("enso")) or prev_file.get("generated")
            print("  ! the El Nino searches did not answer; the card keeps its previous headlines")
    enso_out, seen = [], set()
    for it in sorted((x for x in enso_found if x.get("date") and x["date"] >= cutoff),
                     key=lambda x: x["date"], reverse=True):
        key = re.sub(r"[^a-z0-9]+", "", it["title"].lower())[:48]
        if key in seen or any(same_story(it["title"], k["title"]) for k in enso_out):
            continue
        seen.add(key)
        enso_out.append(it)
    enso_out = enso_out[:4]
    print(f"  El Nino card: {len(enso_out)} headlines kept for '{phenomenon}'")

    # ---- merge --------------------------------------------------------------
    out = {}
    for iso, items in found.items():
        seen, keep = set(), []
        own_names = " ".join([names[iso], ENGLISH.get(iso, ""), LOCAL.get(iso, ("", ""))[1]] + ALIASES.get(iso, []))
        ignore = set(re.findall(r"[^\W\d_]{4,}", own_names.lower()))
        for it in sorted((x for x in items if x.get("date") and x["date"] >= cutoff),
                         key=lambda x: x["date"], reverse=True):
            # the same wire story under two mastheads differs only at the tail of the headline
            key = re.sub(r"[^a-z0-9]+", "", it["title"].lower())[:48]
            if key in seen or it["url"] in seen or any(same_story(it["title"], k["title"], ignore) for k in keep):
                continue
            seen.update({key, it["url"]})
            keep.append(it)
        if keep:
            out[iso] = keep[:PER_COUNTRY]

    # ---- English for every headline that is not English ---------------------
    cache = {}
    if os.path.exists(TRANSLATIONS):
        with open(TRANSLATIONS, encoding="utf-8") as f:
            cache = json.load(f)
    spent, done, waiting = [0], 0, 0
    # The El Nino card first, then the partner NGO's countries, then everyone else.
    first = ["BRA", "FSM", "GTM", "HND", "IDN", "MOZ", "PHL", "PLW"]
    queue = list(enso_out) + [i for iso in first for i in out.get(iso, [])] + \
            [i for iso, items in sorted(out.items()) if iso not in first for i in items]
    for it in queue:
        if it.get("lang", "en") == "en":
            continue
        en = translate_to_english(it["title"], it["lang"], cache, spent) if not only else \
            (cache.get(f"{it['lang']}|{it['title']}") or {}).get("en")
        if en:
            it["title_en"] = en
            done += 1
        else:
            waiting += 1
    if not only:
        with open(TRANSLATIONS, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"  translations: {done} headlines have English, {waiting} still waiting"
          f" ({spent[0]} characters sent this run; the daily allowance is {TRANSLATE_BUDGET})")

    if only:
        for iso, items in out.items():
            print(f"\n  {names[iso]}")
            for it in items:
                print(f"    {it['date']}  [{it['via']}/{it['lang']}] {it['publisher'][:24]:<24} {it['title'][:90]}")
        return 0

    with open(os.path.join(OUT, "news.json"), "w") as f:
        json.dump({
            "generated": today,
            "window_days": WINDOW_DAYS,
            "sources": {"feeds": feed_names,
                        "search": "Google News RSS search, one query per country" if USE_NEWS_SEARCH else None},
            "note": ("Headlines collected automatically and filtered by keyword. Nobody has read "
                     "them; a headline here is a pointer, not an endorsement."),
            "enso": enso_out,
            # when each country's search last answered, and what this run carried over
            "searched": last_answered if USE_NEWS_SEARCH else None,
            "carried_over": carried if (carried["not_reached"] or carried["feeds"] or carried["enso"]) else None,
            "countries": out,
        }, f, indent=1, ensure_ascii=False)

    total = sum(len(v) for v in out.values())
    print(f"\n  wrote {total} headlines across {len(out)} of {len(names)} countries"
          f" ({searched} searches run, {throttled} throttled)")


if __name__ == "__main__":
    sys.exit(main())
