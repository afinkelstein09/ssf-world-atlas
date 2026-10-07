"""Fetch World Bank country metadata: region + income group, keyed by ISO3."""
import json, os, urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wb_meta.json')
url = "https://api.worldbank.org/v2/country?format=json&per_page=400"
req = urllib.request.Request(url, headers={"User-Agent": "ssf-atlas/0.1"})
data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
meta = {}
for c in data[1]:
    iso = c.get("id")
    region = (c.get("region") or {}).get("value")
    income = (c.get("incomeLevel") or {}).get("value")
    if not iso or region in (None, "Aggregates"):
        continue
    meta[iso] = {"name": c.get("name"), "region": region, "income": income}
json.dump(meta, open(OUT, "w"), indent=1)
print(f"{len(meta)} countries with region + income")
from collections import Counter
for k, v in Counter(m["region"] for m in meta.values()).most_common():
    print(f"  {k}: {v}")
