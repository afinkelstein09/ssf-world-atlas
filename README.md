# Small-Scale Fisheries World Atlas — prototype

A first working prototype of a global atlas of small-scale fisheries, built for Rare.

Ninety percent of the world's fishers are small-scale, and they land roughly half the
world's catch — but the space has nothing like the data infrastructure that forests have
in Global Forest Watch. This maps where small-scale catch actually is, and how well we
know it.

**Status: prototype.** Everything here comes from public data. Nothing is official.

## What it shows

Every one of the world's **282 exclusive economic zones**, coloured six ways, grouped in
the left rail as catch and economy, people, environment, and about the data:

- **Small-scale share of catch** — what fraction of each EEZ's landings come from
  artisanal and subsistence fishing, averaged over the last five years of record.
  A switch in the legend reads the same share **in dollars instead of tonnes**: small
  boats land the expensive fish, so Peru is 20% small-scale by weight and 43% by value.
- **People** — how many are employed in small-scale fisheries per 1,000 population:
  national figures, inland and marine, fishing and processing and trade, painted on every
  zone of a country (landlocked countries are left as plain land). This is the honest
  counterweight to the catch map: Indonesia is only a third small-scale by tonnage but has
  11.6 people in small-scale fisheries per 1,000, while Guatemala is 76% small-scale by
  tonnage and has 1.8.
- **Marine heatwave** — how far the sea surface temperature exceeds each location's own
  climatology, on NOAA's six-step scale, read in one sample area about 130 km across
  inside each zone (not averaged over the whole zone), refreshed when the script is run.
- **Overfishing** — the share of each zone's fish populations that Sea Around Us rates
  over-exploited or collapsed in 2019, judged from each population's catch history rather
  than from scientific surveys, and the legend says so. 188 of 282 zones have a reading;
  the rest are hatched.
- **Data confidence** — how complete the catch record is. Gaps are shown, not hidden.

The six views use one hue each (Andrew's palette of 26 September 2026: blue, violet,
raspberry, amber, slate, and for heatwaves the cool blue-grey for "none" then yellow to
dark red), drawn light to dark; the previous ramps are in
`data/backups/2026-09-26-pre-colours/index.html`.

A live ENSO reading sits in the header, because El Niño is the single most
consequential recurring signal for small-scale fisheries.

