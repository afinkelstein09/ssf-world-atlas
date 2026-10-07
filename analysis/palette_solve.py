"""Search for overlay colours that clear every ramp, then verify."""
import math, sys
sys.path.insert(0, '.')
from palette_audit import to_lab, de, hue

VIEW_RAMPS = {
    "Share of catch":        ['#e3eef1','#accfd8','#6aa9b8','#2f7d91','#0d4d5c'],
    "People":                ['#f6ebf3','#e0bcd9','#c286bd','#98479a','#63196b'],
    "Whose fleets fish here":['#f4efe9','#e3c6ac','#c9906a','#a55c33','#75300f'],
    "Marine heatwave":       ['#9dc3d4','#f2d474','#e89a43','#d44b36','#9e1f28','#5c0c2b'],
    "Data confidence":       ['#e8e8e6','#c2c4c2','#8d918f','#4a504e'],
}
ALL_RAMP = [c for cols in VIEW_RAMPS.values() for c in cols]

def chroma(h):
    _, a, b = to_lab(h)
    return math.sqrt(a*a + b*b)

def separable(x, y):
    """Distinguishable if far in Lab, OR if one is neutral and the other is not."""
    if de(x, y) >= 25:
        return True
    cx, cy = chroma(x), chroma(y)
    return (cx < 8 and cy > 18) or (cy < 8 and cx > 18)

def min_gap(col, others):
    return min(de(col, o) for o in others)

# candidate overlay colours, kept vivid enough to read as points and thin lines
CANDS = ['#009d64','#00b377','#12b886','#e8368f','#d61f69','#f0522a','#e8590c',
         '#5b46e0','#7048e8','#4263eb','#00b6c9','#0ca678','#ae3ec9','#f59f00',
         '#c2255c','#1098ad','#5f3dc4','#e03131','#0b7285','#862e9c']

fixed = {"Preferential access areas": '#009d64', "Project & community sites": '#5b46e0'}
print("locked:", fixed)

def score(col, taken):
    return min(min_gap(col, ALL_RAMP), min((de(col, t) for t in taken), default=99))

# Fish Forever must stay warm - it is Rare's identity colour.
warm = [c for c in CANDS if 20 <= hue(c) <= 70 or hue(c) >= 350]
best_ff = max(warm, key=lambda c: score(c, list(fixed.values())))
print(f"\nFish Forever best warm candidate: {best_ff}  gap-to-ramps {min_gap(best_ff, ALL_RAMP):.1f}")

taken = list(fixed.values()) + [best_ff]
best_issf = max([c for c in CANDS if c not in taken], key=lambda c: score(c, taken))
print(f"ISSF best candidate:              {best_issf}  gap-to-ramps {min_gap(best_issf, ALL_RAMP):.1f}")

final = dict(fixed)
final["Rare Fish Forever"] = best_ff
final["ISSF records"] = best_issf

print("\n--- verification ---")
names = list(final)
print("overlay vs overlay:")
for i in range(len(names)):
    for j in range(i+1, len(names)):
        d = de(final[names[i]], final[names[j]])
        print(f"   {names[i][:24]:<25} vs {names[j][:24]:<25} dE {d:5.1f}{'  FAIL' if d < 25 else ''}")
print("overlay vs ramps:")
for n, c in final.items():
    g = min_gap(c, ALL_RAMP)
    print(f"   {n:<26} min dE to any ramp colour {g:5.1f}{'  FAIL' if g < 25 else ''}")

print("\nview vs view, chroma-aware:")
vn = list(VIEW_RAMPS)
for i in range(len(vn)):
    for j in range(i+1, len(vn)):
        a, b = VIEW_RAMPS[vn[i]][-1], VIEW_RAMPS[vn[j]][-1]
        ok = separable(a, b)
        dh = min(abs(hue(a)-hue(b)), 360-abs(hue(a)-hue(b)))
        if not ok or dh < 40:
            print(f"   {vn[i][:22]:<23} vs {vn[j][:22]:<23} dE {de(a,b):5.1f} dHue {dh:4.0f}  {'OK(neutral)' if ok else 'FAIL'}")
print("\nfinal:", final)
