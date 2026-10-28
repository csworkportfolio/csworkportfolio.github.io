"""Recuts the Mars Men PSA for the AI page (assets/ai/marsmen.mp4) from the raw takes, which have no subtitles:
the same lines in the same order as the finished video, a punch-in zoom on every other cut (the TikTok-style
zooms of the original edit), and big yellow captions set behind the speaker, the "content aware" style.

The word timings (tools/marsmen-words.json) came from Whisper, run on this Mac. The speaker is cut out of every
frame with Apple's Vision person segmentation (tools/person_mask.swift), so each caption sits between the
background and him. Prints the new timings for content/ai.json.

Run with Python that has Pillow and numpy (the ppt-master venv):
    swiftc -O tools/person_mask.swift -o /tmp/person_mask
    <python> tools/ai_marsmen.py /tmp/person_mask
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


def text_layer(text, pop):
    """The caption, as large as fits on one line: Futura Condensed ExtraBold, upper case, set high so his head
    covers only the foot of the letters."""
    lines = [text.upper().rstrip(",.?!")]
    size = 260
    while True:
        font = ImageFont.truetype(FONT, size, index=4)
        if max(font.getlength(l) for l in lines) <= W * 0.92 or size < 40:
            break
        size -= 4
    size = int(size * pop)
    font = ImageFont.truetype(FONT, size, index=4)
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    lh = size * 0.92
    top = H * 0.055
    for i, l in enumerate(lines):
        d.text((W / 2, top + i * lh), l, font=font, fill=YELLOW + (255,), anchor="mt")
    return layer


def main(mask_tool):
    words = json.loads((ROOT / "tools/marsmen-words.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    cut, caps, t0 = [], [], 0.0
    for i, (take, a, b) in enumerate(PIECES):
        ws = words[take]
        start = max(0.0, ws[a][0] - 0.06)
        end = min(ws[b][1] + 0.08, ws[b + 1][0] - 0.02) if b + 1 < len(ws) else ws[b][1] + 0.25
        z = ZOOMS[i]
        vf = (f"scale=1080:1920,crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*{FOCUS_Y},scale={W}:{H},fps={FPS},setsar=1")
        run("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", CLIPS / FILES[take], "-vf", vf,
            "-an", "-c:v", "libx264", "-crf", 14, "-pix_fmt", "yuv420p", tmp / f"p{i:02d}.mp4")
        for g in caption_groups(ws[a:b + 1]):
            caps.append([t0 + g[0][0] - start, " ".join(w[2] for w in g).replace("Fuck", "F#%&")])
        cut.append({"take": take, "from": round(t0, 2), "to": round(t0 + end - start, 2)})
        t0 += end - start
    for i in range(len(caps)):
        caps[i].append(caps[i + 1][0] if i + 1 < len(caps) else t0)
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
        cap = next((c for c in caps if c[0] <= t < c[2]), None)
        if cap:
            age = t - cap[0]
            pop = 1.12 - 0.12 * min(1, age / 0.12)   # each caption lands with a small pop
            mask = Image.open(tmp / "masks" / f.name).convert("L").filter(ImageFilter.GaussianBlur(1.2))
            behind = Image.alpha_composite(frame, text_layer(cap[1], pop))
            frame = Image.composite(frame, behind, mask)
        enc.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
        if n == int(2.2 * FPS):
            frame.convert("RGB").save(ROOT / "assets/ai/marsmen.jpg", quality=85)
    enc.stdin.close()
    enc.wait()

    # the timings content/ai.json needs: each piece on the final track, and when each kept line plays
    print(json.dumps({"duration": round(t0, 2), "pieces": cut}))


if __name__ == "__main__":
    main(sys.argv[1])
