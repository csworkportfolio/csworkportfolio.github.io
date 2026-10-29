"""Rebuilds the Mars Men PSA for the AI page (assets/ai/marsmen.mp4) on the finished video's own timeline, without its
burned-in captions: his edit, his soundtrack (voice, music and sound effects, used as he mixed it), every B-roll shot
(the explosion included), from the clean Pexels originals where he found them (source-extra/pexels) and otherwise
from the finished video with its old caption painted out (OpenCV inpainting), and his talking shots taken clean
from the raw takes with punch-in zooms that change every second or so. tools/marsmen-shots.json lists the shots:
where each sits on the timeline and which take and second it came from (matched by sound).

New captions are always big and bold, in Mars Men's type and colors (Fold Grotesque Heavy, white with the key word
in brand orange; the font comes with the brand assets and is passed with --fonts). An earlier look ("wes") followed
Wes Anderson's type, Futura, centered: mustard or white words set behind him (the "content
aware" style, cut out of every frame with Apple's Vision person segmentation, tools/person_mask.swift) and a small
yellow film subtitle; over B-roll, the caption sits where the old one was. Most pop in a word or two at a time;
the big lines (the white stacks) build one word at a time and hold. A phrase set behind him shrinks to stay above
his head, or comes in front if it can't. A second look ("mars") uses Mars Men's own type and colors.

The takes are iPhone HDR (HLG, BT.2020). They go through Apple's own tone mapping first (tools/hdr_to_sdr.swift),
or they come out washed out. The word timings (tools/marsmen-words.json) came from Whisper, run on this Mac.
Prints the timings content/ai.json needs.

Run with Python that has Pillow, numpy and OpenCV (opencv-python-headless):
    swiftc -O tools/person_mask.swift -o /tmp/person_mask
    swiftc -O tools/hdr_to_sdr.swift -o /tmp/hdr_to_sdr
    <python> tools/ai_marsmen.py /tmp/person_mask /tmp/hdr_to_sdr [wes|mars] [--fonts <Fold Grotesque folder>]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
CLIPS = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Downloads/Archive/Misc/Mars Men Video/Hook Body CTA Clips"
FILES = {"Hook 1": "Hook 1.MOV", "Body 1": "Body 1.mov", "Body 2": "Body 2.mov", "Body 3": "Body 3.mov", "CTA": "CTA.mov"}
W, H, FPS = 540, 960, 30
FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"     # 0 Medium, 1 Medium Italic, 2 Bold, 4 Condensed ExtraBold
SLAB = "/System/Library/Fonts/Supplemental/Rockwell.ttc"      # 2 Bold: a slab serif, near the Archer of his credits
YELLOW = (242, 193, 46)    # mustard
PINK = (244, 168, 190)     # dusty pink
WHITE = (255, 255, 255)

# the finished cut, as (take, first word, last word) of the raw takes
PIECES = [("Hook 1", 0, 2), ("Body 3", 0, 19), ("Body 1", 0, 15), ("Body 1", 16, 23), ("Body 2", 11, 32),
          ("CTA", 0, 7), ("CTA", 8, 23), ("CTA", 32, 35), ("CTA", 36, 44), ("CTA", 56, 71)]
# the talking shots punch in and out: every PUNCH seconds the framing moves to the next of these (scale, then
# where the crop sits across and down the frame)
PUNCH = 1.2
FRAMES = [(1.0, .5, .12), (1.3, .5, .1), (1.12, .4, .12), (1.45, .5, .08), (1.06, .6, .12), (1.36, .44, .1), (1.18, .56, .12)]
# each line's caption style: "top" mustard Futura behind his head, "stack" white Futura words stacked behind his
# head, "sub" a small yellow film subtitle; and the most words a phrase of that style holds
STYLES = ["top", "stack", "stack", "top", "stack", "top", "stack", "top", "stack", "top"]   # always big; "sub" is kept for reference
PHRASE = {"top": 2, "stack": 5, "sub": 3}
BUILD = {"stack"}
SNAP = 0.45   # how far ahead of a cut to B-roll a phrase may start and still wait for the cut
# the captions vary phrase by phrase, in this order: big behind his head, a small bold line, a stack to one side,
# and now and then the full height of the frame; some phrases always get the full height
PLACES = ["behind", "small", "side-l", "behind", "small", "side-r", "behind", "small", "full"]
FULL = {"own your results"}
ORANGE = (255, 86, 0)   # Mars Men's brand orange
FINISHED = CLIPS.parent / "Mars Men Video.mov"   # the finished video: its timeline, soundtrack and B-roll
PEXELS = ROOT.parent / "source-extra/pexels"   # the clean B-roll originals from Pexels, named by their Pexels id
# two looks: "wes" (Futura, after Wes Anderson's type) and "mars" (Mars Men's own: Fold Grotesque, white with the
# key word in brand orange, subtitles as white labels on black). Fold Grotesque comes with the brand assets and is
# not kept in this repo: pass its folder with --fonts.
THEMES = {
    "wes": {"head": (FUTURA, 2), "sub": (FUTURA, 2), "top": YELLOW, "stack": WHITE, "subfill": YELLOW, "track": 0.04, "label": False, "accent": None},
    "mars": {"head": ("fold-grotesque-heavy-pro.otf", 0), "sub": ("fold-grotesque-bold-pro.otf", 0), "top": WHITE, "stack": WHITE,
             "subfill": WHITE, "track": 0.0, "label": True, "accent": ORANGE},
}
T = THEMES["wes"]
REC = None   # when a list, text_layer records each word it draws here (for the caption board)   # the styles whose phrases build a word at a time; the rest pop in a word or two at once
BEHIND = {"behind"}


def run(*a):
    subprocess.run([str(x) for x in a], check=True)


def pops(words):
    """One or two words at a time (short words pair up), breaking after punctuation, never inside a TOGETHER pair."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pair = nxt is not None and (bare(w), bare(nxt)) in TOGETHER
        if not pair and (len(cur) >= 2 or w[2][-1] in ",.?!" or len(w[2]) > 4):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# word pairs a caption never splits, even if the phrase runs a word long
