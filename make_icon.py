"""Builds icon.ico (shortcut) and icon.svg (window) from one set of shapes. Run once after editing."""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BG, AMBER, CREAM = "#1b1a18", "#f5a524", "#efe9df"
S = 1024

# (kind, args) in a 1024 box, shared by PNG and SVG output
CAP = (300, 180, 540, 560, 120)          # mic capsule x0,y0,x1,y1,r
GRILLE = [(340, 500, 300), (340, 500, 370), (340, 500, 440)]
YOKE = (240, 330, 600, 690)              # arc box, bottom half
STEM = (420, 690, 420, 800)
BASE = (320, 812, 520, 812)
NOTE_HEAD = (628, 560, 748, 650)
NOTE_STEM = (722, 250, 752, 610)
NOTE_FLAG = [(752, 250), (860, 320), (860, 390), (752, 330)]


def png():
    k = 4  # supersample for smooth edges
    im = Image.new("RGBA", (S * k, S * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    z = lambda *v: [c * k for c in v]
    d.rounded_rectangle(z(0, 0, S, S), radius=230 * k, fill=BG)
    d.rounded_rectangle(z(*CAP[:4]), radius=CAP[4] * k, fill=AMBER)
    for x0, x1, y in GRILLE:
        d.line(z(x0, y, x1, y), fill=BG, width=22 * k)
    d.arc(z(*YOKE), 0, 180, fill=CREAM, width=40 * k)
    d.line(z(*STEM), fill=CREAM, width=40 * k)
    d.line(z(*BASE), fill=CREAM, width=40 * k)
    for x, y in ((BASE[0], BASE[1]), (BASE[2], BASE[3])):
        d.ellipse(z(x - 20, y - 20, x + 20, y + 20), fill=CREAM)
    d.ellipse(z(*NOTE_HEAD), fill=CREAM)
    d.rectangle(z(*NOTE_STEM), fill=CREAM)
    d.polygon([tuple(c * k for c in p) for p in NOTE_FLAG], fill=CREAM)
    return im.resize((256, 256), Image.LANCZOS)


def svg():
    cx0, cy0, cx1, cy1, r = CAP
    yx0, yy0, yx1, yy1 = YOKE
    grille = "".join(f'<line x1="{a}" y1="{y}" x2="{b}" y2="{y}" stroke="{BG}" stroke-width="22"/>' for a, b, y in GRILLE)
    hx0, hy0, hx1, hy1 = NOTE_HEAD
    flag = " ".join(f"{x},{y}" for x, y in NOTE_FLAG)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">
<rect width="{S}" height="{S}" rx="230" fill="{BG}"/>
<rect x="{cx0}" y="{cy0}" width="{cx1 - cx0}" height="{cy1 - cy0}" rx="{r}" fill="{AMBER}"/>{grille}
<path d="M{yx0} {(yy0 + yy1) / 2} A{(yx1 - yx0) / 2} {(yy1 - yy0) / 2} 0 0 0 {yx1} {(yy0 + yy1) / 2}" fill="none" stroke="{CREAM}" stroke-width="40"/>
<line x1="{STEM[0]}" y1="{STEM[1]}" x2="{STEM[2]}" y2="{STEM[3]}" stroke="{CREAM}" stroke-width="40"/>
<line x1="{BASE[0]}" y1="{BASE[1]}" x2="{BASE[2]}" y2="{BASE[3]}" stroke="{CREAM}" stroke-width="40" stroke-linecap="round"/>
<ellipse cx="{(hx0 + hx1) / 2}" cy="{(hy0 + hy1) / 2}" rx="{(hx1 - hx0) / 2}" ry="{(hy1 - hy0) / 2}" fill="{CREAM}"/>
<rect x="{NOTE_STEM[0]}" y="{NOTE_STEM[1]}" width="{NOTE_STEM[2] - NOTE_STEM[0]}" height="{NOTE_STEM[3] - NOTE_STEM[1]}" fill="{CREAM}"/>
<polygon points="{flag}" fill="{CREAM}"/>
</svg>'''


if __name__ == "__main__":
    im = png()
    im.save(os.path.join(HERE, "icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    im.save(os.path.join(HERE, "icon_preview.png"))
    with open(os.path.join(HERE, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(svg())
    print("ok")
