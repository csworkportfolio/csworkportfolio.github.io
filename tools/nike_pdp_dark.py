"""The dark mode copy of the Nike product page in the AI page's search demo (assets/ai/nike-pdp-dark.jpg).

Build the layers once and make Christian's PhotoCraft file from them, each part its own layer:
    <python> tools/nike_pdp_dark.py layers <work folder with in/ and mask/ from tools/person_mask>
Export his edited file to the site (run after he saves it):
    <python> tools/nike_pdp_dark.py export

The page is his screenshot (assets/ai/nike-pdp.jpg) with its white and black swapped to dark; the main photo has him
cut out (Apple Vision, tools/person_mask.swift) and relit for a dark room on the demo box's gray; the thumbnails
stay light; the photo's arrow buttons are dark glass.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT.parent / "storyboards/nike-pdp-dark.pcraft"
PARTS = ROOT.parent / "storyboards/nike-pdp-dark"
LIGHT = ROOT / "assets/ai/nike-pdp.jpg"
OUT = ROOT / "assets/ai/nike-pdp-dark.jpg"
K = 2   # the board is twice the site image's size, so there is detail to edit
GRAY = (22, 22, 24)   # the demo box's dark gray (#161618)
MAIN = (142, 34, 679, 708)   # the main photo on the site image
THUMBS = [(65, 36, 125, 97), (66, 104, 125, 165), (66, 172, 125, 233), (65, 240, 125, 301), (66, 309, 125, 370)]
ARROWS = ((592, -1, "Back"), (637, 1, "Forward"))   # centre x, which way it points
AY, AR = 666, 19


def rounded(w, h, r, s=4):
    mk = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mk).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=255)
    return mk.resize((w, h), Image.LANCZOS)


def layer(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def layers(work):
    light = Image.open(LIGHT).convert("RGB")
    size = (light.width * K, light.height * K)
    big = light.resize(size, Image.LANCZOS)
    box = lambda b: tuple(v * K for v in b)
    PARTS.mkdir(parents=True, exist_ok=True)
    made = []

    # 1. the page: white and black swapped to dark (Nike's black text becomes light, its black button light)
    page = ImageOps.invert(big).point(lambda v: int(17 + v * (240 - 17) / 255)).convert("RGBA")
    made.append(("Page", page))

    # 2. the photo's background panel, the demo box's gray
    x0, y0, x1, y1 = box(MAIN)
    panel = layer(size)
    panel.paste(Image.new("RGBA", (x1 - x0 + K, y1 - y0 + K), GRAY + (255,)), (x0, y0), rounded(x1 - x0 + K, y1 - y0 + K, 10 * K))
    made.append(("Photo Background", panel))

    # 3. him: cut out, relit for a dark room (less exposure, his outline into shadow, darker toward the floor)
    ph = np.asarray(Image.open(work / "in/main.png").convert("RGB")).astype(float)
    raw = Image.open(work / "mask/main.png").convert("L")
    H, W = ph.shape[:2]
    px = max(W, H) / 600
    mk0 = raw.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(int(5 * px) | 1))
    mk = np.asarray(mk0.filter(ImageFilter.GaussianBlur(1.0 * px)), float) / 255
    core = np.asarray(mk0.filter(ImageFilter.MinFilter(int(9 * px) | 1)).filter(ImageFilter.GaussianBlur(14 * px)), float) / 255
    rim = np.clip(mk - core, 0, 1)
    ys = np.linspace(0, 1, H)[:, None]
    lit = ph * (0.9 * (1 - 0.45 * rim) * (1 - 0.14 * ys ** 1.5))[..., None]
    lum = lit.mean(axis=2, keepdims=True)
    lit = np.clip(lum + (lit - lum) * 1.04, 0, 255)
    him = Image.fromarray(np.dstack([lit, mk * 255]).astype("uint8"), "RGBA").resize((x1 - x0 + K, y1 - y0 + K), Image.LANCZOS)
    clip = rounded(x1 - x0 + K, y1 - y0 + K, 10 * K)
    him.putalpha(Image.fromarray((np.asarray(him.getchannel("A"), float) * np.asarray(clip, float) / 255).astype("uint8")))
    lay = layer(size)
    lay.alpha_composite(him, (x0, y0))
    made.append(("Him (Relit)", lay))

    # 4. the thumbnails, light as on the page
    for n, t in enumerate(THUMBS, 1):
        a0, b0, a1, b1 = box(t)
        w, h = a1 - a0 + K, b1 - b0 + K
        lay = layer(size)
        lay.paste(big.crop((a0, b0, a0 + w, b0 + h)).convert("RGBA"), (a0, b0), rounded(w, h, 4 * K))
        made.append((f"Thumbnail {n}", lay))

    # 5. the arrow buttons as dark glass: what is under them blurred and dimmed, a faint ring, a light chevron
    flat = Image.new("RGBA", size)
    for _, im in made:
        flat.alpha_composite(im)
    glass = Image.blend(flat.convert("RGB").filter(ImageFilter.GaussianBlur(8 * K)), Image.new("RGB", size, (44, 44, 48)), 0.7)
    S = 3
    for cx, way, name in ARROWS:
        lay = layer((size[0] * S, size[1] * S))
        bb = tuple(v * K * S for v in (cx - AR, AY - AR, cx + AR, AY + AR))
        circ = Image.new("L", lay.size, 0)
        ImageDraw.Draw(circ).ellipse(bb, fill=255)
        lay.paste(glass.resize(lay.size).convert("RGBA"), (0, 0), circ)
        ImageDraw.Draw(lay).ellipse(bb, outline=(255, 255, 255, 60), width=int(0.8 * K * S))
        a = 5
        tip, back = cx + way * a * 0.55, cx - way * a * 0.55
        ImageDraw.Draw(lay).line([(back * K * S, (AY - a) * K * S), (tip * K * S, AY * K * S), (back * K * S, (AY + a) * K * S)],
                                 fill=(245, 245, 247, 255), width=int(1.9 * K * S), joint="curve")
        made.append((f"{name} Arrow (Glass)", lay.resize(size, Image.LANCZOS)))

    files = []
    for n, (name, im) in enumerate(made):
        f = PARTS / f"{n:02d} {name}.png"
        im.save(f)
        files.append((name, f))
    # the PhotoCraft file: the page first, then every other part placed on it at its own place, each named
    args = ["photocraft-cli", "run", str(files[0][1]),
            "--cmd", "layer.setProps", "--params", json.dumps({"name": files[0][0]})]
    for name, f in files[1:]:
        args += ["--cmd", "file.placeEmbedded", "--params", json.dumps({"path": str(f), "scale": 100, "fit": False, "smartObject": False,
                                                                       "center": [size[0] / 2, size[1] / 2]}),
                 "--cmd", "layer.setProps", "--params", json.dumps({"name": name})]
    subprocess.run(args + ["--out", str(BOARD)], check=True, capture_output=True)
    print("wrote", BOARD)


def export():
    tmp = PARTS / "_flat.png"
    subprocess.run(["photocraft-cli", "convert", str(BOARD), str(tmp)], check=True, capture_output=True)
    im = Image.open(tmp).convert("RGB")
    im.resize((im.width // K, im.height // K), Image.LANCZOS).save(OUT, quality=88)
    tmp.unlink()
    print("wrote", OUT)


if __name__ == "__main__":
    layers(Path(sys.argv[2])) if sys.argv[1] == "layers" else export()