TOGETHER = {("seed", "oils"), ("sleep", "tracker"), ("low", "testosterone"), ("jobs", "we"), ("our", "lives"), ("own", "potential")}


def bare(w):
    return w[2].lower().rstrip(",.?!")


def phrases(words, most):
    """A line's words in phrases of up to `most` words, breaking after punctuation, never inside a TOGETHER pair."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pair = nxt is not None and (bare(w), bare(nxt)) in TOGETHER
        if (len(cur) >= most and not pair) or w[2][-1] in ",.?!":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def font(path, index, size):
    return ImageFont.truetype(path, size, index=index)


def fit(text, width, start, path=FUTURA, index=2, track=0.0, low=24):
    size = start
    while size > low and spaced_width(text, font(path, index, size), size * track) > width:
        size -= 4
    return size


def spaced_width(text, f, gap):
    return sum(f.getlength(c) for c in text) + gap * (len(text) - 1)


def spaced(d, cx, y, text, f, gap, fill):
    """Letter-spaced text centered on cx: Anderson's titles are set a little open."""
    x = cx - spaced_width(text, f, gap) / 2
    for c in text:
        d.text((x, y), c, font=f, fill=fill, anchor="lt")
        x += f.getlength(c) + gap


def soft_shadow(layer, blur=6, alpha=0.5):
    """A soft shadow under what is drawn on the layer (no hard outline), so light type reads on the snow."""
    a = layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * alpha))
    shade = Image.new("RGBA", layer.size, (20, 16, 12, 0))
    shade.putalpha(a)
    out = Image.new("RGBA", layer.size)
    out.alpha_composite(shade, (2, 3))
    out.alpha_composite(layer)
    return out


