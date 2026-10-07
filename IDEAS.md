# Parked ideas

Things considered and deliberately deferred. Not a backlog — a record of decisions,
so nothing has to be rediscovered.

## Panel

- **Remember which sections a reader left open** as they click between zones. Right now
  every zone opens fresh with only "Catch by sector" expanded. Someone comparing
  livelihoods across five countries has to open that section five times.
- **Let the panel widen on large screens.** Fixed at 348px, which is right on a laptop and
  narrow on a desktop once several sections are expanded.

Both deferred 2026-08-21 — the collapsible layout wanted testing on its own first.

## Data

- **Fix the FAOSTAT protein join.** 52 MB downloads and produces nothing: FAOSTAT keys on
  UN M49, everything else on ISO3, and the crosswalk fails silently. Fish as a share of
  animal protein is the third leg of the dependence index.
- **Fix or drop the GDELT news layer.** Currently switched off. The `sourcecountry` filter
  returned a Belize restaurant guide and Tanzanian articles under Brazil.
- **Global Fishing Watch** as an industrial-pressure contrast layer — where the big fleets
  are, against where small-scale grounds are. Free non-commercial token. Assessed
  2026-08-21: worth doing, but it is not small-scale coverage and shouldn't be sold as it.
- **VIIRS Boat Detection** — nightly satellite detection of lit vessels, the one source
  that sees boats without transponders. Free account, 45-day lag on the open tier.
- **Global Mangrove Watch** at 10 m — mangrove walkers are a canonical small-scale fisher
  type, and mangrove loss is a livelihood-loss signal.
- **IHH nutrition and governance workbooks** — micronutrient contribution and tenure
  rights, both downloaded and neither wired in.

## Assessed and rejected

- **SSF Explorers Hub** — an ArcGIS StoryMap profiling National Geographic Explorers.
  Editorial narrative, no queryable dataset. Link out at most.
- **FishWise Seascape Map** — a curated directory of traceability and counter-IUU
  initiatives. Closed visualisation, no API, no download, no licence statement.
  It does point at **ABALOBI**, a South African electronic-logbook platform built with
  small-scale fishers, which is worth investigating on its own terms — data co-produced
  by fishers is a different category from anything else in this atlas.

## Palette

Audited 2026-08-21 with CIE Lab distance (`analysis/palette_audit.py`). Two different
constraints apply and conflating them caused the original clash: **views are exclusive**,
so they only need to be told apart in the picker, while **overlays draw on top of whichever
view is active**, so every overlay must clear every ramp colour.

Resolved:
- Data confidence moved from purple to **neutral grey** — it describes the data, not the
  ocean, and its purple was 21° of hue from the People ramp.
- Project sites moved from brown to **violet**; it was ΔE 8.5 from the fleets ramp, i.e.
  invisible on the exact layer someone would cross-reference it against.
- ISSF moved from purple to **pink**; it was ΔE 7.1 from the old confidence ramp.
- Fish Forever keeps Rare's **orange** and gained a white casing line. Its ΔE to the
  heatwave ramp is 23.3 and cannot be fixed by hue — both must be warm — so the fix is
  cartographic rather than chromatic.

Left alone deliberately: People vs Marine heatwave sit 40° apart in hue. They are never
drawn together, and the picker swatches are unambiguous.
