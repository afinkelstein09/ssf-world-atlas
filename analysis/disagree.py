"""
Do independent sources agree about the same place?

Sea Around Us publishes *reconstructed* catch - reported landings plus modelled
estimates of what went unreported. The World Bank republishes FAO's *reported*
capture production. Same countries, same units, different method. The gap between
them is an estimate of how much fishing goes unrecorded, and it is not evenly
distributed.
"""
import json, os, time, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.dirname(HERE), 'site', 'data')
CACHE = f'{HERE}/wb_capture.json'

def get(url, tries=3):
    for a in range(tries):
        try:
            r = urllib.request.Request(url, headers={"User-Agent":"ssf-atlas/0.1"})
            return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
        except Exception:
            if a==tries-1: return None
            time.sleep(2*(a+1))

if os.path.exists(CACHE):
    wb = json.load(open(CACHE))
else:
    d = get("https://api.worldbank.org/v2/country/all/indicator/ER.FSH.CAPT.MT"
            "?format=json&per_page=20000&date=2015:2019")
    wb = {}
    for row in (d[1] if d and len(d)>1 else []):
        iso = (row.get('countryiso3code') or '').strip()
        v, yr = row.get('value'), row.get('date')
        if len(iso)!=3 or v is None: continue
        wb.setdefault(iso, {})[int(yr)] = float(v)
    json.dump(wb, open(CACHE,'w'))

# aggregate Sea Around Us tonnage to country level
eez = json.load(open(f'{D}/countries.json'))['countries']
meta = json.load(open(f'{HERE}/wb_meta.json'))
sau = defaultdict(float)
for z in eez:
    if z.get('iso3') and z.get('total_t'):
        sau[z['iso3']] += z['total_t']

pairs = []
for iso, t in sau.items():
    yrs = wb.get(iso)
    if not yrs: continue
    rep = sum(yrs.values())/len(yrs)          # mean reported 2015-19
    if rep <= 0 or t <= 0: continue
    pairs.append({'iso3': iso, 'name': meta.get(iso,{}).get('name', iso),
                  'region': meta.get(iso,{}).get('region'),
                  'income': meta.get(iso,{}).get('income'),
                  'sau': t, 'reported': rep, 'ratio': t/rep})

pairs.sort(key=lambda p: -p['ratio'])
print(f"=== SEA AROUND US (reconstructed) vs FAO/WORLD BANK (reported) ===")
print(f"    {len(pairs)} countries comparable\n")
within20 = sum(1 for p in pairs if 0.8 <= p['ratio'] <= 1.2)
over50   = sum(1 for p in pairs if p['ratio'] > 1.5)
under50  = sum(1 for p in pairs if p['ratio'] < 0.67)
print(f"  agree within 20%:              {within20:>3} ({100*within20/len(pairs):.0f}%)")
print(f"  reconstruction >50% higher:    {over50:>3} ({100*over50/len(pairs):.0f}%)")
print(f"  reconstruction >33% lower:     {under50:>3} ({100*under50/len(pairs):.0f}%)")

print(f"\n  Largest upward revisions (reconstruction / reported):")
for p in pairs[:10]:
    print(f"    {p['name'][:28]:<28} {p['ratio']:5.2f}x   {p['sau']:>10,.0f} vs {p['reported']:>10,.0f} t")
print(f"\n  Largest downward revisions:")
for p in pairs[-6:]:
    print(f"    {p['name'][:28]:<28} {p['ratio']:5.2f}x   {p['sau']:>10,.0f} vs {p['reported']:>10,.0f} t")

print(f"\n  Median ratio by region:")
byreg = defaultdict(list)
for p in pairs:
    if p['region']: byreg[p['region']].append(p['ratio'])
for reg, rs in sorted(byreg.items(), key=lambda kv: -sorted(kv[1])[len(kv[1])//2]):
    rs.sort()
    print(f"    {reg[:44]:<45} {rs[len(rs)//2]:5.2f}x  (n={len(rs)})")

json.dump(pairs, open(f'{HERE}/disagreement.json','w'), indent=1)
