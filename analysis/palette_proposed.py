"""Test a proposed palette against the same collision checks."""
import math, sys
sys.path.insert(0, '.')
from palette_audit import to_lab, de, hue

# --- proposal -------------------------------------------------------------
# Views keep a semantic hue and stay spread apart in the picker.
#   sea            -> teal          (unchanged; it is right)
#   people         -> magenta/plum  (unchanged, now unambiguous once confidence moves)
#   foreign fleets -> rust/brown    (extraction; no overlay will use brown again)
#   heatwave       -> cool to hot   (universal convention; untouchable)
#   confidence     -> NEUTRAL GREY  (changed: it describes the data, not the ocean,
#                                    so it should not compete as a colour at all)
VIEW_RAMPS = {
    "Share of catch":        ['#e3eef1','#accfd8','#6aa9b8','#2f7d91','#0d4d5c'],
    "People":                ['#f6ebf3','#e0bcd9','#c286bd','#98479a','#63196b'],
    "Whose fleets fish here":['#f4efe9','#e3c6ac','#c9906a','#a55c33','#75300f'],
    "Marine heatwave":       ['#9dc3d4','#f2d474','#e89a43','#d44b36','#9e1f28','#5c0c2b'],
    "Data confidence":       ['#e8e8e6','#c2c4c2','#8d918f','#4a504e'],
}

# Overlays move into the two hue bands no ramp occupies: green ~150 deg and
# blue-violet ~285 deg.
OVERLAYS = {
    "Preferential access areas": '#009d64',   # green = a right, a protection
    "Project & community sites": '#5b46e0',   # blue-violet, far from the rust ramp
    "Rare Fish Forever":         '#f0522a',   # Rare's warm identity, pushed hotter
    "ISSF records":              '#00b6c9',   # cyan, distinct from both the above
}

def report():
    print("VIEW vs VIEW (picker legibility)")
    names = list(VIEW_RAMPS)
    worst = 999
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            a, b = names[i], names[j]
            ca, cb = VIEW_RAMPS[a][-1], VIEW_RAMPS[b][-1]
            d = de(ca, cb)
            # a neutral ramp has no meaningful hue, so compare on distance alone
            neutral = 'confidence' in a.lower() or 'confidence' in b.lower()
            dh = 999 if neutral else min(abs(hue(ca)-hue(cb)), 360-abs(hue(ca)-hue(cb)))
            bad = (dh < 45) or d < 20
            worst = min(worst, d)
            if bad:
                print(f"   COLLISION {a} vs {b}  dE {d:.1f} dHue {dh:.0f}")
    print(f"   min dE across views: {worst:.1f}")

    print("\nOVERLAY vs OVERLAY (drawn together)")
    on = list(OVERLAYS)
    worst = 999
    for i in range(len(on)):
        for j in range(i+1, len(on)):
            a, b = on[i], on[j]
            d = de(OVERLAYS[a], OVERLAYS[b])
            dh = min(abs(hue(OVERLAYS[a])-hue(OVERLAYS[b])), 360-abs(hue(OVERLAYS[a])-hue(OVERLAYS[b])))
            worst = min(worst, d)
            if d < 25 or dh < 30:
                print(f"   COLLISION {a} vs {b}  dE {d:.1f} dHue {dh:.0f}")
    print(f"   min dE across overlays: {worst:.1f}")

    print("\nOVERLAY vs every ramp colour (overlays sit on top)")
    for oname, ocol in OVERLAYS.items():
        w = min(((de(ocol, c), vn) for vn, cols in VIEW_RAMPS.items() for c in cols), key=lambda t: t[0])
        mark = "  <-- too close" if w[0] < 25 else "  ok"
        print(f"   {oname:<26} nearest {w[1][:22]:<23} dE {w[0]:5.1f}{mark}")

report()
