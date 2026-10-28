"""Recuts the Mars Men PSA for the AI page (assets/ai/marsmen.mp4) from the raw takes, which have no subtitles:
the same lines in the same order as the finished video, jump cut at the pauses into short shots that each zoom
or shift a little (the TikTok-style punch-ins of the original edit, and more of them), with captions styled after
Wes Anderson's type, Futura, centered: mustard or white words set behind the speaker (the "content aware" style,
cut out of every frame with Apple's Vision person segmentation, tools/person_mask.swift) and a small yellow film
subtitle. Most captions pop in a word or two at a time; the big lines (the white stacks) build one word at a time
as he says it and hold the whole phrase until the next one.

The takes are iPhone HDR (HLG, BT.2020). They go through Apple's own tone mapping first (tools/hdr_to_sdr.swift),
or they come out washed out. The word timings (tools/marsmen-words.json) came from Whisper, run on this Mac.
Prints the new timings for content/ai.json.

Run with Python that has Pillow and numpy (the ppt-master venv):
    swiftc -O tools/person_mask.swift -o /tmp/person_mask
    swiftc -O tools/hdr_to_sdr.swift -o /tmp/hdr_to_sdr
    <python> tools/ai_marsmen.py /tmp/person_mask /tmp/hdr_to_sdr
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
# the jump cuts: each line splits at its pauses into shots of about this long, and each shot takes the next
# zoom and framing in turn (scale, then where the crop sits across and down the frame)
SHOT = 1.5
FRAMES = [(1.0, .5, .12), (1.3, .5, .1), (1.12, .4, .12), (1.45, .5, .08), (1.06, .6, .12), (1.36, .44, .1), (1.18, .56, .12)]
# each line's caption style: "top" mustard Futura behind his head, "stack" white Futura words stacked behind his
# head, "sub" a small yellow film subtitle; and the most words a phrase of that style holds
STYLES = ["top", "sub", "stack", "sub", "top", "stack", "sub", "top", "stack", "top"]
PHRASE = {"top": 2, "stack": 4, "sub": 3}
BUILD = {"stack"}   # the styles whose phrases build a word at a time; the rest pop in a word or two at once
BEHIND = {"top", "stack"}


def run(*a):
    subprocess.run([str(x) for x in a], check=True)


def pops(words):
    """One or two words at a time (short words pair up), breaking after punctuation."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 2 or w[2][-1] in ",.?!" or len(w[2]) > 4:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def phrases(words, most):
    """A line's words in phrases of up to `most` words, breaking after punctuation."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == most or w[2][-1] in ",.?!":
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


def text_layer(full, shown, pop, style):
    """One phrase, centered, with its first `shown` words on screen. Every word is set where it sits in the whole
    phrase, so nothing shifts as words arrive; the newest lands with a small pop."""
    full = [w.upper().rstrip(",.?!") for w in full]
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    def word(x, y, w, f, size, gap, fill, newest):
        if newest and pop != 1:
            f = font(FUTURA, 2, int(size * pop))
            x -= (spaced_width(w, f, gap) - spaced_width(w, font(FUTURA, 2, size), gap)) / 2
        for c in w:
            d.text((x, y), c, font=f, fill=fill, anchor="lt")
            x += f.getlength(c) + gap
    if style == "stack":
        # white Futura Bold, one word a line, each as wide as it can be, behind him
        sizes = [min(fit(w, W * 0.88, 210, track=0.03), 170) for w in full]
        total = sum(sizes) * 0.9
        k = min(1.0, H * 0.46 / total)   # four big words still clear his chin
        y = H * 0.035
        for i, w in enumerate(full):
            size = int(sizes[i] * k)
            f, gap = font(FUTURA, 2, size), size * 0.03
            if i < shown:
                word(W / 2 - spaced_width(w, f, gap) / 2, y, w, f, size, gap, WHITE + (255,), i == shown - 1)
            y += size * 0.9
        return layer
    line = " ".join(full)
    if style == "top":
        # mustard Futura Bold, a little open, as large as the whole phrase fits on one line, behind him
        size, y, fill, track = fit(line, W * 0.9, 200, track=0.04), H * 0.05, YELLOW, 0.04
    else:
        # a film subtitle: small yellow Futura Bold, low and centered
        size, y, fill, track = min(fit(line, W * 0.86, 52, track=0.06), 52), H * 0.83, YELLOW, 0.06
    f, gap = font(FUTURA, 2, size), size * track
    x = W / 2 - spaced_width(line, f, gap) / 2
    for i, w in enumerate(full):
        if i < shown:
            word(x, y, w, f, size, gap, fill + (255,), i == shown - 1)
        x += spaced_width(w + " ", f, gap) + gap
    return layer if style == "top" else soft_shadow(layer, 4, 0.6)


def main(mask_tool, sdr_tool):
    words = json.loads((ROOT / "tools/marsmen-words.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    sdr = {}
    for take, name in FILES.items():   # tone-map each HDR take to standard video once
        sdr[take] = tmp / f"{take}.mov"
        run(sdr_tool, CLIPS / name, sdr[take])
    cut, timed, t0, n = [], [], 0.0, 0
    for i, (take, a, b) in enumerate(PIECES):
        ws = words[take]
        # split the line at its pauses into short shots: a shot ends after about SHOT seconds, or at a pause,
        # and the pause itself is cut out
        shots, cur = [], [a]
        for k in range(a, b):
            gap = ws[k + 1][0] - ws[k][1]
            if gap > 0.32 or ws[k][1] - ws[cur[0]][0] >= SHOT:
                cur.append(k); shots.append(cur); cur = [k + 1]
        cur.append(b); shots.append(cur)
        piece_from = t0
        for first, last in shots:
            start = max(0.0, ws[first][0] - 0.05, ws[first - 1][1] + 0.01 if first > 0 else 0.0)
            end = min(ws[last][1] + 0.07, ws[last + 1][0] - 0.02) if last + 1 < len(ws) else ws[last][1] + 0.25
            z, fx, fy = FRAMES[n % len(FRAMES)]
            vf = (f"scale=1080:1920,crop=iw/{z}:ih/{z}:(iw-iw/{z})*{fx}:(ih-ih/{z})*{fy},scale={W}:{H},fps={FPS},setsar=1")
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", sdr[take], "-vf", vf,
                "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{n:03d}.mp4")
            # the same stretch of his voice, faded in and out over a few milliseconds so the jump cuts don't click
            fade = f"afade=t=in:d=0.012,afade=t=out:st={max(0.0, end - start - 0.012):.3f}:d=0.012"
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", sdr[take], "-vn", "-af", fade,
                "-ar", 48000, "-ac", 2, "-c:a", "pcm_s16le", tmp / f"a{n:03d}.wav")
            # each word's time on the cut, for the captions
            for w in ws[first:last + 1]:
                timed.append((i, t0 + max(0.0, w[0] - start), w[2].replace("Fuck", "F#%&")))
            t0 += end - start
            n += 1
        cut.append({"take": take, "from": round(piece_from, 2), "to": round(t0, 2)})
    # the captions: each line's words in phrases; a phrase builds a word at a time and holds until the next
    caps = []
    for i in range(len(PIECES)):
        mine = [(t, w, w) for k, t, w in timed if k == i]
        style = STYLES[i]
        build = style in BUILD
        groups = phrases([(t, t, w) for t, w, _ in mine], PHRASE[style]) if build else pops([(t, t, w) for t, w, _ in mine])
        for ph in groups:
            # a popping caption shows all its words at once: every word takes the phrase's first time
            times = [x[0] for x in ph] if build else [ph[0][0]] * len(ph)
            caps.append({"start": ph[0][0], "times": times, "words": [x[2] for x in ph], "style": style})
    for k, c in enumerate(caps):
        c["end"] = caps[k + 1]["start"] if k + 1 < len(caps) else t0
    (tmp / "list.txt").write_text("".join(f"file 'p{i:03d}.mp4'\n" for i in range(n)))
    (tmp / "alist.txt").write_text("".join(f"file 'a{i:03d}.wav'\n" for i in range(n)))
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", tmp / "alist.txt", "-c", "copy", tmp / "voice.wav")
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", tmp / "list.txt", "-c", "copy", tmp / "cut.mp4")
    (tmp / "frames").mkdir()
    run("ffmpeg", "-v", "error", "-y", "-i", tmp / "cut.mp4", tmp / "frames/%05d.png")
    run(mask_tool, tmp / "frames", tmp / "masks")

    frames = sorted((tmp / "frames").iterdir())
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", str(tmp / "voice.wav"), "-c:v", "libx264", "-crf", "26", "-preset", "slow", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "128k", "-shortest",
                            "-movflags", "+faststart", str(ROOT / "assets/ai/marsmen.mp4")], stdin=subprocess.PIPE)
    for n, f in enumerate(frames):
        t = n / FPS
        frame = Image.open(f).convert("RGBA")
        cap = next((c for c in caps if c["start"] <= t < c["end"]), None)
        if cap:
            shown = sum(1 for x in cap["times"] if x <= t)
            age = t - cap["times"][shown - 1]
            pop = 1.12 - 0.12 * min(1, age / 0.12)   # each word lands with a small pop
            layer = text_layer(cap["words"], shown, pop, cap["style"])
            if cap["style"] in BEHIND:
                mask = Image.open(tmp / "masks" / f.name).convert("L").filter(ImageFilter.GaussianBlur(1.2))
                frame = Image.composite(frame, Image.alpha_composite(frame, layer), mask)
            else:
                frame = Image.alpha_composite(frame, layer)
        enc.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
        if n == int(2.2 * FPS):
            frame.convert("RGB").save(ROOT / "assets/ai/marsmen.jpg", quality=85)
    enc.stdin.close()
    enc.wait()

    # the timings content/ai.json needs: each piece on the final track, and when each kept line plays
    print(json.dumps({"duration": round(t0, 2), "pieces": cut}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