A "Conservation groups" overlay outlines the countries where Rare's Fish Forever programme
works (highlighter orange on a white casing) and where Blue Ventures works (highlighter
yellow on a dark casing, so it survives a pale sea); a country on both lists gets yellow
dashes over the orange, and a key under the switch says which is which. Project and
community sites are brown dots: aid-funded projects that reported a map location to
IATI (895 points from 400 projects; a point that is really a region, a capital or the
country itself is drawn faint) and records from the Too Big To Ignore research network
(519 records; those with no site of their own sit faint at the country's centre). Clicking a dot
opens a card with the project or record, its dates and reporter, and a link to the
record on d-portal or ISSF. Blue Ventures' list is in
`site/data/groups.json` with the page it was read from and the date. Clicking any zone opens catch by
sector and a 70-year history, what the catch is worth, whose fleets take it, access
rights and law, livelihoods, current ocean heat, the state of the ecosystem (stock
status, threatened species by name, reefs and mangroves, protected waters), an
organisation directory in which every entry opens to its own pages and its reported
fisheries work, and recent fisheries headlines for the country.

## Running it

```bash
python3 scripts/fetch_saup.py     # catch by sector, per EEZ  (~4 min first run)
python3 scripts/fetch_people.py   # livelihoods, population   (~2 min)
python3 scripts/fetch_climate.py  # ENSO + heat stress        (~4 min)
python3 scripts/fetch_orgs.py     # aid-funded project sites  (~3 min)
python3 scripts/fetch_issf.py     # ISSF profiles + orgs      (~1 min)
python3 scripts/fetch_fleets.py   # foreign fleet shares      (~4 min)
python3 scripts/fetch_value.py    # landed value, prices      (~6 min first run)
python3 scripts/fetch_ecosystem.py # stocks, species, habitat (~20 min first run)
python3 scripts/check_links.py    # test every outbound link  (~2 min)
python3 scripts/build_profile.py  # organisation directory    (instant, local)
python3 scripts/build_regulatory.py  # laws and legal links   (instant, local)
python3 scripts/build_country_geo.py # country polygons       (instant, local)
python3 scripts/fetch_paa.py      # preferential access areas (needs the gpkg)
python3 scripts/fetch_news.py     # headlines per country     (~12 min, slow on purpose)
python3 -m http.server 8891       # then open http://localhost:8891/site/
```

Every script caches to `data/raw/`, so re-runs are close to instant. The only
dependency beyond the standard library is `openpyxl`, for reading FAO's workbooks.
No API keys anywhere.

**About the news script:** it makes one search per country, a little over a second apart,
and caches each day's results, so a cold run takes about twelve minutes and a re-run the
same day is instant. `python3 scripts/fetch_news.py CHL SEN` is a dry run for those
countries that prints what would be kept and leaves the site's file alone. Run
`check_links.py` before `build_profile.py`: the directory leaves out any organisation
link the checker found dead.

## How it's built

```
scripts/countries.py     resolves EEZ names to ISO3 — the join everything depends on
scripts/fetch_saup.py    catch by sector, per EEZ (Sea Around Us)
scripts/fetch_people.py  livelihoods and population (IHH, World Bank, FAOSTAT)
scripts/fetch_climate.py ENSO and ocean heat stress (NOAA)
scripts/fetch_paa.py     preferential access area boundaries (Duke)
scripts/fetch_orgs.py    aid-funded fisheries activities (IATI)
scripts/fetch_issf.py    community profiles and organisations (ISSF)
scripts/fetch_fleets.py  catch by fleet nationality per EEZ (Sea Around Us)
scripts/build_profile.py merges organisations into a categorised country directory
scripts/build_regulatory.py access law, SSF Guidelines status, FAOLEX links
scripts/build_country_geo.py country landmasses for the 'by country' scale
scripts/fetch_news.py    recent fisheries headlines (Google News search + feeds)
data/raw/                cached API responses — safe to delete, costs time not money
site/                    the deployable site — this folder is the whole website
site/data/               generated JSON, written by the pipelines
```

`scripts/countries.py` deserves a note. Sea Around Us names EEZs for fishing purposes
("Indonesia (Central)", "Azores Isl. (Portugal)"), while every other dataset is keyed by
ISO3. That resolver bridges the two and reaches all 282 zones, tagging each match as
`self`, `split`, or `territory`. Territory matches inherit their parent country's national
statistics — the Azores are not Portugal — so the site says so on the page rather than
quietly presenting the wrong number.

The site is static: HTML, JavaScript, and JSON files. There is no server and no database.
"Living" comes from re-running the pipeline on a schedule and republishing — the same
two-speed model Global Forest Watch uses, where a slow authoritative layer sits under
faster-moving signals.

`site/` is self-contained on purpose. It is the only directory that gets deployed, so
anything the page needs at runtime has to live inside it.

## Two scales

The atlas can be read **by ocean zone** or **by country**, and the switch changes the
geometry, not just the colour. Catch is published per exclusive economic zone, which is how
the science works but not how most people think — Indonesia is three zones, the USA is
twelve (Puerto Rico, Guam and the other US territories have their own codes). In country mode the land itself is drawn and coloured, using Sea Around Us's own
country polygons so both scales key on the same ISO3 codes.

Rolling up is weighted by tonnage rather than averaged, so a small zone cannot outvote a
large one. Confidence takes a country's *weakest* record and marine heatwave takes its
*worst*: a country page should not hide a problem sitting in one of its zones. Every
country page lists the zones it combines, and clicking one drops back into that zone.

## Data sources

**Sea Around Us** (University of British Columbia) — reconstructed marine catch by sector,
1950–2019, via `api.seaaroundus.org`. This is the only global source that splits catch into
artisanal, subsistence, industrial, and recreational, which is what makes the whole map
possible.

**Illuminating Hidden Harvests** (FAO/Duke/WorldFish, 2023) — employment in small-scale
fisheries for 187 countries, disaggregated by gender, CC BY 4.0. A one-off 2023 baseline,
explicitly *not* official country statistics. Two things to know: employment and
subsistence are reported separately here rather than summed, because IHH counts
subsistence as household food production — combining them would claim half of Kiribati
"works in fisheries", which is not what the data means. And the figures are national, so
they are not split across a country's several EEZs. 109 of the 187 country figures are
IHH's own extrapolations from regional patterns rather than survey results; the People
section says so wherever that is the case. Taiwan has no World Bank population series, so
its rate uses a fixed 23.4 million.

**Preferential access areas** — DeLand, Vegh, Cleary, Basurto, Virdin & Halpin (2025),
*A global dataset of preferential access areas for small-scale fishing*, Duke Research Data
Repository, doi:10.7924/r40s01h5j, **CC0**. Accompanies Basurto et al. (2024) in *npj Ocean
Sustainability*. 44 countries have formally reserved nearshore waters for small-scale
fishers; this is the closest thing that exists to a map of small-scale fishing *rights*
rather than activity. Two notes: the authors describe 63 areas across 44 countries as a
**lower bound**, since a country can create one through law outside the fisheries code and
it would not appear; and only 12 of the 44 boundaries have been confirmed by a local
expert, the rest being reconstructed from the text of the law. Both facts are surfaced in
the interface.

**Aid-funded activity** — IATI Registry via the Code for IATI Datastore
(datastore.codeforiati.org), open data, no key. 1,460 fisheries activities across 122
coastal countries, filtered to those devoting at least 25% of their sector allocation to
fisheries purpose codes (activities that state no percentages are kept, so small
publishers are not filtered out).

Two things this layer is not. It reports **aid-funded** work, so organisations financed by
private philanthropy are largely absent — Rare, Blue Ventures, EDF, Oceana and The Nature
Conservancy return zero matches, while FAO alone accounts for 351 implementing roles. And
only **27% of activities carry coordinates**, so the map shows where reported work is
geocoded, not where work is. Both facts are stated in the interface.

**Organisation directory** — 2,156 entries across 147 countries, merged from three
sources and sorted into the categories Rare asked for: government, fisher organisations,
international NGO, national/local NGO, donors, research, private sector.

The fisher organisations come from **Annex A: SSF Organisations by Region**, 120 bodies
compiled from WFFP, ICSF and project files and supplied by Rare. They are the fishers' own
representative organisations and appear in no other source here — 117 placements across
56 countries, and 11 regional networks listed separately.

Categories are assigned by rule from organisation names and the roles sources report, with
two decisions worth knowing. A ministry is only *government* on its own country's page:
Denmark's foreign ministry appearing under Indonesia is a bilateral donor, and filing it as
government would answer the wrong question. And named aid agencies are checked before the
government pattern, because most of them are ministries at home — BMZ and Irish Aid are
departments of foreign affairs.

**416 of the 2,156 are left unclassified**, and deliberately so. Guessing Rare into the
donor column would be worse than an honest blank.

The gap this exposes is the one worth acting on. Of the organisations Rare named as
examples, **Rare itself appears in zero countries**, The Nature Conservancy zero,
Environmental Defense Fund zero, WCS one, Blue Ventures one (via ISSF), Conservation
International three. WWF reaches twelve only because it publishes to IATI. Privately
funded conservation NGOs do not appear in aid reporting, so the directory sees the donors
and the fishers clearly and the implementers barely at all.

**Foreign fishing** — Sea Around Us, catch by fishing entity within each EEZ
(`/api/v1/eez/tonnage/country/`), all 282 zones, five-year mean. This is the layer a
fisheries ministry acts on: of everything landed from a country's waters, how much leaves
with someone else's fleet.

Two handling notes. A country's own fleet has to be identified by resolving the fleet name
to ISO3 rather than matching strings — Sea Around Us calls the fleet "Russian Federation"
and the zone "Russia (Barents Sea)", and without the bridge Russia read as 100%
foreign-fished in its own waters. And catch attributed to no identified fleet is held as
its own category rather than counted as foreign; folding it in overstated Micronesia by
twelve points.

It is a reconstruction, not a landings record, and it does not distinguish licensed access
from unlicensed fishing.

**Community and organisation records** — Information System on Small-scale Fisheries
(ISSF), Too Big To Ignore, issfcloud.toobigtoignore.net. Public API, no key. 519 mappable
records across 129 countries: 297 community profiles, 151 organisations, 67 blue justice
cases, 4 case studies. 320 sit at a real site; the other 199 are national or regional
records, or were placed on a country centroid, and are drawn hollow so the map does not
pretend to a precision it lacks.

It is here because it sees what IATI cannot. IATI reports aid-funded activity; ISSF is
contributed by researchers, so WCS, WorldFish and other privately funded organisations
appear. Two caveats, stated in the interface: it is **largely dormant**, with most records
contributed between 2013 and 2016 and one so far in 2026; and its coverage is **academic
rather than geographic** — Spain holds 27 organisation records, more than any other
country, which maps where contributing researchers work rather than where small-scale
fishing is.

Together the two sources reach 151 of the atlas's 178 coastal countries and territories,
but **only 89 appear in both.** 29 are in ISSF alone and 33 in IATI alone. Neither source
is close to sufficient on its own, which is the clearest available evidence that this
layer has to be assembled rather than downloaded.

**NOAA** — the Oceanic Niño Index and weekly Niño region anomalies from the Climate
Prediction Center, and two heat products from Coral Reef Watch via the PacIOOS ERDDAP
server. Public domain.

The headline heat metric is the **marine heatwave category**, which classifies sea surface
temperature against each location's own climatology on a six-step scale. It replaced degree
heating weeks, which was the wrong instrument twice over: DHW's 4 and 8 thresholds come from
coral bleaching studies, so the number means nothing for Peru's anchoveta or Norway's cod,
and because it is only meaningful in the tropics the layer silently omitted most of Europe
and North America. Switching metrics took coverage from 208 zones to 266 and made the
values comparable between oceans; sampling at a point inside each zone, rather than at
its centre of mass (which for a coastal zone is usually the coast), took it further. The
zones without a reading are polar sea ice.

Degree heating weeks is still reported, as its own line, within 35° of the equator and
labelled as the coral-specific measure it is. The heatwave archive begins July 2024, so it
is a current-conditions layer, not a historical one.

**Landed value** — Sea Around Us prices every tonne it reconstructs, through the same API
and for the same 282 zones as the catch (`/eez/value/sector/` and `/eez/value/country/`),
in real 2010 US dollars. `fetch_value.py` uses the same five-year window and the same
small-scale definition as the catch script, so the share of value sits beside the share of
tonnes and means the same thing. Across all zones the catch is worth about $137 billion a
year and small-scale fishing earns 32% of it, against 27% of the tonnes. The gap is the
story: Peru's small boats land 20% of the tonnes and 43% of the value, because the
industrial fleet's anchoveta sells for $374 a tonne and the small boats' food fish for
$1,126. The share-of-catch view has a tonnes/value switch, and each panel has a "What
it's worth" section with prices per tonne and the foreign fleets' share of the value.

Three things to know. It is an estimate: reconstructed catch priced from a global
database of prices at the dock, not sales records. **Six zones are flagged as unreliable**
because a sector is priced under $200 a tonne, far below the roughly $1,200 to $3,400 a
tonne at which the middle half of zones price small-scale catch: the three Kiribati zones ($24 to $29 a tonne for
small-scale catch), Eritrea ($31), and the industrial catch of Bahrain and Kuwait. Eritrea's
small-scale share falls from 42% of tonnes to 4% of value on that price alone. Flagged
zones show their numbers under a caution and are left uncoloured in the value view. And a
country's figures are sums of dollars and tonnes across its zones, never averages of
percentages.

**A second estimate for the Pacific** — Gillett and Fong (2023), *Fisheries in the economies
of Pacific Island countries and territories* (Benefish Study 4), Pacific Community, Tables
29-1 and 29-2. Volumes and values for 22 island countries and territories in 2021, from
fisheries agency reports and household surveys. Its "coastal commercial" plus "coastal
subsistence" is the region's small-scale sector: Kiribati lands 19,000 t worth $44 million,
about $2,300 a tonne, where Sea Around Us's price is under $30. The table is transcribed in
`data/pacific_benefish_2021.csv` (the column sums match the six totals printed in the
study) and shown beside the Sea Around Us figures, never blended with them: different
method, different year, nominal dollars. SPC authorises partial reproduction for research
and education with acknowledgement.

**Diet and GDP** — fish and seafood supply per person from FAO's food balance sheets, read
through Our World in Data's country file (192 countries, 2023), and UN SDG indicator
14.7.1, sustainable fisheries as a share of GDP (132 countries). Both are national: a
territory zone does not inherit its parent's, and one zone of several says "national".

**Ecosystem** — `fetch_ecosystem.py`, per ocean zone wherever the source allows.

*State of fish populations* is Sea Around Us's stock-status plot for the zone: the share
of fished populations that are developing, exploited, over-exploited, collapsed or
rebuilding, in the latest year (2019 everywhere). 188 of 282 zones have one; in the median
zone 57% are over-exploited or collapsed. **It is read from each population's catch history
against its peak, not from scientific surveys**, and the panel says so beside the bar. The
shares are of the populations classified that year, which is fewer than the number on
record since 1950 (Sudan: eighths, eight populations, while eleven are on record);
`count_classified()` recovers the year's count from the published shares and the label
uses it, with the number on record shown separately. Where two or more counts fit the shares (17
zones, 4 of them with the whole year in one category) the label gives no count and the
warning says what the shares allow: "fit as few as N of the n on record", or, for a
year wholly in one category, that they do not say how many were classified.

*Threatened species* come from OBIS: species with an IUCN Red List category of Vulnerable,
Endangered or Critically Endangered that have been recorded inside the zone. Each zone is
queried with a simplified outline of itself (tolerance 0.02° for most, up to 0.58° for the
Canadian Arctic), so the Azores get their own answer rather than Portugal's. The outline
is queried without its land holes, so the coast and islands are inside it: shorebirds and
mangroves count, and a hand-checked list (`NOT_MARINE`, 34 species: a steppe lapwing, two
geese, river terns, a dragonfly, a freshwater plant, freshwater fish, an Amazon river
turtle) is left out. OBIS also holds records placed far outside a species' range (a
Tasmanian handfish in Finland and Poland; a polar bear, walrus, sea otter and vaquita in
India's waters); the clearest are left out by hand too (`RANGE_ONLY`, `OUT_OF_RANGE`,
audit of 6 October 2026), and the page says others may remain. The first list was made
after the first build named the sociable lapwing among Germany's threatened marine species.
Each zone also carries its list by animal group split by Red List category, drawn as
thin bars in the panel with a line naming where the critically endangered species sit
when one group holds most of them. **The count is never painted on the map**: it tracks how
much surveying has been done (Australia 472, Japan 412, and three zones with none on
record), so it lives in the panel next to that caveat. Up to five species are named, the
critically endangered first. English names come from a table checked by hand, because the
first attempt took names from WoRMS automatically and labelled the whale shark "Basking
shark"; a species not in the table is shown by its scientific name.

