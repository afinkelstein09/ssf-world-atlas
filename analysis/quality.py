"""Where is the data best and worst, by name; and how recent is each source."""
import json, os
from collections import defaultdict

HERE=os.path.dirname(os.path.abspath(__file__))
D=os.path.join(os.path.dirname(HERE),'site','data')
eez=json.load(open(f'{D}/countries.json'))['countries']
people=json.load(open(f'{D}/people.json'))['countries']
climate=json.load(open(f'{D}/climate.json'))
paa=json.load(open(f'{D}/paa.json'))['countries']
meta=json.load(open(f'{HERE}/wb_meta.json'))
FF={'PHL','IDN','MOZ','BRA','HND','GTM','PLW','FSM'}

# a simple completeness score per zone: how many of 5 variables are present
score={}
for z in eez:
    iso=z.get('iso3')
    s=0
    s+= 1 if z.get('ssf_share') is not None else 0
    s+= 1 if z.get('confidence',0)>=3 else 0
    s+= 1 if people.get(iso,{}).get('employed_per_1k') is not None else 0
    s+= 1 if z['name'] in climate['zones'] else 0
    s+= 1 if iso in paa else 0
    score[z['name']]=(s,iso,z.get('total_t') or 0)

print("=== COMPLETENESS (0-5 variables present per zone) ===")
from collections import Counter
for k,v in sorted(Counter(s for s,_,_ in score.values()).items(), reverse=True):
    print(f"  {k}/5 variables: {v} zones")

big=[(n,s,i,t) for n,(s,i,t) in score.items() if t>100000]
big.sort(key=lambda x:(-x[1],-x[3]))
print(f"\n=== BEST-COVERED major fishing zones (>100k t) ===")
for n,s,i,t in big[:10]: print(f"  {s}/5  {n[:32]:<33} {t:>10,}t")
print(f"\n=== WORST-COVERED major fishing zones (>100k t) ===")
for n,s,i,t in big[-10:]: print(f"  {s}/5  {n[:32]:<33} {t:>10,}t")

print(f"\n=== RECENCY BY SOURCE ===")
yrs=[z['years'][1] for z in eez if z.get('years')]
print(f"  Sea Around Us catch      last year of record: {min(yrs)}-{max(yrs)} (all zones end {max(set(yrs), key=yrs.count)})")
print(f"  Illuminating Hidden H.   2013-2017 baseline, published 2023, static")
print(f"  World Bank population    2015-2025 window, latest non-null used")
print(f"  Duke access areas        v1 2025; laws enacted {min(p['year'] for p in paa.values() if p['year'])}-{max(p['year'] for p in paa.values() if p['year'])}")
print(f"  NOAA heat stress         {climate['zones'][list(climate['zones'])[0]]['date']} (daily)")
print(f"  NOAA ENSO                {climate['enso'].get('oni_season')} monthly / week of {climate['enso'].get('week')}")

print(f"\n=== FISH FOREVER COUNTRIES: completeness ===")
for z in eez:
    if z.get('iso3') in FF and z.get('iso_kind')!='territory':
        s,i,t=score[z['name']]
        print(f"  {s}/5  {z['name'][:32]:<33} {t:>10,}t")

print(f"\n=== PAA ENACTMENT ERA ===")
years=[p['year'] for p in paa.values() if p['year']]
years.sort()
for lo,hi in [(1900,1990),(1990,2000),(2000,2010),(2010,2026)]:
    c=sum(1 for y in years if lo<=y<hi)
    print(f"  {lo}-{hi}: {c} countries")
