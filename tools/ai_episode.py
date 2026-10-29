"""Cuts the real pieces for the AI page's "One Episode, Five Pieces" demo from the Resilience Universe episode with
Kevin Mandia (the public YouTube episode, kept in source-extra/episode with its Whisper word timings):

    assets/ai/episode-linkedin.mp4  the LinkedIn clip, 4:5 (LinkedIn's 1080 by 1350 post), with captions
    assets/ai/episode-vertical.mp4  the Shorts and Reels cut, 9:16, with captions
    assets/ai/episode-quote.jpg     the quote card, 1080 by 1350, in the show's look: the Resilience Universe
                                    lockup, his line and his headshot cut out (Apple Vision, tools/person_mask.swift)
    (and a poster .jpg for each clip)

and prints the episode's waveform (its loudness in 140 slices) for content/ai.json. The captions are his words as
Whisper heard them, with the few it got wrong fixed (FIX); the word being said shows in Cohesity green.

The show's lockup and his headshot are the files Christian saved from Cohesity (source-extra/episode).

Run with Python that has Pillow and numpy:
    swiftc -O tools/person_mask.swift -o /tmp/person_mask
    <python> tools/ai_episode.py /tmp/person_mask
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "source-extra/episode"
EP = SRC / "episode.mp4"
FPS = 30
GREEN = (0, 221, 104)   # Cohesity's bright green
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"   # index 1: Bold
# words Whisper misheard, checked against YouTube's own captions
FIX = {"phone": "vulnerability"}
# each clip: where it starts and ends in the episode (seconds), its size, and the crop (across, in the 1920 x 1080
# frame) that keeps Mandia centered
CLIPS = {
    "linkedin": {"from": 585.4, "to": 633.55, "size": (432, 540), "crop": (864, 1080, 508), "y": 0.8, "font": 30},
    "vertical": {"from": 1160.4, "to": 1181.7, "size": (406, 720), "crop": (608, 1080, 636), "y": 0.7, "font": 30},
}


def chunks(words):
    """Up to three words at a time, breaking after punctuation."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or w[2][-1] in ",.?!":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def caption(size, line, fsize, y):
    """One caption line, centered: the word being said in green, the rest white, with a soft shadow."""
    W, H = size
    layer = Image.new("RGBA", size)
    d = ImageDraw.Draw(layer)
    text = " ".join(w for w, _ in line)
    while d.textlength(text, font=ImageFont.truetype(FONT, fsize, index=1)) > W * 0.9:   # a long line shrinks to fit
        fsize -= 2
    f = ImageFont.truetype(FONT, fsize, index=1)
    x = (W - d.textlength(text, font=f)) / 2
    for i, (w, on) in enumerate(line):
        d.text((x, H * y), w, font=f, fill=GREEN + (255,) if on else (255, 255, 255, 255), anchor="ls")
        x += d.textlength(w + " ", font=f)
    out = Image.new("RGBA", size, (0, 0, 0, 255))
    out.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.85)))
    out.alpha_composite(layer)
    return out


def cut(name, c, words):
    W, H = c["size"]
    cw, ch, cx = c["crop"]
    fix = lambda t: FIX.get(t.rstrip(",.?!").lower(), t.rstrip(",.?!")) + t[len(t.rstrip(",.?!")):]
    span = [(s, e, fix(t)) for s, e, t in words if c["from"] - 0.05 <= s < c["to"]]
    groups = chunks(span)
    dur = c["to"] - c["from"]
    raw = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{c['from']:.3f}", "-t", f"{dur:.3f}", "-i", str(EP), "-vf",
                            f"crop={cw}:{ch}:{cx}:0,scale={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    out = ROOT / f"assets/ai/episode-{name}.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-ss", f"{c['from']:.3f}", "-t", f"{dur:.3f}", "-i", str(EP), "-map", "0:v", "-map", "1:a",
                            "-c:v", "libx264", "-crf", "27", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                            "-shortest", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    n = 0
    while True:
        buf = raw.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = c["from"] + n / FPS
        frame = Image.frombytes("RGB", (W, H), buf).convert("RGBA")
        g = next((g for k, g in enumerate(groups) if g[0][0] <= t < (groups[k + 1][0][0] if k + 1 < len(groups) else c["to"] + 1)), None)
        if g:
            now = max((k for k, w in enumerate(g) if w[0] <= t), default=-1)   # only the word being said is green
            frame.alpha_composite(caption((W, H), [(w[2], k == now) for k, w in enumerate(g)], c["font"], c["y"]))
        enc.stdin.write(frame.convert("RGB").tobytes())
        if n == int(1.5 * FPS):
            frame.convert("RGB").save(ROOT / f"assets/ai/episode-{name}.jpg", quality=82)
        n += 1
    enc.stdin.close()
    enc.wait()
    print(name, n / FPS, "seconds")


