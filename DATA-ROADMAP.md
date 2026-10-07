# What would take this atlas to the next level

A survey of data that could be added to the Small-Scale Fisheries World Atlas prototype,
which currently runs on a single source (Sea Around Us reconstructed catch by sector).

Compiled 2026-08-13. Every endpoint below was tested live — this is a list of what is
actually fetchable, not a list of what exists. Where something is gated, blocked, or
broken, that is stated.

---

## The short version

Three additions would change what this atlas *is*, rather than just adding layers:

1. **IHH Livelihoods** turns the map from tonnes into people — and fixes a real flaw in
   the current prototype.
2. **IATI** builds the "who works where" layer that no existing marine atlas has.
3. **VIIRS Boat Detection** puts actual fishing boats on the map at point resolution,
   including boats that carry no transponder.

Everything else is depth. Those three are the difference between a catch map and an atlas.

---

## 1. The metric problem, and its fix

The prototype has an honest flaw. Palau reads as 22% small-scale and Micronesia as 1.4%,
which makes them look like Rare's least small-scale countries. That is an artifact:
industrial tuna fleets dominate tonnage inside those EEZs, which says nothing about how
much small-scale fishing matters to the people living there. **Catch tonnage is the wrong
headline metric**, and the atlas currently leads with it.

**Illuminating Hidden Harvests — Livelihoods workbook** is the fix, and it is better than
expected. Verified by download:

- `https://www.fao.org/3/cd3915en/IHH_Livelihoods_data.xlsx` — 322 KB, CC BY 4.0, no key
- **187 countries** — more than triple the 58 in the IHH catch workbook
- Columns: employment in SSF, **women's employment in SSF**, employment in large-scale
  fisheries, women's employment in LSF, subsistence workers, women in subsistence SSF
- Each split pre-harvest / harvest / post-harvest, inland and marine, with per-value
  quality flags and the source survey named

This is the only global dataset built to count fisheries *people* rather than fisheries
tonnes, and it is the only one that carries gender through every category. Parser note:
the header spans merged rows 1–4, so a naive `read_excel` gets garbage — skip to the real
header row.

**The composite worth building — a dependence index:**

| Component | Source | Status |
|---|---|---|
| SSF workers per 1,000 coastal residents | IHH Livelihoods ÷ SEDAC LECZ | LECZ needs free NASA login |
| Fish as % of animal protein | FAOSTAT Food Balance Sheets, 54.8 MB CSV | keyless, CC BY |
| Vulnerability | World Bank food insecurity `SN.ITK.MSFI.ZS` or UNDP HDI | keyless |

That index reframes Palau from "barely small-scale" to what it actually is, and it is the
sentence a funder remembers. It is also the strongest possible answer to "why does this
atlas exist when Sea Around Us already publishes catch data."

Other IHH workbooks, by usefulness:

- **Nutrition** (58 countries) — calcium, iron, protein, omega-3, selenium, zinc, vitamin A
  by species group. The "this fishery feeds people" layer.
- **Governance** (51 countries) — access strategies (licensing, historical use, residence,
  registration, open access), harvesting measures, devolved rights, each as both
  presence/absence and catch-weighted tonnage. A genuine tenure layer; nothing else has this.
- **Ex-vessel price** (7,241 rows, 58 countries) — prices by species and year, with a count
  of imputed values, so you can be honest about which numbers are estimates.
- **Export** — only 12 countries. Too thin to map.
- **Matrix** — countries are anonymized as "Country1"…"Country50". Unmappable. Use only for
  global distributions.

---

## 2. The organization layer — the unoccupied ground

Prior research established that every existing marine atlas maps fish, catch, or vessels,
and none maps who is working where. The SSF Hub, the field's own platform, has no map at all.

**IATI (International Aid Transparency Initiative) is the way in, and it works today.**

- `https://datastore.codeforiati.org/api/1/access/activity.json` — **no API key**
- Verified live: `?sector=31320` (fishery development) returns **1,457 activities**;
  `31310` (fishing policy and administration) 1,291; `31382` (fishery education) 296
- Stackable with `recipient-country=MG` and other filters
- Activities carry `location[]` with real lat/lon, plus reporting organization,
  participating organizations by role (funding / implementing / accountable), budgets,
  and dates
- One returned record: *"Madagascar — Tuléar Fishing Communities Support Project"*,
  geocoded to Morombe District
- Refreshed nightly from the IATI Registry

Caveat: roughly 40–60% of activities are geocoded; the rest need a country-centroid
fallback. Note also that the official IATI endpoint at `api.iatistandard.org` requires a
free key — the Code for IATI mirror above does not.

**Policy context to sit underneath it — SDG indicator 14.b.1:**

