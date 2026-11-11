"""Draw the program icon: a large black clarinet across a warm sunset tile, with
bright sound waves from the bell.  Bold shapes and strong color contrast, so it
still reads at taskbar size.  Usage: python make_icon.py assets/clarinet.ico"""
import sys, math
from PIL import Image, ImageDraw, ImageFilter

S = 1024
# background: diagonal gradient, gold (top left) to magenta to deep purple (bottom right)
stops = [(0.0, (255, 196, 0)), (0.5, (236, 64, 122)), (1.0, (74, 20, 140))]
def grad(t):
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * u) for a, b in zip(c0, c1))
    return stops[-1][1]
bg = Image.new("RGBA", (S, S))
px = bg.load()
for y in range(S):
    for x in range(S):
        px[x, y] = grad((x + y) / (2 * S - 2)) + (255,)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=210, fill=255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(bg, (0, 0), mask)

# clarinet from top left (mouthpiece) to lower right (bell)
A = (110, 100); B = (545, 535)
ux, uy = B[0] - A[0], B[1] - A[1]; L = math.hypot(ux, uy); ux, uy = ux / L, uy / L
pxv, pyv = -uy, ux
def P(t, s): return (A[0] + ux * t + pxv * s, A[1] + uy * t + pyv * s)
half = 76
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
sd = ImageDraw.Draw(shadow)
def clarinet(d, off=(0, 0), col=(18, 18, 22, 255)):
    Q = lambda t, s: (P(t, s)[0] + off[0], P(t, s)[1] + off[1])
    d.polygon([Q(0, -34), Q(0, 34), Q(110, half), Q(110, -half)], fill=col)          # mouthpiece
    d.polygon([Q(110, -half), Q(110, half), Q(L, half), Q(L, -half)], fill=col)      # body
    d.polygon([Q(L, -half), Q(L, half), Q(L + 150, 165), Q(L + 150, -165)], fill=col)  # bell
clarinet(sd, (18, 22), (40, 0, 60, 150))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
d = ImageDraw.Draw(img)
clarinet(d)
silver = (235, 238, 245, 255)
for t in (110, 300, L):                                                              # rings
    d.polygon([P(t - 14, -half - 10), P(t - 14, half + 10), P(t + 14, half + 10), P(t + 14, -half - 10)], fill=silver)
for t in range(380, int(L) - 40, 95):                                                # keys
    x, y = P(t, 0); d.ellipse([x - 24, y - 24, x + 24, y + 24], fill=silver)
# sound waves: thick, bright, three colors
mx, my = P(L + 150, 0)
ang = math.degrees(math.atan2(uy, ux))
for r, col in ((95, (255, 255, 255, 255)), (165, (0, 229, 255, 255)), (235, (255, 235, 59, 255))):
    cx, cy = mx - ux * 50, my - uy * 50
    d.arc([cx - r, cy - r, cx + r, cy + r], start=ang - 40, end=ang + 40, fill=col, width=46)
img = Image.composite(img, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask)

out = sys.argv[1] if len(sys.argv) > 1 else "clarinet.ico"
big = img.resize((256, 256), Image.LANCZOS)
big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.save(out.replace(".ico", ".png"))
prev = Image.new("RGBA", (440, 280), (32, 32, 32, 255)); x = 10
for s in (16, 24, 32, 48, 256):
    prev.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 10)); x += s + 16
prev.save("/tmp/icon_preview.png")