def quote_card(mask_tool):
    """The quote card, 1080 by 1350, in the show's look: the Cohesity wordmark (white, its S green) over the Resilience
    Universe lockup, his line in big white type after a green quote mark, FEATURING KEVIN MANDIA, and his headshot
    in black and white, cut out of its backdrop."""
    W, H = 1080, 1350
    card = Image.new("RGB", (W, H), (12, 12, 12))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([-250, -350, 850, 750], fill=70)
    card = Image.composite(Image.new("RGB", (W, H), (60, 60, 60)), card, glow.filter(ImageFilter.GaussianBlur(170)))
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "in").mkdir()
        head = Image.open(SRC / "image-1793244979724.png").convert("RGB")
        head = head.resize((head.width * 2, head.height * 2), Image.LANCZOS)
        head.save(Path(tmp) / "in/h.png")
        subprocess.run([mask_tool, Path(tmp) / "in", Path(tmp) / "out"], check=True, capture_output=True)
        mask = Image.open(Path(tmp) / "out/h.png").convert("L").resize(head.size).filter(ImageFilter.GaussianBlur(1.5))
    head = ImageOps.autocontrast(head.convert("L"), cutoff=1).convert("RGB")
    hh = 1060
    hw = int(head.width * hh / head.height)
    card.paste(head.resize((hw, hh), Image.LANCZOS), (W - hw + 250, H - hh + 40), mask.resize((hw, hh), Image.LANCZOS))
    mark = Image.open(ROOT / "assets/ai/hub/cohesity-wordmark.png").convert("RGBA")
    px = mark.load()
    for y in range(mark.height):
        for x in range(mark.width):
            r, g, b, a = px[x, y]
            if a and not (g > 120 and r < 90):
                px[x, y] = (255, 255, 255, a)
    lock = Image.open(SRC / "image-1793244986028.png").convert("RGBA")
    lw, mw = 460, 260
    lock = lock.resize((lw, int(lock.height * lw / lock.width)), Image.LANCZOS)
    mark = mark.resize((mw, int(mark.height * mw / mark.width)), Image.LANCZOS)
    card.paste(mark, (70 + (lw - mw) // 2, 80), mark)
    card.paste(lock, (70, 80 + mark.height + 28), lock)
    d = ImageDraw.Draw(card)
    bold = lambda n: ImageFont.truetype(FONT, n, index=1)
    y = 80 + mark.height + 28 + lock.height + 270
    d.text((64, y), "\u201c", font=bold(140), fill=GREEN, anchor="ls")
    lines = ["Offense is going to", "force defense to be", "autonomous.\u201d"]
    for i, line in enumerate(lines):
        d.text((70, y + 70 + i * 80), line, font=bold(68), fill="white", anchor="ls")
    yb = y + 70 + len(lines) * 80 + 60
    label = "\u200a".join("FEATURING")
    lf = ImageFont.truetype(FONT, 28, index=7)
    d.text((70, yb), label, font=lf, fill=(235, 235, 235), anchor="ls")
    fw = d.textlength(label, font=lf)
    d.line([(70 + fw + 16, yb - 10), (70 + fw + 78, yb - 10)], fill="white", width=2)
    d.rectangle([70 + fw + 78, yb - 16, 70 + fw + 90, yb - 4], outline="white", width=2)
    d.text((70, yb + 56), "KEVIN MANDIA", font=ImageFont.truetype("/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf", 50), fill="white", anchor="ls")
    card.save(ROOT / "assets/ai/episode-quote.jpg", quality=88)


def main():
    words = json.loads((SRC / "words.json").read_text())
    for name, c in CLIPS.items():
        cut(name, c, words)
    quote_card(sys.argv[1])
    # the waveform: the episode's loudness in 140 slices, 0 to 1
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(EP), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    rms = np.array([np.sqrt(np.mean(s ** 2)) for s in np.array_split(a, 140)])
    peaks = np.clip((rms - rms.min() * 0.6) / (rms.max() - rms.min() * 0.6), 0.08, 1)
    print(json.dumps([round(float(p), 2) for p in peaks]))


if __name__ == "__main__":
    main()
