"""Recuts the Mars Men PSA for the AI page (assets/ai/marsmen.mp4) from the raw takes, which have no subtitles:
the same lines in the same order as the finished video, a punch-in zoom on every other cut (the TikTok-style
zooms of the original edit), and captions whose style changes from shot to shot to keep the eye moving: big
yellow words set behind the speaker (the "content aware" style), a lower third with the key word in yellow,
big white words stacked behind his head, and black-on-yellow word boxes.

The takes are iPhone HDR (HLG, BT.2020). They go through Apple's own tone mapping first (tools/hdr_to_sdr.swift),
or they come out washed out.

The word timings (tools/marsmen-words.json) came from Whisper, run on this Mac. The speaker is cut out of every
frame with Apple's Vision person segmentation (tools/person_mask.swift), so each caption sits between the
background and him. Prints the new timings for content/ai.json.

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
FONT = "/System/Library/Fonts/Supplemental/Futura.ttc"   # index 4: Futura Condensed ExtraBold
YELLOW = (255, 206, 58)

# the finished cut, as (take, first word, last word) of the raw takes
PIECES = [("Hook 1", 0, 2), ("Body 3", 0, 19), ("Body 1", 0, 15), ("Body 1", 16, 23), ("Body 2", 11, 32),
          ("CTA", 0, 7), ("CTA", 8, 23), ("CTA", 32, 35), ("CTA", 36, 44), ("CTA", 56, 71)]
ZOOMS = [1.0, 1.22, 1.0, 1.18, 1.0, 1.2, 1.0, 1.24, 1.0, 1.16]   # punch in on every other cut
FOCUS_Y = 0.12   # zoom in from near the top, so his head stays under the captions
# each shot's caption style: "top" one big yellow line behind his head, "stack" big white words stacked behind
# his head, "low" a lower third in front, "box" black words on yellow boxes in the middle
STYLES = ["top", "low", "box", "stack", "low", "top", "box", "low", "stack", "top"]
BEHIND = {"top", "stack"}


def run(*a):
    subprocess.run([str(x) for x in a], check=True)


def caption_groups(words):
    """One or two words at a time (short words pair up), breaking after punctuation, each up until the next
    group starts."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 2 or w[2][-1] in ",.?!" or len(w[2]) > 4:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def fit(text, width, start, low=40, index=4):
    size = start
    while size > low and ImageFont.truetype(FONT, size, index=index).getlength(text) > width:
        size -= 4
    return size


def text_layer(text, pop, style):
    """One caption in the shot's style, upper case in Futura Condensed ExtraBold, landing with a small pop."""
    text = text.upper().rstrip(",.?!")
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    if style == "top":
        # as large as fits on one line, yellow, set behind him (main() puts him back in front)
        size = int(fit(text, W * 0.92, 260) * pop)
        font = ImageFont.truetype(FONT, size, index=4)
        d.text((W / 2, H * 0.055), text, font=font, fill=YELLOW + (255,), anchor="mt")
    elif style == "stack":
        # one word a line, white, each as wide as it can be, also behind him
        y = H * 0.035
        for w in text.split():
            size = int(min(fit(w, W * 0.9, 240), 200) * pop)
            font = ImageFont.truetype(FONT, size, index=4)
            d.text((W / 2, y), w, font=font, fill=(255, 255, 255, 255), anchor="mt")
            y += size * 0.86
    elif style == "low":
        # a lower third in front of him: white with a black edge, the longest word in yellow
        words = text.split()
        key = max(words, key=len)
        size = int(min(fit(text, W * 0.86, 120), 104) * pop)
        font = ImageFont.truetype(FONT, size, index=4)
        gap = font.getlength(" ")
        x = W / 2 - font.getlength(" ".join(words)) / 2
        for w in words:
            d.text((x, H * 0.70), w, font=font, fill=(YELLOW if w == key else (255, 255, 255)) + (255,),
                   stroke_width=max(4, size // 14), stroke_fill=(0, 0, 0, 255), anchor="lt")
            x += font.getlength(w) + gap
    else:
        # word boxes: black words on yellow, stacked in the middle, a little tilted
        words = text.split()
        size = int(min(fit(max(words, key=len), W * 0.7, 150), 130) * pop)
        font = ImageFont.truetype(FONT, size, index=4)
        y = H * 0.50 - len(words) * size * 0.55
        for k, w in enumerate(words):
            tw = font.getlength(w)
            box = Image.new("RGBA", (int(tw + size * 0.5), int(size * 1.08)), YELLOW + (255,))
            ImageDraw.Draw(box).text((box.width / 2, box.height * 0.53), w, font=font, fill=(17, 17, 17, 255), anchor="mm")
            box = box.rotate((-3 if k % 2 else 3), expand=True, resample=Image.BICUBIC)
            layer.alpha_composite(box, (int(W / 2 - box.width / 2), int(y)))
            y += size * 1.12
    return layer


def main(mask_tool, sdr_tool):
    words = json.loads((ROOT / "tools/marsmen-words.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    sdr = {}
    for take, name in FILES.items():   # tone-map each HDR take to standard video once
        sdr[take] = tmp / f"{take}.mov"
        run(sdr_tool, CLIPS / name, sdr[take])
    cut, caps, t0 = [], [], 0.0
    for i, (take, a, b) in enumerate(PIECES):
        ws = words[take]
        start = max(0.0, ws[a][0] - 0.06)
        end = min(ws[b][1] + 0.08, ws[b + 1][0] - 0.02) if b + 1 < len(ws) else ws[b][1] + 0.25
        z = ZOOMS[i]
        vf = (f"scale=1080:1920,crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*{FOCUS_Y},scale={W}:{H},fps={FPS},setsar=1")
        run("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", sdr[take], "-vf", vf,
            "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{i:02d}.mp4")
        for g in caption_groups(ws[a:b + 1]):
            caps.append([t0 + g[0][0] - start, " ".join(w[2] for w in g).replace("Fuck", "F#%&"), STYLES[i]])
        cut.append({"take": take, "from": round(t0, 2), "to": round(t0 + end - start, 2)})
        t0 += end - start
    for i in range(len(caps)):
        caps[i].append(caps[i + 1][0] if i + 1 < len(caps) else t0)   # [start, text, style, end]
    (tmp / "list.txt").write_text("".join(f"file 'p{i:02d}.mp4'\n" for i in range(len(PIECES))))
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", tmp / "list.txt", "-c", "copy", tmp / "cut.mp4")
    (tmp / "frames").mkdir()
    run("ffmpeg", "-v", "error", "-y", "-i", tmp / "cut.mp4", tmp / "frames/%05d.png")
    run(mask_tool, tmp / "frames", tmp / "masks")

    frames = sorted((tmp / "frames").iterdir())
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-c:v", "libx264", "-crf", "26", "-preset", "slow", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(ROOT / "assets/ai/marsmen.mp4")], stdin=subprocess.PIPE)
    for n, f in enumerate(frames):
        t = n / FPS
        frame = Image.open(f).convert("RGBA")
        cap = next((c for c in caps if c[0] <= t < c[3]), None)
        if cap:
            age = t - cap[0]
            pop = 1.12 - 0.12 * min(1, age / 0.12)   # each caption lands with a small pop
            layer = text_layer(cap[1], pop, cap[2])
            if cap[2] in BEHIND:
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
