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
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
