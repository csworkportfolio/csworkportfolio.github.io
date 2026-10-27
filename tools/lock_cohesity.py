#!/usr/bin/env python3
"""Lock the Cohesity case study's executive posts: render the carousel that replaces the locked row (the newsletter,
then the posts written for Cohesity's executives) with the posts' images inlined, and encrypt it with the same
passcode as the Ghostwriting page into content/cohesity-exec.lock.json.

The posts come from ../private/ghostwriting.json (outside the public repo), so only the encrypted file is
committed. Run it again whenever those posts change:

    python3 tools/lock_cohesity.py

then rebuild with python3 tools/build.py. The passcode is asked for twice and never stored.
"""
import getpass
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402  (reuses the site's carousel markup)
from lock_ghostwriting import PRIVATE, data_url, find  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "cohesity-exec.lock.json"
# which Ghostwriting posts were written for Cohesity, and the caption each carries under the carousel
POSTS = {
    "Building with AWS, for Cohesity's CPO": "A post I wrote for Cohesity's Chief Product Officer.",
    "AI Resilience at Catalyst on Tour, for the CFO and COO": "A post I wrote for Cohesity's CFO and COO after Catalyst on Tour in Singapore.",
}


def render_html():
    pages = json.loads((build.CONTENT / "cases-1.json").read_text())
    block = next(b for p in pages if p["slug"] == "cohesity" for b in p["blocks"] if b.get("locked_strip"))
    site = json.loads((build.CONTENT / "site.json").read_text())
    lead = block["lead"]
    news = build.gallery_item({k: lead[k] for k in ("v", "title", "desc", "cap") if k in lead}, build.Media([]), site)
    news["thumb"] = "../" + news["thumb"]   # the page sits one folder down; the posts' own images are inlined
    items = [news]
    media = build.Media([build.ROOT.parent / d for d in ("wix-export", "source-extra", "screens")])
    for raw in block.get("open", []):   # the pieces shown in the open after the newsletter ("first": before it)
        it = build.fix_paths(build.gallery_item(raw, media, site), "../")
        items.insert(items.index(news), it) if raw.get("first") else items.append(it)
    src = json.loads(PRIVATE.read_text())
    for raw in src["items"]:
        if raw["title"] in POSTS:
            path = find(raw["src"])
            thumb, w, h = data_url(path, 1000, 78)
            full, _, _ = data_url(path, 2000, 82)
            items.append({"type": "image", "thumb": thumb, "full": full, "w": w, "h": h,
                          "title": raw["title"], "desc": raw["desc"], "cap": POSTS[raw["title"]]})
    if len(items) != 1 + len(block.get("open", [])) + len(POSTS):
        sys.exit("Couldn't find every Cohesity post in private/ghostwriting.json; check the titles in POSTS.")
    opts = {"height": block.get("height", 470), "gap": block.get("gap", 50), "label": "", "ground": True, "play": "auto"}   # the newsletter loops silently, with no play button
    return build.strip(items, "", "Newsletter and executive posts", opts), len(POSTS)


def encrypt(html, pw):
    res = subprocess.run(["node", str(ROOT / "tools" / "encrypt.mjs")],
                         input=json.dumps({"password": pw, "plaintext": html}).encode(),
                         capture_output=True, check=True)
    OUT.write_text(res.stdout.decode() + "\n")


def ask(prompt):
    """A Mac password window (typing into some terminal panes never reaches a hidden prompt); getpass elsewhere."""
    if sys.platform == "darwin":
        script = (f'text returned of (display dialog "{prompt}" default answer "" with hidden answer '
                  'with title "Lock the Cohesity posts" buttons {"Cancel", "OK"} default button "OK")')
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if res.returncode != 0:
            sys.exit("Cancelled; nothing was changed.")
        return res.stdout.rstrip("\n")
    return getpass.getpass(prompt + " ")


def main():
    html, n = render_html()
    pw = ask("Passcode (the same one as the Ghostwriting page):")
    if ask("Again to confirm:") != pw:
        sys.exit("The passcodes didn't match; nothing was changed.")
    encrypt(html, pw)
    print(f"Locked {n} posts into {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB). Now run: python3 tools/build.py")


if __name__ == "__main__":
    main()
