> **Superseded.** This inventory describes the prototype as of 2026-08-14 (four layers, degree heating weeks, no organisation directory). The current state is in `README.md`; every number was verified in `TRUTH-2026-09-08.md`.

# What the atlas currently does

A feature-by-feature inventory of the prototype as of 2026-08-14 — what each thing
shows, where the data comes from, and what it can't tell you.

---

## The map itself

**MapLibre GL** rendering **CARTO's dark basemap** (free, no API key, © OpenStreetMap
contributors). Static site — HTML, JavaScript and JSON files. No server, no database,
no accounts.

The unit of the map is the **exclusive economic zone**: the waters a country controls,
out to 200 nautical miles. There are **282** of them, and every one is drawn from real
polygon geometry supplied by Sea Around Us.

---

## Four base layers

Only one shows at a time. Each recolours the same 282 zones to answer a different question.

### 1. Share of catch — *how much of the fishing here is small-scale?*

Colours each EEZ by the percentage of its landings that come from artisanal and
subsistence fishing, averaged over the last five years of record.

- **Source:** Sea Around Us (University of British Columbia), reconstructed catch by
  sector, via `api.seaaroundus.org`. This is the only global dataset that splits catch
  into artisanal, subsistence, industrial and recreational — which is the single fact
  that makes the whole atlas possible.
- **Coverage:** all 282 EEZs, 1950–2019.
- **Worldwide mean:** 37.8% small-scale.
- **What it can't tell you:** these are *reconstructions*, not official landings. They
  combine reported catch with estimates of unreported catch using interpolation and
  expert judgement, and Sea Around Us scores its own uncertainty from ±10% to ±50%.
  The record also stops in 2019.

### 2. People — *how many humans actually fish here?*

Colours each EEZ by how many people are employed in small-scale fisheries per 1,000
population.

- **Source:** Illuminating Hidden Harvests (FAO / Duke / WorldFish, 2023) for employment;
  World Bank `SP.POP.TOTL` for population.
- **Coverage:** 187 countries, joining to 232 of the 282 EEZs.
- **Why it exists:** the catch layer has a real flaw. Palau reads as 22% small-scale and
  Micronesia as 1.4%, which makes them look like Rare's *least* small-scale countries.
  That's an artifact of industrial tuna fleets dominating tonnage in those waters — it
  says nothing about how many people fish. Indonesia is only 33% small-scale by tonnage
  but has 11.6 fishers per 1,000 people; Guatemala is 87% by tonnage with 1.8. Same
  countries, opposite rankings.
- **What it can't tell you:** figures are national, so a country's several EEZs all show
  the same number. IHH is a one-off 2023 baseline, explicitly not official statistics.
  And **Palau and Micronesia aren't in IHH at all** — the layer fixes the problem in
  general and misses the two cases that motivated it.

### 3. Ocean heat stress — *is the water dangerously warm right now?*

Colours each EEZ by accumulated heat stress, on a five-step scale from "no heat stress"
to "extreme — coral mortality likely."

- **Source:** NOAA Coral Reef Watch 5 km degree heating weeks, pulled daily through the
  PacIOOS ERDDAP server.
- **Coverage:** 208 EEZs. Zones beyond 40° latitude are skipped — there's no reef signal
  there and querying them is wasted time.
- **Currently showing:** a severe Mediterranean marine heatwave (Balearics, Algeria,
  Sicily, Tunisia) and equatorial Pacific hotspots consistent with the active El Niño.
- **What it can't tell you:** degree heating weeks is calibrated to *coral*, not fish —
  the 4 and 8 thresholds come from coral bleaching studies. It's a good proxy for reef
  fisheries and a poor one for upwelling or temperate fisheries. It's also sampled from
  one box near each zone's centroid, not averaged across the whole polygon.
- **Note:** severity here is derived from mean degree heating weeks using NOAA's
  thresholds, not NOAA's own bleaching alert product. Taking NOAA's maximum alert across
  a box let a single hot coastal pixel speak for an entire EEZ — Portugal briefly read 47
  degree heating weeks against a real value near 9. Hence mean plus a 90th percentile,
  and hence "heat stress" rather than "bleaching alert" in the interface.

### 4. Data confidence — *how much should you trust the catch number?*

Colours each EEZ on a 1–4 scale for how complete its catch record is.

- **Source:** our own heuristic over the Sea Around Us series — missing values, length of
  record, and total catch volume.
- **Coverage:** all 282 EEZs. Distribution: 115 good, 123 fair, 43 thin, 1 poor.
- **Why it exists:** small-scale fisheries data is famously patchy, and most atlases
  present a single number with no indication of how solid it is. Making uncertainty its
  own visible layer is the honest move, and it's a pattern MPA Atlas uses too.
- **What it can't tell you:** it measures *completeness of the record*, not accuracy. A
  full series can still be a rough reconstruction.

---

## One overlay

### Preferential access areas — *where has the law reserved water for small-scale fishers?*

Drawn in teal on top of whichever base layer is showing, so you can read legal rights
against catch, people, or heat.

- **Source:** DeLand, Vegh, Cleary, Basurto, Virdin & Halpin (2025), *A global dataset of
  preferential access areas for small-scale fishing*, Duke Research Data Repository,
  doi:10.7924/r40s01h5j, **CC0**. Accompanies Basurto et al. (2024) in *npj Ocean
  Sustainability*.
- **Coverage:** 44 countries, 63 areas, about 3% of the world's continental shelf.
- **Why it's different from everything else:** every other layer is descriptive — what is
  happening. This one is normative — what a government decided. It's the only layer that
  names a lever someone could actually pull.