def text_layer(full, shown, pop, style, room=None, at=None):
    """One phrase, centered, with its first `shown` words on screen, and whether it can sit behind him. Every word
    is set where it sits in the whole phrase, so nothing shifts as words arrive; the newest lands with a small pop.
    `room` is how far down the frame his head starts: a phrase set behind him shrinks to stay mostly above it, and
    if it would be too small there it comes in front of him instead."""
    full = [w.upper().rstrip(",.?!") for w in full]
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    hp, hi = T["head"]
    key = max(range(len(full)), key=lambda i: len(full[i])) if T["accent"] else -1   # the brand look's orange word
    def word(x, y, w, path, index, size, gap, fill, newest):
        f = font(path, index, size)
        if newest and pop != 1:
            big = font(path, index, int(size * pop))
            x -= (spaced_width(w, big, gap) - spaced_width(w, f, gap)) / 2
            y -= size * (pop - 1) / 2
            f = big
        if REC is not None:
            REC.append({"word": w, "x": round(x, 1), "y": round(y, 1), "size": f.size, "ascent": f.getmetrics()[0],
                        "font": Path(f.path).name, "color": "#%02x%02x%02x" % tuple(fill[:3]), "gap": round(gap, 2)})
        for c in w:
            d.text((x, y), c, font=f, fill=fill, anchor="lt")
            x += f.getlength(c) + gap
    behind = True
    key_i = key
    def col(i):
        return (T["accent"] if i == key_i else T["stack"]) + (255,)
    if style == "small":
        # one small bold line, low in the frame, in front of him
        line = " ".join(full)
        size = min(fit(line, W * 0.86, 54, hp, hi, 0.02), 54)
        f, gap = font(hp, hi, size), size * 0.02
        x, y = W / 2 - spaced_width(line, f, gap) / 2, H * 0.74
        for i, w in enumerate(full):
            if i < shown:
                word(x, y, w, hp, hi, size, gap, col(i), i == shown - 1)
            x += spaced_width(w + " ", f, gap) + gap
        return soft_shadow(layer, 5, 0.6), False
    if style in ("side-l", "side-r"):
        # a medium stack to one side of him, in front
        sizes = [min(fit(w, W * 0.46, 120, hp, hi, 0.0), 104) for w in full]
        total = sum(sizes) * 0.9
        y = H * 0.56 - total / 2
        for i, w in enumerate(full):
            size = sizes[i]
            ww = spaced_width(w, font(hp, hi, size), 0)
            x = W * 0.05 if style == "side-l" else W * 0.95 - ww
            if i < shown:
                word(x, y, w, hp, hi, size, 0, col(i), i == shown - 1)
            y += size * 0.9
        return soft_shadow(layer, 6, 0.55), False
    if style == "full":
        style, room = "stack", None   # the full height of the frame, below
    if style == "behind":
        # big behind his head; if it would come out too small there, it moves to the side instead
        style = "stack"
        if room is None:
            room = H * 0.3
    if style == "top" and fit(" ".join(full), W * 0.9, 200, hp, hi, T["track"]) < 140:
        style = "stack"   # one line would come out small in a wide face: stack the words big instead
    if style == "thirds":
        # one word to each third of the screen, top to bottom, each stretched to fill its third, in front of him
        for i, w in enumerate(full[:shown]):
            f = font(*T["head"], 400) if T["accent"] else font(FUTURA, 4, 400)
            box = f.getbbox(w)
            im = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8))
            ImageDraw.Draw(im).text((4 - box[0], 4 - box[1]), w, font=f, fill=(T["accent"] if T["accent"] and i == len(full) - 1 else T["stack"]) + (255,))
            third = H / 3
            sc = pop if i == shown - 1 else 1
            tw, th = int(W * 0.94 * sc), int(third * 0.9 * sc)
            im = im.resize((tw, th), Image.LANCZOS)
            layer.alpha_composite(im, (int((W - tw) / 2), int(third * i + (third - th) / 2)))
        return soft_shadow(layer, 8, 0.6), False
    if style == "stack":
        # big words, one a line, each as wide as it can be, behind him
        sizes = [min(fit(w, W * 0.88, 210, hp, hi, T["track"]), 170) for w in full]
        y0 = H * 0.035
        total = sum(sizes) * 0.9
        k = min(1.0, H * 0.46 / total)
        if room is not None:
            k = min(k, (room - y0 + sizes[-1] * 0.25) / total)
            if max(sizes) * k < 80:
                return text_layer([w.lower() for w in full], shown, pop, "side-r", None)
        if room is None:
            # in front of him: the words get the full height of the frame, larger, centered top to bottom
            behind = False
            sizes = [min(fit(w, W * 0.92, 300, hp, hi, T["track"]), 250) for w in full]
            total = sum(sizes) * 0.9
            k = min(1.0, H * 0.86 / total)
            y0 = (H - total * k) / 2
        y = y0
        for i, w in enumerate(full):
            size = int(sizes[i] * k)
            gap = size * T["track"]
            fill = (T["accent"] if i == key else T["stack"]) + (255,)
            if i < shown:
                word(W / 2 - spaced_width(w, font(hp, hi, size), gap) / 2, y, w, hp, hi, size, gap, fill, i == shown - 1)
            y += size * 0.9
        return (layer if behind else soft_shadow(layer, 6, 0.55)), behind
    line = " ".join(full)
    if style == "top":
        path, index = hp, hi
        size, y, fill = fit(line, W * 0.9, 200, path, index, T["track"]), H * 0.05, T["top"]
        if room is not None and size * 0.95 > room - y + size * 0.25:
            size = int(max(0, room - y) / 0.7)
            if size < 110:   # too small behind him: in front of him at full size instead
                size, behind = fit(line, W * 0.9, 200, path, index, T["track"]), False
    else:
        # a subtitle, low and centered: small Futura in the Anderson look, a white label on black in the brand look
        path, index = T["sub"]
        size, y, fill, behind = min(fit(line, W * 0.82, 52, path, index, 0.06), 52), H * 0.83, T["subfill"], False
        if at is not None:
            # over a cutaway's painted-out caption: a little larger, centered on the old caption's spot
            size = min(fit(line, W * 0.84, 64, path, index, 0.06), 64)
            y = H * at - size / 2
    track = T["track"] if style == "top" else 0.06
    f, gap = font(path, index, size), size * track
    x = W / 2 - spaced_width(line, f, gap) / 2
    if style == "sub" and T["label"]:
        part = " ".join(full[:shown])
        pad = size * 0.32
        d.rectangle([x - pad, y - pad * 0.7, x + spaced_width(part, f, gap) + pad, y + size * 1.02 + pad * 0.7], fill=(14, 14, 14, 235))
    for i, w in enumerate(full):
        if i < shown:
            c = (T["accent"] if i == key and style == "top" else fill) + (255,)
            word(x, y, w, path, index, size, gap, c, i == shown - 1)
        x += spaced_width(w + " ", f, gap) + gap
    if style == "sub" and T["label"]:
        return layer, False
    return (layer if behind else soft_shadow(layer, 4 if style == "sub" else 6, 0.6)), behind