- `https://unstats.un.org/SDGAPI/v1/sdg/Series/Data?seriesCode=ER_REG_SSFRAR`
- 1,100 records, keyless JSON, scores each country 1–5 on degree of application of a
  small-scale fisheries access-rights framework, sourced from FAO
- The only global comparable measure of SSF Guidelines implementation

**Stock sustainability — SDG 14.4.1:** also on the UN SDG API, ~105 countries plus all 15
FAO Major Fishing Areas, 2004–2024. Not PDF-trapped, contrary to assumption.

### Licensing constraints that shape the build

**WDPA / Protected Planet** (the global protected-areas database) is the one to be careful
with. Its terms **prohibit redistribution** — you may not re-serve WDPA data "through
downloads, web services, interactive maps, or file transfer protocols" without written
permission. You *may* display it if the data stay non-downloadable, attribution is visible,
and you link back with the release date.

Practical consequence: render protected areas as a display-only layer, ship no WDPA
geometry in `site/data/`, and never put a download button on it. Anything more needs
written permission from UNEP-WCMC.

**MPAtlas** (Marine Conservation Institute) offers CSV and geodatabase downloads of
*assessed* MPAs with MPA Guide protection scores — the "is it actually protected"
dimension WDPA can't give. Requires a short request form; non-commercial.

### The finding that justifies the project

**No global registry of locally managed marine areas exists.** Not from the LMMA Network,
not from MIHARI in Madagascar (~150 communities), not from Blue Ventures. The ICCA Registry
is the closest thing at ~310 self-reporting communities, and it is terrestrial-heavy and
consent-based.

This is worth saying plainly to Rare: the community-institution layer cannot be downloaded
from anywhere, by anyone. It has to be assembled. That is simultaneously the hardest part
of the atlas and the entire reason it would be valuable.

---

## 3. Sub-national resolution

The prototype's other real weakness: EEZs are whole countries, and small-scale fishing is
local. Three sources fix this.

**VIIRS Boat Detection — the best find in this survey.**

- `https://eogdata.mines.edu/products/vbd/` — NOAA / Colorado School of Mines
- Detects **individual lit vessels at night** from satellite, as point coordinates with
  radiance — not gridded, actual boats
- Nightly CSV and KMZ; monthly and annual summary rasters at ~500 m
- Global, archive to 2012; CC BY 4.0
- Free account required; **data older than 45 days is open**, near-real-time is gated

Why this matters: AIS vessel tracking cannot see small-scale fleets, and both FAO and
Global Fishing Watch say so — small boats carry no transponders. VIIRS sees them anyway,
because it detects light.

The honest caveat belongs *in the UI*: it only sees **lit** vessels. It captures
light-luring squid and small-pelagic fleets in Indonesia, the Philippines, Peru and
Thailand, and it misses unlit canoes and pirogues entirely. That is a mappable bias, not a
defect — and showing where the method is blind is exactly the honesty this atlas is built on.

**Global Mangrove Watch** — mangroves are core small-scale fishing habitat, and "mangrove
walkers" are one of FAO's canonical small-scale fisher types.

- Zenodo v4.0.19, DOI 10.5281/zenodo.12756047, **CC BY 4.0, no key, direct HTTP**
- **10 m** resolution (Sentinel-2), vector zip 393 MB for a single year
- v4.1 extends to 41 annual epochs, 1985–2025 — so mangrove *loss* becomes a livelihood
  loss signal

**GEBCO bathymetry** — `https://www.gebco.net`, 15 arc-second, public domain, no
registration. Deriving 0–50 m shelf area per stretch of coast gives a strong proxy for
where small boats can physically work. Cheap, and it is a real analytical layer rather than
a downloaded one.

Also available: **Global Fishing Watch API** (free non-commercial token, instant) for
industrial fishing effort and Sentinel-1 SAR "dark vessel" detections — useful as the
*contrast* layer showing industrial pressure against small-scale grounds, not as SSF data
itself. Allen Coral Atlas and UNEP-WCMC seagrass both require free registration.

---

## 4. Making it live

Caleb asked for news feeds and for the atlas to be constantly updating. All verified:

**GDELT DOC 2.0** — `https://api.gdeltproject.org/api/v2/doc/doc`, **truly keyless**.
A live test query for Philippines fisheries news returned same-day articles including
*"US funds Palawan center for fishers to report illegal fishing."* Each record carries URL,
title, date, domain, language and source country — enough to render a news card without
scraping. 65 languages, rolling 3-month window.

Limits that matter: 250 records maximum per call, and the rate limit is **sticky** — rapid
calls got the researcher's IP blocked for several minutes. Sleep 6 seconds between calls,
cache aggressively, and never call it from the browser.

**Climate signals, all keyless, all verified today:**

