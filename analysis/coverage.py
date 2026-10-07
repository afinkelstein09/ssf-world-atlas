"""
Measure data coverage across the atlas, by variable and by region.

Answers the empirical questions behind the write-up: which variables exist
everywhere, which only in some places, and whether the gaps track anything.
"""
import json, os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.dirname(HERE), 'site', 'data')

eez     = json.load(open(f'{D}/countries.json'))['countries']
people  = json.load(open(f'{D}/people.json'))['countries']
climate = json.load(open(f'{D}/climate.json'))['zones']
paa     = json.load(open(f'{D}/paa.json'))['countries']
meta    = json.load(open(f'{HERE}/wb_meta.json'))

FF = {'PHL','IDN','MOZ','BRA','HND','GTM','PLW','FSM'}

rows = []
for z in eez:
    iso = z.get('iso3')
    m = meta.get(iso, {})
    rows.append({
        'zone': z['name'], 'iso3': iso, 'kind': z.get('iso_kind'),
        'region': m.get('region'), 'income': m.get('income'),
        'catch':   z.get('ssf_share') is not None,
        'conf':    z.get('confidence', 0),
        'people':  bool(people.get(iso, {}).get('employed_per_1k') is not None),
        'gender':  bool(people.get(iso, {}).get('women_share') is not None),
        'heat':    z['name'] in climate,
        'paa':     iso in paa,
        'ff':      iso in FF,
        'tonnes':  z.get('total_t') or 0,
    })

n = len(rows)
print(f"=== VARIABLE COVERAGE across {n} exclusive economic zones ===")
for var, label in [('catch','Catch by sector (Sea Around Us)'),
                   ('people','Employment (Illuminating Hidden Harvests)'),
                   ('gender','Gender split (IHH)'),
                   ('heat','Ocean heat stress (NOAA)'),
                   ('paa','Preferential access area (Duke)')]:
    have = sum(1 for r in rows if r[var])
    print(f"  {label:<45} {have:>3}/{n}  ({100*have/n:5.1f}%)")

print(f"\n=== CONFIDENCE OF THE CATCH RECORD ===")
for score, lab in [(4,'good — full series'),(3,'fair'),(2,'thin'),(1,'poor')]:
    c = sum(1 for r in rows if r['conf']==score)
    print(f"  {score} {lab:<22} {c:>3} zones ({100*c/n:4.1f}%)")

print(f"\n=== COVERAGE BY REGION (share of zones with each variable) ===")
byreg = defaultdict(list)
for r in rows:
    if r['region']: byreg[r['region']].append(r)
print(f"  {'region':<44}{'zones':>6}{'people':>8}{'heat':>7}{'PAA':>6}{'conf4':>7}")
for reg, rs in sorted(byreg.items(), key=lambda kv: -len(kv[1])):
    k = len(rs)
    print(f"  {reg[:43]:<44}{k:>6}"
          f"{100*sum(r['people'] for r in rs)/k:>7.0f}%"
          f"{100*sum(r['heat'] for r in rs)/k:>6.0f}%"
          f"{100*sum(r['paa'] for r in rs)/k:>5.0f}%"
          f"{100*sum(1 for r in rs if r['conf']==4)/k:>6.0f}%")

print(f"\n=== COVERAGE BY INCOME GROUP ===")
byinc = defaultdict(list)
for r in rows:
    if r['income']: byinc[r['income']].append(r)
order = ['Low income','Lower middle income','Upper middle income','High income']
print(f"  {'income group':<26}{'zones':>6}{'people':>8}{'PAA':>6}{'conf4':>7}")
for inc in order:
    rs = byinc.get(inc, [])
    if not rs: continue
    k = len(rs)
    print(f"  {inc:<26}{k:>6}"
          f"{100*sum(r['people'] for r in rs)/k:>7.0f}%"
          f"{100*sum(r['paa'] for r in rs)/k:>5.0f}%"
          f"{100*sum(1 for r in rs if r['conf']==4)/k:>6.0f}%")

print(f"\n=== TERRITORY vs SOVEREIGN ===")
for kind in ['self','split','territory']:
    rs = [r for r in rows if r['kind']==kind]
    if not rs: continue
    k=len(rs)
    print(f"  {kind:<12}{k:>4} zones   people {100*sum(r['people'] for r in rs)/k:>4.0f}%   PAA {100*sum(r['paa'] for r in rs)/k:>4.0f}%")

json.dump(rows, open(f'{HERE}/rows.json','w'))