- **What it can't tell you:** the authors describe their count as a **lower bound** — a
  country can create such an area through law outside the fisheries code and it wouldn't
  appear. Only **12 of the 44 boundaries have been confirmed by a local expert**; the rest
  were reconstructed from the text of the law using distance from shore, depth, or listed
  coordinates.

**The finding worth raising with Rare:** the database records **five of the eight Fish
Forever countries as having no preferential access area** — Brazil, Guatemala, Honduras,
Indonesia, Micronesia. Only Philippines (15.75% of its EEZ), Mozambique (3.74%) and Palau
(1.95%) appear. Since Rare's entire model is managed access with reserves, this is far
more likely a gap in the database than a gap on the ground, which makes it something Rare
could contribute back.

Read against the people layer, the same data becomes a gap-finder. Of 142 marine countries
in the atlas, only 40 have a recorded access area. The largest gaps by marine small-scale
workforce: Indonesia (1.9M), Vietnam (460k), Brazil (385k), Sri Lanka (272k), Madagascar
(153k). Sri Lanka and Madagascar stand out — both around 75% of catch small-scale, neither
with a recorded legal reservation.

---

## The El Niño banner

A live reading of the El Niño / La Niña state, sitting in the header.

- **Source:** NOAA Climate Prediction Center — the Oceanic Niño Index (monthly) and weekly
  Niño region anomalies, both plain text files, public domain.
- **Currently showing:** **El Niño, ONI +1.39**. The index has climbed −0.39 → −0.21 →
  +0.11 → +0.46 → +0.95 → +1.39 across the last six overlapping seasons, and the Niño 1+2
  region off Peru and Ecuador is running **+4.1 °C above normal**.
- **Why it's there:** El Niño is the single most consequential recurring climate signal
  for small-scale fisheries — the Peruvian anchoveta collapse is the textbook case — and
  Caleb asked for it specifically. It happens to be live right now.

---

## Rare Fish Forever countries

Outlined in orange across every layer: Philippines, Indonesia, Mozambique, Brazil,
Honduras, Guatemala, Palau, Micronesia — 12 EEZs in total, since several countries have
more than one.

- **Source:** Rare's published country list, hand-entered.
- **Note:** matching by country name initially flagged uninhabited French islands in the
  Mozambique Channel and Brazil's offshore rocks as Rare sites, so this is now an explicit
  list of exact zone names rather than a pattern match.

---

## Clicking a zone

Opens a panel with, in order:

1. **Zone name, record span, and Fish Forever badge** where it applies.
2. **Headline figure** — the small-scale share of catch, and the tonnage it's drawn from.
3. **Catch by sector** — artisanal, subsistence, industrial, recreational, as bars with
   percentages and tonnes.
4. **Small-scale share over time** — a sparkline of the full record, usually 1950 to 2019.
5. **Preferential access** — share of EEZ reserved, year enacted, area, what the law
   excludes, and whether a local expert confirmed the boundary. Or an explicit note that
   no area is recorded, with the lower-bound caveat.
6. **People** — workers employed, per 1,000 population, women's share of that workforce,
   subsistence fishers counted separately, and the small-scale share of all fishing jobs.
7. **Ocean heat** — today's severity, mean and 90th-percentile degree heating weeks.
8. **News** — recent fisheries coverage. *Not yet populated; see below.*
9. **Data confidence** — the 1–4 score with a plain-language explanation.
10. **Sources** — named on every panel, with their limitations stated.

Hovering any zone shows its name and the current layer's value without opening the panel.

---

## Honesty features

These are deliberate, and they're the thing that separates this from a dashboard.

- **Gaps are drawn, not hidden.** Zones without data render in flat grey rather than being
  omitted or interpolated.
- **Missing data says why.** Palau's panel explains that IHH covers 187 countries but not
  this one — a real gap, not a rendering failure.
- **Territories are flagged.** The Azores inherit Portugal's national statistics, and the
  panel says so rather than presenting the number as local. 55 of the 282 zones are
  territories inheriting a parent country's figures.
- **Derived numbers are labelled as ours.** The confidence score and the heat-stress
  severity are both our own constructions, and both say so.
- **Every source carries its caveat** in the panel where it's used, not buried in a
  methodology page.
- **A freshness stamp** in the footer reports how many zones carry each kind of data and
  when it was generated.

---

## Not working yet

**The news feed.** The pipeline is written and running, but GDELT has our IP rate-limited
from testing — their limit is strict and sticky, and it blocks for minutes after each
refusal. Three of 60 countries have fetched so far, and `news.json` isn't written until
the run completes, so no news appears in the site yet. The panel degrades gracefully:
the section simply doesn't render. Left running, it will fill in.

---

## Data sources, at a glance

| Layer | Source | Licence | Updates |
|---|---|---|---|
| Catch by sector | Sea Around Us (UBC) | cite per their policy | static to 2019 |
| EEZ geometry | Sea Around Us | as above | static |
| Employment, gender | Illuminating Hidden Harvests (FAO/Duke/WorldFish) | CC BY 4.0 | one-off, 2023 |
| Population, food insecurity | World Bank | CC BY 4.0 | annual |
| Fish protein share | FAOSTAT Food Balance Sheets | CC BY 4.0 | annual |
| Preferential access areas | Duke Research Data Repository | **CC0** | v1, 2025 |
| Heat stress | NOAA Coral Reef Watch via PacIOOS | public domain | daily |
| El Niño indices | NOAA Climate Prediction Center | public domain | weekly / monthly |
| News | GDELT | free with attribution | rolling 3 months |
| Basemap | CARTO / OpenStreetMap | ODbL | — |

Everything above is free and keyless. Nothing in this project requires a paid tier, an API
key, or an account.
