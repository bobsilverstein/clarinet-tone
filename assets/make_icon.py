import sys, math
from PIL import Image, ImageDraw
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([24, 24, S-24, S-24], radius=200, fill=(21, 101, 192, 255))
A = (200, 120); B = (530, 570)                     # mouthpiece tip, start of bell
ux, uy = B[0]-A[0], B[1]-A[1]; L = math.hypot(ux, uy); ux, uy = ux/L, uy/L
px, py = -uy, ux                                   # perpendicular
def P(t, s): return (A[0]+ux*t+px*s, A[1]+uy*t+py*s)
half = 44
body = (25, 25, 25, 255); silver = (215, 220, 228, 255)
d.polygon([P(0, -26), P(0, 26), P(80, half), P(80, -half)], fill=body)          # mouthpiece
d.polygon([P(80, -half), P(80, half), P(L, half), P(L, -half)], fill=body)      # body
d.polygon([P(L, -half), P(L, half), P(L+130, 125), P(L+130, -125)], fill=body)  # bell
for t in (80, 250, L):                                                            # rings
    d.polygon([P(t-10, -half-8), P(t-10, half+8), P(t+10, half+8), P(t+10, -half-8)], fill=silver)
for t in range(320, int(L)-30, 75):                                               # tone holes / keys
    x, y = P(t, 0); d.ellipse([x-17, y-17, x+17, y+17], fill=silver)
# sound waves spreading from the bell mouth
mx, my = P(L+130, 0)
ang = math.degrees(math.atan2(uy, ux))
for i, r in enumerate((95, 165, 235)):
    cx, cy = mx - ux*20, my - uy*20
    d.arc([cx-r, cy-r, cx+r, cy+r], start=ang-42, end=ang+42, fill=(255, 255, 255, 255-i*45), width=40)
out = sys.argv[1]
big = img.resize((256, 256), Image.LANCZOS)
big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
big.save(out.replace(".ico", ".png"))
prev = Image.new("RGBA", (420, 270), (240, 240, 240, 255)); x = 10
for s in (16, 32, 48, 256):
    prev.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 10)); x += s + 20
prev.save("/tmp/icon_preview.png")