*Pressure*: the unreported share of the catch (median 29%), the discarded share, and the
five largest catches by taxon, all Sea Around Us. *The zone itself*: shelf area, inshore
fishing area, share of the world's tropical reefs and primary production, from Sea Around
Us's zone metrics. *National*: mangrove area 1996 to 2020 from the Ocean Health Index
habitat layer (95 countries), and marine protected areas as a share of territorial waters
from the World Bank (207 countries and territories).

On a country page with several zones, stock status and species are listed zone by zone
rather than totalled: the same stock and the same turtle turn up in neighbouring zones.

**News** — two routes, merged per country. RSS feeds from outlets that cover fisheries
(Mongabay, the Guardian's fishing desk, CFFA on West African artisanal fishing, the Pacific
Forum Fisheries Agency, Blue Ventures, Oceana, Global Fishing Watch, plus RNZ Pacific and
AllAfrica filtered by headline), tagged with the countries they name. And one Google News
RSS search per country in the language its press writes in: "pesca artesanal" for Chile,
"pêche artisanale" for Senegal, "nelayan" for Indonesia.

A headline is kept only if it is about fishing, and only if it belongs to the country:
the headline names the country, its people or a well-known coast, or the outlet sits on
the country's own web domain. The first version used GDELT and matched words anywhere in
an article, which filed a lobster restaurant guide under Belize; the first run of this
version filed Trump's fishing orders under the United Kingdom until the headline rule was
added, and a Guinea-Bissau shipwreck under Guinea until a country's name inside another
name was masked (`NOT_THIS_COUNTRY`: South Sudan, American Samoa, Northern Ireland, the
Indian Ocean and so on). Social-network posts are not press. Two headlines are one story
only when they share three content words beyond the search's own vocabulary. A run that
gets no answer from any source leaves `news.json` untouched; a country the search did not
reach, a feed that did not answer and the El Niño card keep their previous headlines, and
the file records what was carried over. Headlines are collected by machine and nobody has
read them; the panel says so.

