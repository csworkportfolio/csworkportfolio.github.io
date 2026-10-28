"""Makes the AI page's videos and stills (assets/ai/) from the originals on this Mac. Run it again only when an
original changes: python3 tools/ai_media.py. Needs ffmpeg. Every video is muted, small, and loops."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets/ai"
HOME = Path.home()
BUDGET = HOME / "Developer/Projects/Budget AI/docs/screenshots"
MARKUP = HOME / "Developer/Toolbox/markup-ai"
REMARK = HOME / "Developer/Toolbox/mods/remark/demo"
HEARD = HOME / "Developer/Projects/Transcript AI"
JOBS = HOME / "Developer/Projects/Job Search AI/app/icons"
PORTFOLIO = ROOT.parent
HUB = PORTFOLIO / "wix-export/ezgif.com-video-to-gif-converter-2.gif"   # the Champions Hub screen recording
# the post images around the shared post in the Hub replica, cut from the recording's first frame (x0, y0, x1, y1)
HUB_CROPS = {"hpe": (481, 180, 611, 341), "risk": (752, 190, 935, 414), "office": (179, 528, 317, 706),
             "maryland": (481, 528, 611, 706), "cohhpe": (752, 535, 935, 706), "ua1": (1051, 153, 1233, 252),
             "ua2": (1051, 299, 1233, 398), "ua3": (1051, 445, 1233, 544), "ua4": (1051, 591, 1233, 690)}

W, H = 960, 600          # the tool cards' screens (16:10)
HOLD, FADE = 3.2, 0.6    # seconds each screen holds, and the cross-fade between screens


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def tour(name, shots, bg="0x111113"):
    """A looping tour of screenshots: each fits the 16:10 screen on the app's own dark ground, holds, and
    cross-fades into the next; the last fades back into the first so the loop has no seam."""
    shots = shots + shots[:1]
    inputs, chain = [], []
    for i, s in enumerate(shots):
        inputs += ["-loop", "1", "-t", HOLD + FADE, "-i", s]
        chain.append(f"[{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:{bg},"
                     f"setsar=1,fps=30,format=yuv420p[v{i}]")
    last, off = "v0", 0.0
    for i in range(1, len(shots)):
        off += HOLD
        chain.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={off:.2f}[x{i}]")
        last = f"x{i}"
    total = HOLD * (len(shots) - 1) + FADE
    ff(*inputs, "-filter_complex", ";".join(chain), "-map", f"[{last}]", "-ss", FADE, "-t", total - FADE,
       "-c:v", "libx264", "-crf", 28, "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
       OUT / f"{name}.mp4")
    ff("-i", shots[0], "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:{bg}",
       "-q:v", 3, OUT / f"{name}.jpg")


def main():
    OUT.mkdir(exist_ok=True)
    # the Mars Men PSA has its own script (tools/ai_marsmen.py): a recut from the raw takes
    tour("budget-ai", [BUDGET / f for f in ("1-dashboard.png", "2-transactions.png", "4-budgets.png", "6-recurring.png")])
    tour("markup-ai", [REMARK / "photocraft-threads.png", MARKUP / "card-preview.png", MARKUP / "drawing-preview.png",
                       MARKUP / "shelf-preview.png"])
    ff("-i", HEARD / "Release Tools/GitHub Social Preview.png", "-vf", f"scale={W}:-2", "-q:v", 3, OUT / "heardhum.jpg")
    ff("-i", JOBS / "icon-512.png", "-vf", "scale=240:-2", OUT / "job-search-ai.png")
    (OUT / "hub").mkdir(exist_ok=True)
    for name, (x0, y0, x1, y1) in HUB_CROPS.items():
        ff("-ss", 0.2, "-i", HUB, "-frames:v", 1, "-vf", f"crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale=iw*2:ih*2:flags=lanczos",
           "-q:v", 2, OUT / f"hub/{name}.jpg")
    ff("-i", PORTFOLIO / "source-extra/Updated Portrait Color avatar.jpg", "-vf", "scale=96:96:force_original_aspect_ratio=increase,crop=96:96",
       "-q:v", 3, OUT / "hub/me.jpg")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