def placed(words, times, start, t, fonts):
    """A caption as Christian laid it out on the caption board (tools/marsmen-layout.json): each word at its own
    place, size, stretch, weight and color, italic where he wants it, landing with a small pop when it is said.
    Returns the words set in front of the speaker and the ones set behind him, as two layers."""
    front, back = Image.new("RGBA", (W, H)), Image.new("RGBA", (W, H))
    for w in words:
        at = times[w["i"]] if w["i"] >= 0 else start
        if at > t:
            continue
        pop = 1.12 - 0.12 * min(1, (t - at) / 0.12)
        size = int(round(w["size"] * pop))
        f = font(str(Path(fonts) / f"fold-grotesque-{w['weight']}-pro.otf"), 0, size)
        # a lighter or heavier weight is wider or narrower than the Heavy he placed: keep the word's center
        placed_w = font(str(Path(fonts) / "fold-grotesque-heavy-pro.otf"), 0, int(round(w["size"]))).getlength(w["text"]) * w["stretch"]
        asc, desc = f.getmetrics()
        im = Image.new("RGBA", (int(f.getlength(w["text"]) + size * 0.4), asc + desc))
        ImageDraw.Draw(im).text((0, asc), w["text"], font=f, fill=w["color"], anchor="ls")
        if w["stretch"] != 1:
            im = im.resize((max(1, int(im.width * w["stretch"])), im.height), Image.LANCZOS)
        if w["italic"]:
            # a 12 degree slant, leaning from the baseline
            k = 0.21
            im = im.transform((im.width + int(asc * k), im.height), Image.AFFINE, (1, k, -asc * k, 0, 1, 0), Image.BICUBIC)
        cx = w["x"] + placed_w / 2
        new_w = f.getlength(w["text"]) * w["stretch"]
        x = cx - new_w / 2
        y = w["baseline"] - w["size"] * (pop - 1) / 2 - asc
        layer = Image.new("RGBA", (W, H))
        layer.paste(im, (int(round(x)), int(round(y))))
        (back if w["behind"] else front).alpha_composite(layer)
    return soft_shadow(front, 6, 0.55), back


