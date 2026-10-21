#!/usr/bin/env python3
"""Lock the Ghostwriting page: render its gallery and text from the private source file, with the images
inlined, and encrypt the result with a password into content/ghostwriting.lock.json.

The plain text and images never enter the public repo: the source is ../private/ghostwriting.json (outside it)
and only the encrypted file is committed. Run it again whenever the posts change or to set a new password:

    python3 tools/lock_ghostwriting.py

then rebuild with python3 tools/build.py. The password is asked for twice and never stored.
"""
import base64
import getpass
import io
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402  (reuses the site's gallery and text markup)

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT.parent / "private" / "ghostwriting.json"
SOURCES = [ROOT.parent / "wix-export", ROOT.parent / "source-extra"]
OUT = ROOT / "content" / "ghostwriting.lock.json"


def find(name):
    for d in SOURCES:
        p = d / name
        if p.exists():
            return p
    sys.exit(f"Missing source image: {name}")


def data_url(path, max_h, quality):
    im = Image.open(path).convert("RGB")
    if im.height > max_h:
        im = im.resize((round(im.width * max_h / im.height), max_h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=4)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode(), im.width, im.height


def main():
    src = json.loads(PRIVATE.read_text())
    items = []
    for raw in src["items"]:
        path = find(raw["src"])
        thumb, w, h = data_url(path, 1000, 78)    # the tile, about twice its on-screen height
        full, _, _ = data_url(path, 2000, 82)     # the zoomed view
        items.append({"type": "image", "thumb": thumb, "full": full, "w": w, "h": h,
                      "title": raw["title"], "desc": raw["desc"]})
    opts = {"height": src["height"], "gap": src["gap"], "label": src["label"], "play": "click"}
    html = build.strip(items, "", "Ghostwriting samples", opts) + f'''
<section class="wrap cat-text">
  <h2>{build.esc(src["heading"])}</h2>
  {build.paragraphs(src["body"])}
</section>'''

    pw = getpass.getpass("Password for the Ghostwriting page: ")
    if len(pw) < 10 and input(
            "A short password (like 4 digits) keeps casual visitors out, but someone determined could download the\n"
            "locked file and try every combination in minutes. Use it anyway? [y/N] ").strip().lower() != "y":
        sys.exit("Nothing was changed.")
    if getpass.getpass("Again to confirm: ") != pw:
        sys.exit("The passwords didn't match; nothing was changed.")
    res = subprocess.run(["node", str(ROOT / "tools" / "encrypt.mjs")],
                         input=json.dumps({"password": pw, "plaintext": html}).encode(),
                         capture_output=True, check=True)
    OUT.write_text(res.stdout.decode() + "\n")
    print(f"Locked {len(items)} posts into {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB). "
          "Now run: python3 tools/build.py")


if __name__ == "__main__":
    main()