| Layer | Endpoint | Cadence |
|---|---|---|
| Coral heat stress (DHW, bleaching alert 0–4) | PacIOOS ERDDAP `dhw_5km` | daily, 5 km |
| Marine heatwave category (0–5) | PacIOOS ERDDAP `mhw_5km` | daily, 5 km |
| ENSO / El Niño (ONI, weekly Niño regions) | NOAA CPC flat text | monthly / weekly |
| Chlorophyll-a | NOAA CoastWatch ERDDAP | daily–monthly, 4 km |
| Cyclone tracks | IBTrACS CSV + NHC `CurrentStorms.json` | ~2×/week, 6-hourly |
| Sea level trends, 510 stations | NOAA Tides & Currents API | annual |

One reusable ERDDAP function (dataset, variables, bounding box, dates → CSV) unlocks four
of those six.

**A timely note:** the ENSO index is not neutral right now. Verified from NOAA's live file,
the Oceanic Niño Index has climbed −0.39 → −0.21 → +0.11 → +0.46 → +0.95 → **+1.39** across
the last six overlapping seasons, and the Niño 1+2 region off Peru and Ecuador is running
**+4.1°C above normal**. A real El Niño is building, in the exact waters where the El Niño
/ small-scale fishery story is best documented. If the atlas shipped with an ENSO layer
this month, it would open on a live event.

**Also live:** GDACS disaster alerts (keyless RSS and GeoJSON, 386 active events, with
coordinates — so a point-in-polygon test gives "a cyclone alert is inside this fishing
zone"). RSS feeds work for Rare (`rare.org/feed/`), Blue Ventures (`/rss`), WorldFish, and
the SSF Hub. FAO has no usable feed — their fishery site is client-rendered.

**Email alerting from a static site**, which is Global Forest Watch's retention mechanism:
GitHub Actions on a cron → Python script → GDELT and GDACS per zone → diff against a state
file → batch send through a free email tier. Roughly 150 lines. Ship **one public weekly
digest** before per-zone subscriptions — it proves the "living atlas" claim at a tenth of
the complexity.

---

## 5. Credibility layers

- **FAO FishStat bulk** — `https://www.fao.org/fishery/static/Data/`, release 2026.1.0,
  1,159,616 rows, 1950–**2024**. Official catch to cross-check the Sea Around Us
  reconstructions, and it extends five years past where SAU stops. No sector split, so it
  complements rather than replaces. Annual.
- **Fisheries subsidies** (Sumaila et al. 2019) — open supplement CSV, 152 countries × 13
  subsidy types. Pairs into a strong narrative: subsidies flowing to industrial fleets
  versus the small-scale share of catch.
- **FishBase** — the old REST API is dead; the live route is parquet on Source Cooperative,
  plain HTTPS, no key. Trophic level, habitat, max length.
- **RAM Legacy stock assessments** — 112 MB, CC BY, but ~1,000 mostly industrial temperate
  stocks whose boundaries don't align to EEZs. High join cost, low small-scale relevance.
  Defer.

---

## Recommended build order

Ordered by value ÷ effort, not by interest.

1. **IHH Livelihoods** → the dependence index. Fixes the metric flaw, adds gender, 187
   countries, one 322 KB file. Highest value, lowest effort in the entire survey.
2. **GDELT news panel** → one keyless call per country makes the atlas visibly living.
3. **ENSO + coral heat stress** → two endpoints, and El Niño is active right now.
4. **IATI organization layer** → claims the unoccupied ground. Medium effort, highest
   strategic value.
5. **SDG 14.b.1 and 14.4.1** → two API calls, adds policy and sustainability context.
6. **IHH Nutrition and Governance** → depth on food security and tenure.
7. **VIIRS Boat Detection** → sub-national resolution, genuinely novel. Needs a free
   account and real raster/point work.
8. **Global Mangrove Watch and GEBCO shelf** → habitat and fishing-ground proxies.
9. **FishStat cross-check** → credibility, and extends the record to 2024.
10. **Weekly email digest** → the retention loop, once there is something worth sending.

Items 1–3 are a weekend. Items 1–5 would make this a genuinely different product from
anything currently published.

---

## Questions this raises for Rare

- The community-institution layer cannot be downloaded from anywhere. Would Rare share
  Fish Forever site locations, and would peer organizations (Blue Ventures, WCS, EDF)
  share theirs? Without that, this layer can only ever be partial.
- `portal.rare.org` is offline pending a rebuild. Does this atlas complement it, feed it,
  or duplicate it?
- Is a dependence index (people and nutrition) more useful to Rare's audience than catch
  tonnage — or is the honest answer to show both and let the disagreement be the point?
- WDPA's redistribution terms constrain the protected-areas layer. Does Rare have an
  existing UNEP-WCMC relationship that would allow more than display-only use?