**Headlines in the reader's language.** Every headline that is not in English is
translated into English once, at build time, by MyMemory's free machine translation, and
kept in `data/news_translations.json` so it is never translated twice. A reader whose
browser is set to another language gets that language from the browser's built-in
translator, where it has one (desktop Chrome and Edge only; no phones, no Tagalog). A
translation is always marked, and one click shows the original. MyMemory allows 5,000
characters a day without an address and 50,000 with a contact email, which travels in the
URL and is kept by the service, so `TRANSLATE_CONTACT_EMAIL` in `fetch_news.py` is left
empty for whoever runs it to decide. The El Niño card has its own small news block, from
one search for the phenomenon and fishing together, in English and Spanish.

There is no official Google News API (Google closed it in 2011). The RSS search feed is
public and keyless, and its terms are written for personal, non-commercial use: fine for
a prototype, **worth checking before an organisation hosts this publicly**. It sits behind
one switch, `USE_NEWS_SEARCH` in `fetch_news.py`, and the sector feeds work without it.

**Links** — every organisation in the directory opens to what is on record for it: the
fisheries work the aid registry names it on in that country (each linked to its IATI
record on d-portal), its ISSF record, and, for the fisher organisations in Rare's annex
and the bodies that recur across many countries, a web page from `data/org_links.json`.
That table was assembled by search and then checked: a page counts only if it answered and
named the organisation. Nothing is guessed at build time, and where no page is on record
the box says so and offers a search, labelled as a search. `check_links.py` re-tests every
outbound link (organisation pages, law texts, the fixed links in source notes), sorts
them into ok / blocked to scripts / dead, and writes `data/link_check.json`; the directory
build leaves out anything dead. It exists because in September 2026 six of the eight law
links pointed at an FAO host that had stopped answering and nothing noticed. Those six now
point at the same files on faolex.fao.org.