def head_top(mask):
    """How far down the frame his head starts: the first row where he fills a little of the frame's middle."""
    m = np.asarray(mask.convert("L"))[:, W // 5: W * 4 // 5] > 128
    rows = np.nonzero(m.sum(axis=1) > W * 0.04)[0]
    return int(rows[0]) if len(rows) else H // 2


def main(mask_tool, sdr_tool, theme="wes", fonts=None):
    import cv2
    global T
    T = dict(THEMES[theme])
    if theme == "mars":
        T["head"] = (str(Path(fonts) / T["head"][0]), 0)
        T["sub"] = (str(Path(fonts) / T["sub"][0]), 0)
    out = ROOT / "assets/ai/marsmen.mp4" if theme == "mars" else ROOT.parent / f"previews/marsmen-{theme}.mp4"
    words = json.loads((ROOT / "tools/marsmen-words.json").read_text())
    shots = json.loads((ROOT / "tools/marsmen-shots.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    sdr = {}
    for take in {s["take"] for s in shots if "broll" not in s or "keyed" in s}:   # tone-map each HDR take to standard video once
        sdr[take] = tmp / f"{take}.mov"
        run(sdr_tool, CLIPS / FILES[take], sdr[take])

    # the picture, shot by shot on the finished video's frames: B-roll from the finished video, talking shots from
    # the clean takes, split into punch-ins
    n, total = 0, int(round(shots[-1]["to"] * FPS))
    for s in shots:
        f0, f1 = int(round(s["from"] * FPS)), int(round(s["to"] * FPS))
        if "keyed" in s:
            # the speaker keyed over the explosion: his clean take now, the clean Pexels explosion behind him later
            vf = f"scale={W}:{H},fps={FPS},setsar=1"
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{s['at']:.4f}", "-i", sdr[s["take"]], "-frames:v", f1 - f0, "-vf", vf,
                "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{n:03d}.mp4")
            n += 1
            continue
        if "pexels" in s:
            # the clean original, cropped to the edit's framing: a 9:16 window `zoom` times into the frame
            px = s["pexels"]
            z = px["zoom"]
            vf = (f"crop=min(iw\\,ih/{z}*9/16):ih/{z}:min(iw-min(iw\\,ih/{z}*9/16)\\,iw*{px['x']}):min(ih-ih/{z}\\,ih*{px['y']}),"
                  f"scale={W}:{H},fps={FPS},setsar=1")
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{px['at']:.3f}", "-i", PEXELS / f"{px['id']}.mp4", "-frames:v", f1 - f0,
                "-vf", vf, "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{n:03d}.mp4")
            n += 1
            continue
        if "broll" in s:
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{f0 / FPS:.4f}", "-i", FINISHED, "-frames:v", f1 - f0,
                "-vf", f"scale={W}:{H},fps={FPS},setsar=1", "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{n:03d}.mp4")
            n += 1
            continue
        step = max(1, int(PUNCH * FPS))
        for g0 in range(f0, f1, step):
            g1 = min(f1, g0 + step) if f1 - (g0 + step) >= step // 2 else f1   # no sliver at the end of a shot
            z, fx, fy = FRAMES[n % len(FRAMES)]
            src = s["at"] + (g0 / FPS - s["from"])
            vf = f"scale=1080:1920,crop=iw/{z}:ih/{z}:(iw-iw/{z})*{fx}:(ih-ih/{z})*{fy},scale={W}:{H},fps={FPS},setsar=1"
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{src:.4f}", "-i", sdr[s["take"]], "-frames:v", g1 - g0, "-vf", vf,
                "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{n:03d}.mp4")
            n += 1
            if g1 == f1:
                break
    (tmp / "list.txt").write_text("".join(f"file 'p{i:03d}.mp4'\n" for i in range(n)))
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", tmp / "list.txt", "-c", "copy", tmp / "cut.mp4")
    (tmp / "frames").mkdir()
    run("ffmpeg", "-v", "error", "-y", "-i", tmp / "cut.mp4", "-frames:v", total, tmp / "frames/%05d.png")
    # paint the old captions out of the B-roll
    windows = []
    for s in shots:
        if "broll" not in s:
            continue
        if "keyed" in s:   # his own shot: captions treat it like his other shots
            continue
        x0, y0, x1, y1 = s["box"]
        if "pexels" in s:   # a clean original: nothing to paint out, the new caption goes where the old one was
            windows.append((s["from"], s["to"], (y0 + y1) / 4 / H))
            continue
        f0, f1 = int(round(s["from"] * FPS)), int(round(s["to"] * FPS))
        for k in range(f0, f1):
            path = tmp / "frames" / f"{k + 1:05d}.png"
            if not path.exists():
                continue
            im = cv2.imread(str(path))
            hole = np.zeros(im.shape[:2], np.uint8)
            cv2.rectangle(hole, (x0 // 2, y0 // 2), (x1 // 2, y1 // 2), 255, -1)
            cv2.imwrite(str(path), cv2.inpaint(im, hole, 6, cv2.INPAINT_TELEA))
        windows.append((s["from"], s["to"], (y0 + y1) / 4 / H))   # where the old caption sat, as a share of the height
    run(mask_tool, tmp / "frames", tmp / "masks")
    # the keyed shot: put the clean explosion behind the speaker, using his mask
    for s in shots:
        if "keyed" not in s:
            continue
        kd, f0, f1 = s["keyed"], int(round(s["from"] * FPS)), int(round(s["to"] * FPS))
        z = kd["zoom"]
        bdir = tmp / "keybg"
        bdir.mkdir(exist_ok=True)
        vf = (f"crop=min(iw\\,ih/{z}*9/16):ih/{z}:min(iw-min(iw\\,ih/{z}*9/16)\\,iw*{kd['x']}):min(ih-ih/{z}\\,ih*{kd['y']}),"
              f"scale={W}:{H},fps={FPS}")
        run("ffmpeg", "-v", "error", "-y", "-ss", f"{kd['bg_at']:.3f}", "-i", PEXELS / f"{kd['bg']}.mp4", "-frames:v", f1 - f0, "-vf", vf, bdir / "%05d.png")
        for k in range(f0, f1):
            name = f"{k + 1:05d}.png"
            fg = Image.open(tmp / "frames" / name).convert("RGB")
            bg = Image.open(bdir / f"{k - f0 + 1:05d}.png").convert("RGB")
            m = Image.open(tmp / "masks" / name).convert("L").filter(ImageFilter.GaussianBlur(1.5))
            Image.composite(fg, bg, m).save(tmp / "frames" / name)

    # every word he says, on the timeline: each shot plays its take from `at`, so a word lands at from + (start - at)
    timed = {}
    for s in shots:
        for k, w in enumerate(words[s["take"]]):
            if s["at"] - 0.02 <= w[0] < s["at"] + (s["to"] - s["from"]) - 0.02:
                timed.setdefault((s["take"], k), (s["from"] + w[0] - s["at"], w[2].replace("Fuck", "F#%&"), w[1] - w[0]))
    piece_of = lambda take, k: next((i for i, (t, a, b) in enumerate(PIECES) if t == take and a <= k <= b), None)
    # the captions: each line's words in phrases; the big lines build a word at a time and hold until the next
    caps, lines = [], {}
    order = sorted(timed.items(), key=lambda kv: kv[1][0])
    for (take, k), (t, text, dur) in order:
        i = piece_of(take, k)
        if i is None:
            continue
        lines.setdefault(i, []).append((t, t, text, dur))
    for i in sorted(lines, key=lambda i: lines[i][0][0]):
        style = STYLES[i]
        build = style in BUILD
        # words said just before a cut to or from B-roll wait for the cut, so a phrase starts whole on the new shot
        cuts_ = [w[0] for w in windows] + [w[1] for w in windows]
        moved = []
        for x in lines[i]:
            e = next((e for e in cuts_ if 0 < e - x[0] <= SNAP and any(y[0] >= e for y in lines[i])), None)
            moved.append((e, e, *x[2:]) if e is not None else x)
        lines[i] = moved
        groups = phrases(lines[i], PHRASE[style]) if build else pops(lines[i])
        starts = [w[0] for w in windows]
        for ph in groups:
            times = [x[0] for x in ph] if build else [ph[0][0]] * len(ph)
            # a phrase that would begin just before a cut to B-roll waits for the cut, so it lands on the new shot
            snap = next((e for e in starts if 0 < e - times[0] <= SNAP), None)
            if snap is not None:
                times = [max(t, snap) for t in times]
            words_ = [x[2] for x in ph]
            key = " ".join(w.lower().rstrip(",.?!") for w in words_)
            caps.append({"start": times[0], "times": times, "words": words_, "style": style})
    caps.sort(key=lambda c: c["start"])
    for k, c in enumerate(caps):
        key = " ".join(w.lower().rstrip(",.?!") for w in c["words"])
        c["style"] = "full" if key in FULL else PLACES[k % len(PLACES)]
        if c["style"] == "small":   # a small line shows the whole phrase at once
            c["times"] = [c["times"][0]] * len(c["times"])
    end = shots[-1]["to"]
    # his layout from the caption board, when there is one; a word he added to the first caption (the F-word, said
    # as the video opens) shows from the first frame
    lay_file = ROOT / "tools/marsmen-layout.json"
    layout = json.loads(lay_file.read_text()) if lay_file.exists() and fonts else {}
    if any(w["i"] < 0 for w in layout.get("1", [])):
        caps[0]["start"] = 0.0
    for k, c in enumerate(caps):
        c["end"] = caps[k + 1]["start"] if k + 1 < len(caps) else end

    (ROOT.parent / "storyboards").mkdir(exist_ok=True)
    (ROOT.parent / "storyboards/marsmen-captions.json").write_text(json.dumps(
        [{"start": round(c["start"], 2), "end": round(c["end"], 2), "words": c["words"], "style": c["style"]} for c in caps], indent=1))
    frames = sorted((tmp / "frames").iterdir())
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", str(FINISHED), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "26",
                            "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest",
                            "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    global REC
    bdir = ROOT.parent / "storyboards/marsmen-board"
    bdir.mkdir(parents=True, exist_ok=True)
    peaks = {max(int(round(c["start"] * FPS)), int(round((c["end"] - 0.08) * FPS))): k for k, c in enumerate(caps)}
    board = []
    for n, f in enumerate(frames):
        t = n / FPS
        frame = Image.open(f).convert("RGBA")
        if n in peaks:
            # the caption board: this caption's clean frame, a cut-out of him, and where every word sits
            k = peaks[n]
            frame.convert("RGB").save(bdir / f"{k + 1:02d}.jpg", quality=90)
            REC = []
        cap = next((c for c in caps if c["start"] <= t < c["end"]), None)
        if cap and str(caps.index(cap) + 1) in layout:
            front, back = placed(layout[str(caps.index(cap) + 1)], cap["times"], cap["start"], t, fonts)
            behind = back.getbbox() is not None
            if behind:
                mask = Image.open(tmp / "masks" / f.name).convert("L").filter(ImageFilter.GaussianBlur(1.2))
                frame = Image.composite(frame, Image.alpha_composite(frame, back), mask)
            frame = Image.alpha_composite(frame, front)
        elif cap:
            cut_away = next((wd for wd in windows if wd[0] <= t < wd[1]), None)
            # over B-roll a phrase keeps its own style and place (so nothing restarts or shows twice), in front of the
            # shot; only the small subtitles move to where the old caption sat
            front = cut_away is not None and cap["style"] != "sub"
            if front and cap["style"] == "behind":
                cap = dict(cap, style="side-l")
            if front:
                cut_away = None
            if not cut_away and not front and cap["style"] in BEHIND and "room" not in cap:
                # where his head is when the phrase first shows decides how big it can be behind him
                cap["room"] = head_top(Image.open(tmp / "masks" / f.name))
            shown = sum(1 for x in cap["times"] if x <= t)
            age = t - cap["times"][shown - 1]
            pop = 1.12 - 0.12 * min(1, age / 0.12)   # each word lands with a small pop
            if cut_away:
                layer, behind = text_layer(cap["words"], shown, pop, "sub", at=cut_away[2])
            else:
                layer, behind = text_layer(cap["words"], shown, pop, cap["style"], cap.get("room"))
                if front and behind:
                    layer, behind = soft_shadow(layer, 6, 0.55), False
            if behind:
                mask = Image.open(tmp / "masks" / f.name).convert("L").filter(ImageFilter.GaussianBlur(1.2))
                frame = Image.composite(frame, Image.alpha_composite(frame, layer), mask)
            else:
                frame = Image.alpha_composite(frame, layer)
        if REC is not None:
            k = peaks[n]
            entry = {"n": k + 1, "start": round(caps[k]["start"], 2), "style": caps[k]["style"], "behind": bool(cap and behind), "words": REC}
            if entry["behind"]:
                cut = Image.open(f).convert("RGBA")
                cut.putalpha(Image.open(tmp / "masks" / f.name).convert("L").filter(ImageFilter.GaussianBlur(1.2)))
                cut.save(bdir / f"{k + 1:02d}-cut.png")
            board.append(entry)
            REC = None
        enc.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
        if n == int(2.2 * FPS) and theme == "mars":
            frame.convert("RGB").save(ROOT / "assets/ai/marsmen.jpg", quality=85)
    enc.stdin.close()
    enc.wait()
    if not layout:   # with his layout in place, board.json keeps the words the board was made from
        (bdir / "board.json").write_text(json.dumps(board, indent=1))

    # the timings content/ai.json needs: when each kept line plays, which take plays when, and the B-roll on top
    spans = {i: [round(v[0][0], 2), round(v[-1][0] + v[-1][3], 2)] for i, v in lines.items()}
    track = []
    for s in shots:
        if track and track[-1]["take"] == s["take"]:
            track[-1]["to"] = s["to"]
        else:
            track.append({"take": s["take"], "from": s["from"], "to": s["to"]})
    print(json.dumps({"duration": round(end, 2), "lines": spans, "final": track,
                      "broll": [{"name": s["broll"], "from": s["from"], "to": s["to"]} for s in shots if "broll" in s]}))


if __name__ == "__main__":
    # tools/ai_marsmen.py <person_mask> <hdr_to_sdr> [wes|mars] [--fonts <Fold Grotesque folder>]
    args = sys.argv[1:]
    fonts = args[args.index("--fonts") + 1] if "--fonts" in args else None
    rest = [a for a in args if a != "--fonts" and a != fonts]
    main(rest[0], rest[1], rest[2] if len(rest) > 2 else "mars", fonts)
