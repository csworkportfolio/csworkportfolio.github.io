"""Recuts the Mars Men PSA for the AI page (assets/ai/marsmen.mp4) from the raw takes, which have no subtitles:
the same lines in the same order as the finished video, jump cut at the pauses into short shots that each zoom
or shift a little (the TikTok-style punch-ins of the original edit, and more of them), with captions styled after
Wes Anderson's type: Futura for the titles and subtitles, a slab serif for title cards, centered, in mustard, white
and dusty pink. Some sit behind the speaker (the "content aware" style), cut out of every frame with Apple's
Vision person segmentation (tools/person_mask.swift).

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
# head, "sub" a small yellow film subtitle, "card" a dusty pink slab serif title card between two rules
STYLES = ["top", "sub", "card", "stack", "sub", "top", "card", "sub", "stack", "top"]
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


def text_layer(text, pop, style):
    """One caption, centered, in its line's style, landing with a small pop."""
    text = text.upper().rstrip(",.?!")
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    if style == "top":
        # mustard Futura Bold, a little open, as large as fits; main() puts him back in front of it
        size = int(fit(text, W * 0.9, 200, track=0.04) * pop)
        spaced(d, W / 2, H * 0.05, text, font(FUTURA, 2, size), size * 0.04, YELLOW + (255,))
        return layer
    if style == "stack":
        # white Futura Bold, one word a line, each as wide as it can be, also behind him
        y = H * 0.035
        for w in text.split():
            size = int(min(fit(w, W * 0.88, 210, track=0.03), 180) * pop)
            spaced(d, W / 2, y, w, font(FUTURA, 2, size), size * 0.03, WHITE + (255,))
            y += size * 0.9
        return layer
    if style == "sub":
        # a film subtitle: small yellow Futura Bold, low and centered, the way his narrators are subtitled
        size = int(min(fit(text, W * 0.86, 52, track=0.06), 52) * pop)
        spaced(d, W / 2, H * 0.83, text, font(FUTURA, 2, size), size * 0.06, YELLOW + (255,))
        return soft_shadow(layer, 4, 0.6)
    # "card": a title card in dusty pink slab serif, widely spaced, between two thin rules, set on his dark jacket
    size = int(min(fit(text, W * 0.66, 54, path=SLAB, index=2, track=0.14), 54) * pop)
    f = font(SLAB, 2, size)
    y = H * 0.5
    spaced(d, W / 2, y, text, f, size * 0.14, PINK + (255,))
    half = min(W * 0.42, spaced_width(text, f, size * 0.14) / 2 + size * 0.6)
    for ry in (y - size * 0.45, y + size * 1.25):
        d.line([(W / 2 - half, ry), (W / 2 + half, ry)], fill=PINK + (255,), width=max(2, size // 20))
    return soft_shadow(layer, 5, 0.7)


def main(mask_tool, sdr_tool):
    words = json.loads((ROOT / "tools/marsmen-words.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    sdr = {}
    for take, name in FILES.items():   # tone-map each HDR take to standard video once
        sdr[take] = tmp / f"{take}.mov"
        run(sdr_tool, CLIPS / name, sdr[take])
    cut, caps, t0, n = [], [], 0.0, 0
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
            for g in caption_groups(ws[first:last + 1]):
                caps.append([t0 + max(0.0, g[0][0] - start), " ".join(w[2] for w in g).replace("Fuck", "F#%&"), STYLES[i]])
            t0 += end - start
            n += 1
        cut.append({"take": take, "from": round(piece_from, 2), "to": round(t0, 2)})
    for i in range(len(caps)):
        caps[i].append(caps[i + 1][0] if i + 1 < len(caps) else t0)   # [start, text, style, end]
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