**World Bank and FAOSTAT** — population, food insecurity, and food balance sheets. CC BY 4.0.

Important caveats, which the site states publicly:

- These are *reconstructions*, not official national statistics. They combine reported
  landings with estimates of unreported catch, using anchor points, interpolation, and
  expert judgment.
- Sea Around Us scores its own uncertainty from ±10% to ±50% depending on sector and era.
- Marine mammals, corals, plants, the aquarium trade, and ghost fishing are excluded, so
  totals are conservative.
- Use requires attribution under their citation policy:
  https://www.seaaroundus.org/citation-policy/

The **data confidence** score is our own heuristic, not a Sea Around Us product. It reflects
how complete each record is — missing values, series length, and catch volume. It is
labelled as an estimate everywhere it appears.

The **heat stress severity** is also ours. NOAA's own Bleaching Alert Area combines degree
heating weeks with an instantaneous hotspot test; we derive severity from mean DHW over a
zone using NOAA's published 4 and 8 thresholds instead. Taking NOAA's maximum alert across
a sampled box let one hot coastal pixel speak for an entire EEZ — Portugal briefly showed
degree heating weeks of 47 that way, against a real value near 9. Hence mean plus a 90th
percentile, and hence "heat stress" rather than "bleaching alert" in the interface.

Basemap: CARTO dark matter, © OpenStreetMap contributors.

