# Every source, and where it goes in the piece

Seven sources. Full citations first, then a claim-by-claim map of where each one attaches.

---

## The citations

**1. Illuminating Hidden Harvests — the 40% / 90% figures, and the livelihoods vintage**

> FAO, Duke University & WorldFish. 2023. *Illuminating Hidden Harvests: The contributions
> of small-scale fisheries to sustainable development.* Rome, FAO.
> https://doi.org/10.4060/cc4576en

Executive summary, where the 40%/90% sentence appears verbatim: https://doi.org/10.4060/cc6062en
Underlying data workbooks: https://www.fao.org/3/cd3915en/

**2. Basurto et al. — the preferential access areas study**

> Basurto, X., Virdin, J., Franz, N., DeLand, S., Smith, B., Cleary, J., Vegh, T. &
> Halpin, P. 2024. "A global assessment of preferential access areas for small-scale
> fisheries." *npj Ocean Sustainability* 3, 56. https://doi.org/10.1038/s44183-024-00096-0

**3. DeLand et al. — the dataset behind that paper** (cite separately; it is a distinct object)

> DeLand, S., Vegh, T., Cleary, J., Basurto, X., Virdin, J. & Halpin, P.N. 2025. *A global
> dataset of preferential access areas for small-scale fishing.* Duke Research Data
> Repository. https://doi.org/10.7924/r40s01h5j  (CC0)

**4. Pauly & Zeller — the reconstruction-exceeds-reported finding**

> Pauly, D. & Zeller, D. 2016. "Catch reconstructions reveal that global marine fisheries
> catches are higher than reported and declining." *Nature Communications* 7, 10244.
> https://doi.org/10.1038/ncomms10244

**5. Sea Around Us — catch, sector, and fleet nationality**

> Pauly, D., Zeller, D. & Palomares, M.L.D. (eds.) *Sea Around Us Concepts, Design and
> Data.* University of British Columbia. https://www.seaaroundus.org

Their citation policy is mandatory: https://www.seaaroundus.org/citation-policy/
API endpoints used:
- sector split — `/api/v1/eez/tonnage/sector/?region_id={id}`
- fleet nationality — `/api/v1/eez/tonnage/country/?region_id={id}`

**6. FAO reported capture production, via the World Bank**

> World Bank. *World Development Indicators*, indicator `ER.FSH.CAPT.MT` (capture
> fisheries production, metric tons). Source: FAO fishery statistics.
> https://data.worldbank.org

**7. NOAA — thermal stress and ENSO**

> NOAA Coral Reef Watch. Daily Global 5 km Satellite Coral Bleaching Degree Heating Week
> product. https://coralreefwatch.noaa.gov  (accessed via the PacIOOS ERDDAP server)
>
> NOAA Climate Prediction Center. *Oceanic Niño Index.*
> https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

---

## Where each one attaches

### Opening paragraph

> "Small-scale fisheries account for at least 40% of the global capture fisheries catch
> and employ around 60.2 million people, roughly 90% of everyone working in fisheries
> worldwide **(Duke Paper)**."

**Replace `(Duke Paper)` with source 1 (Illuminating Hidden Harvests).** This is the
citation error — those figures are not from the preferential-access paper. If you want the
page-exact version, the sentence appears verbatim in the executive summary.

### "My work" — the sources list

You currently name four. Name five, and note the two Sea Around Us dimensions explicitly,
because the fleet-nationality query is what makes the Guinea-Bissau claim defensible:

- Sea Around Us reconstructed catch, using both its **sector** and **fleet-nationality**
  dimensions → **source 5**
- FAO-reported capture production → **source 6**
- Thermal stress and ENSO → **source 7**
- Statutory nearshore areas → **sources 2 and 3** (paper for the method, dataset for the
  boundaries)
- Livelihoods and employment → **source 1** — currently missing from your list, but you
  rely on it twice

### "The two datasets"

| Claim in your draft | Source |
|---|---|
| 164 countries, 18% agree within 20%, 42% more than half again higher | **Your own computation.** State it as such — see below. |
| "That reconstruction exceeds the reported catch is not new... central finding of the Sea Around Us program" | **Source 4** (Pauly & Zeller) — you already gesture at this; give it the full citation |
| Guinea-Bissau 27-fold gap; 97% foreign; Senegal 25.5%, China 22.1%, Spain 12.8%, Russia 6.4%, domestic 3.0% | **Source 5**, fleet-nationality dimension. Name the dimension in the methodology paragraph. |
| FAO 40,071 t vs 33,337 t domestic, within a factor of 1.2 | **Sources 5 and 6** together — this is the cross-check |
| Belize flag registry | **Currently unsourced.** Either find a source or scope it to what the data shows. |

On the tabulation: it is yours, but the *claim* it illustrates is Pauly and Zeller's.
One sentence handles this — "consistent with Pauly and Zeller's finding rather than a
discovery of it" — which you already have. Keep it. It is the single most defensible
sentence in the draft.

### "When the definition creates the gap"

Everything in this section is **source 2** (the paper), and all of it is verbatim-checkable:

| Claim | Where in the paper |
|---|---|
| Search terms "small-scale," "subsistence," "artisanal," "traditional" | Methods |
| 186 documents, 65% deemed non-relevant | Methods |
| Boundary keywords "mile," "kilometer," "fathom," "meter," "depth," "shore," "baseline" | Methods — your list is a subset; write "keywords including" |
| Ground-truthing across 4 search engines | Methods |
| 44 countries, 63 areas, ~3% of continental shelf | Abstract |
| TURFs distinguished as "small and locally bounded" vs PAAs "designated to the entire coastline" | Introduction — quote this rather than paraphrasing as "omit" |

Cite **source 3** as well when you refer to the map or its boundaries, as opposed to the
study's conclusions. They are separate published objects with separate DOIs.

### "When time creates the gap"

| Claim | Source |
|---|---|
| Thermal stress ~1 day old; ENSO ~1 week | **Source 7** |
| Catch record stops in 2019 | **Source 5** |
| Livelihoods data describes 2013–2017 | **Source 1** |

### The compounding point (if you add it)

> "The PAA global database was built with data for 44 countries identified by the
> Illuminating Hidden Harvests (IHH) initiative..."

**Source 2**, Methods. This is where sources 1 and 2 connect, and it is the evidence for
your claim in paragraph two that these decisions "compound."

---

## The methodology paragraph — what it must now carry

Your editor asked for 150–250 words as prose. Given what has been verified, it needs to do
four things:

1. Name the five sources.
2. State the 20% agreement threshold as **your** choice, and that countries in only one
   dataset were excluded.
3. **Say that fleet nationality is a separate Sea Around Us dimension that you queried
   directly** — this is what converts Guinea-Bissau from inference to evidence, and it is
   the specific answer to the challenge.
4. State the two limits you already name: no uncertainty propagation from the
   reconstruction, and coverage figures describe existence rather than accuracy.

Your existing draft of that paragraph already does all four. It just needs the dimension
named as a dimension, so a reader knows it is published data rather than your inference.
