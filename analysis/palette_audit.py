"""
Audit the atlas palette for perceptual collisions.

Two different constraints apply, and conflating them is what produced the current
clash:

  Views are exclusive - only one colours the map at a time - so they only need to
  be told apart in the picker.
  Overlays draw ON TOP of whichever view is active, so every overlay colour must
  stay legible against every view ramp, and against the other overlays.

Distances are CIE76 dE in Lab. Below ~25 two colours read as the same family at a
glance; below ~15 they are hard to separate at all.
"""

import math

VIEW_RAMPS = {
    "Share of catch":       ['#e3eef1','#accfd8','#6aa9b8','#2f7d91','#0d4d5c'],
    "People":               ['#f6ebf3','#e0bcd9','#c286bd','#98479a','#63196b'],
    "Whose fleets fish here":['#f4efe9','#e3c6ac','#c9906a','#a55c33','#75300f'],
    "Marine heatwave":      ['#9dc3d4','#f2d474','#e89a43','#d44b36','#9e1f28','#5c0c2b'],
    "Data confidence":      ['#ded9f3','#b5a9e2','#8272c6','#54429e'],
}
OVERLAYS = {
    "Preferential access areas": '#00b3a0',
    "Project & community sites": '#b0552f',
    "Rare Fish Forever":         '#d8541b',
    "ISSF records":              '#6b4fa8',
}


def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def to_lab(hexcode):
    r, g, b = hex_to_rgb(hexcode)
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    x = r*0.4124 + g*0.3576 + b*0.1805
    y = r*0.2126 + g*0.7152 + b*0.0722
    z = r*0.0193 + g*0.1192 + b*0.9505
    xn, yn, zn = 0.95047, 1.0, 1.08883
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787*t + 16/116
    fx, fy, fz = f(x/xn), f(y/yn), f(z/zn)
    return (116*fy - 16, 500*(fx - fy), 200*(fy - fz))


def de(a, b):
    la, lb = to_lab(a), to_lab(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def hue(hexcode):
    _, a, b = to_lab(hexcode)
    return (math.degrees(math.atan2(b, a)) + 360) % 360


def ramp_hue(colors):
    """Hue of the saturated end - what the ramp 'is' visually."""
    return hue(colors[-1])


print("=" * 72)
print("VIEW RAMPS — identity hue of the saturated end")
print("=" * 72)
for name, cols in VIEW_RAMPS.items():
    print(f"  {name:<24}{ramp_hue(cols):6.0f}°   {cols[-1]}")

print()
print("=" * 72)
print("VIEW vs VIEW — do the pickers read as different families?")
print("=" * 72)
names = list(VIEW_RAMPS)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = names[i], names[j]
        d = de(VIEW_RAMPS[a][-1], VIEW_RAMPS[b][-1])
        dh = abs(ramp_hue(VIEW_RAMPS[a]) - ramp_hue(VIEW_RAMPS[b]))
        dh = min(dh, 360 - dh)
        flag = "  <-- COLLISION" if dh < 45 else ""
        print(f"  {a[:22]:<23} vs {b[:22]:<23} dE {d:5.1f}  dHue {dh:5.0f}°{flag}")

print()
print("=" * 72)
print("OVERLAY vs OVERLAY — these draw at the same time")
print("=" * 72)
onames = list(OVERLAYS)
for i in range(len(onames)):
    for j in range(i + 1, len(onames)):
        a, b = onames[i], onames[j]
        d = de(OVERLAYS[a], OVERLAYS[b])
        dh = abs(hue(OVERLAYS[a]) - hue(OVERLAYS[b]))
        dh = min(dh, 360 - dh)
        flag = "  <-- COLLISION" if d < 25 or dh < 30 else ""
        print(f"  {a[:24]:<25} vs {b[:24]:<25} dE {d:5.1f}  dHue {dh:5.0f}°{flag}")

print()
print("=" * 72)
print("OVERLAY vs VIEW RAMP — worst case against each ramp's saturated end")
print("=" * 72)
for oname, ocol in OVERLAYS.items():
    worst = min(((de(ocol, c), vname, c) for vname, cols in VIEW_RAMPS.items() for c in cols),
                key=lambda t: t[0])
    flag = "  <-- hides against this ramp" if worst[0] < 25 else ""
    print(f"  {oname:<25} closest to {worst[1][:22]:<23} dE {worst[0]:5.1f}{flag}")