## Known gaps

Things a funded version would need that this prototype does not have:

- **The organization layer.** The genuinely unoccupied ground in this space is mapping
  *who works where* — NGOs, community institutions, managed-access areas. Every existing
  atlas maps fish, catch, or vessels instead. This prototype only stubs that in via the
  Fish Forever outlines. IATI's aid database is the way in and is verified workable; see
  `DATA-ROADMAP.md`.
- **Sub-national resolution.** EEZs are whole countries. Small-scale fishing is local, and
  the interesting variation happens well below this scale. Employment figures are national
  too, so a country's several EEZs all show the same livelihoods number.
- **Palau and Micronesia have no livelihoods data.** IHH covers 187 countries but not those
  two — which is exactly where the catch metric misleads worst. The people layer fixes the
  problem in general and misses the cases that motivated it. Shown as a gap, not hidden.
- **The catch record ends in 2019.** That is where Sea Around Us reconstructions stop. FAO
  FishStat runs to 2024 and would extend it, at the cost of losing the sector split.
- **Heat is sampled, not zonal.** One 1.2° box at a point inside each EEZ, not a true
  average over the polygon. Fine for a signal, wrong for analysis; for zones narrower
  than the box (Bosnia, Iraq, Singapore) the box is mostly a neighbour's water.
- **News is unread.** Headlines come from a Google News search per country and fisheries
  feeds, filtered by keyword (the first version, on GDELT, filed a Belize restaurant guide
  under Belize and was dropped). Nobody reads them before they appear, and the Google
  News RSS terms are for personal, non-commercial use.
- **The organisation layer is half a map.** IATI covers aid-funded work well and privately
  funded conservation NGOs barely at all. The half it misses is the half Rare belongs to,
  which is the argument for asking organisations to contribute directly.
- **Nutrition and governance are untouched.** IHH also publishes micronutrient contribution
  and tenure/access-rights workbooks. Both are wired for, neither is wired in.
