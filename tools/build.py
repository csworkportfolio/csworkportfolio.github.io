#!/usr/bin/env python3
"""Build the portfolio site.

Reads page content from content/*.json, optimizes every referenced image,
GIF and video into media/ (cached, so re-runs are fast), and writes one
index.html per page.

    python3 tools/build.py                       # sources in ../wix-export and ../source-extra
    python3 tools/build.py --src /path/to/originals --src /another/folder

Once media/manifest.json exists, pages can be rebuilt without the original
files; only new or changed media needs them.
"""
import argparse
import colorsys
import hashlib
import itertools
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
MEDIA = ROOT / "media"
MANIFEST = MEDIA / "manifest.json"

FULL_MAX = 2000      # longest edge for lightbox / full-size images
STRIP_MAX_H = 960    # gallery strip images are shown ~470px tall, so 2x
BG_MAX_W = 2400      # full-bleed background images
VIDEO_MAX_W = 1280   # GIFs become MP4s no wider than this

esc = html.escape


# ---------------------------------------------------------------- media

class Media:
    def __init__(self, src_dirs):
        self.src_dirs = [Path(d) for d in src_dirs]
        self.manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        self.used = set()

    def find(self, name):
        # macOS screenshot names use a narrow no-break space before AM/PM.
        variants = [name, re.sub(r" (AM|PM)\b", " \\1", name)]
        for d in self.src_dirs:
            for v in variants:
                p = d / v
                if p.exists():
                    return p
        return None

    @staticmethod
    def slug(name):
        stem = re.sub(r"\.[A-Za-z0-9]{3,4}$", "", name)
        s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48] or "file"
        return f"{s}-{hashlib.md5(name.encode()).hexdigest()[:6]}"

    def get(self, name, role="default"):
        """Return manifest info for a source file, processing it if needed."""
        key = f"{role}:{name}"
        self.used.add(key)
        src = self.find(name)
        entry = self.manifest.get(key)
        if entry and entry.get("kind") == "image" and entry.get("boxv") != 1:
            entry = None   # older entry without the visible-box measurement: process it again
        if entry and (src is None or entry.get("mtime") == int(src.stat().st_mtime)):
            if all((ROOT / f).exists() for f in entry["files"]):
                return entry
        if src is None:
            sys.exit(f"Missing source file: {name!r} (pass --src to point at the originals)")
        print(f"  processing {name} [{role}]")
        entry = self.process(src, name, role)
        entry["mtime"] = int(src.stat().st_mtime)
        self.manifest[key] = entry
        MANIFEST.write_text(json.dumps(self.manifest, indent=1))  # keep progress if interrupted
        return entry

    def process(self, src, name, role):
        base = self.slug(name) + ("-bg" if role == "bg" else "") + ("-light" if role.startswith("light") else "")
        kind = sniff(src)
        if kind in ("gif", "mp4"):
            if role.startswith("light"):
                return self.to_video(src, base, gif=kind == "gif", max_w=int(role[5:] or 720), crf="30")
            return self.to_video(src, base, gif=kind == "gif")
        im = Image.open(src)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if has_alpha(im) else "RGB")
        out = {"kind": "image", "files": []}
        if role == "bg":
            full = fit(im, max_w=BG_MAX_W)
            out["src"] = save_webp(full, f"{base}.webp", q=72)
        else:
            full = fit(im, max_edge=FULL_MAX)
            out["src"] = save_webp(full, f"{base}.webp", q=82)
            small = fit(im, max_h=STRIP_MAX_H, max_w=1600)
            if small.size != full.size:
                out["sm"] = save_webp(small, f"{base}-sm.webp", q=80)
        out["w"], out["h"] = full.size
        out["boxv"] = 1
        if im.mode == "RGBA":
            # where the picture itself ends inside its transparent margins (a baked-in shadow counts as margin),
            # as fractions of the image, so a caption can line up with the visible edge rather than the file's
            bb = im.getchannel("A").point(lambda a: 255 if a > 128 else 0).getbbox()
            if bb:
                w, h = im.size
                box = [round(bb[0] / w, 4), round(bb[1] / h, 4), round(bb[2] / w, 4), round(bb[3] / h, 4)]
                if box != [0, 0, 1, 1]:
                    out["box"] = box
        out["files"] = [v for k, v in out.items() if k in ("src", "sm")]
        return out

    def to_video(self, src, base, gif, max_w=None, crf=None):
        mp4 = f"media/{base}.mp4"
        crf = crf or ("27" if gif else "26")
        vf = f"scale='trunc(min({max_w or VIDEO_MAX_W},iw)/2)*2':-2:flags=lanczos"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf,
               "-c:v", "libx264", "-preset", "medium", "-crf", crf,
               "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += ["-an"] if gif else ["-c:a", "aac", "-b:a", "128k"]
        subprocess.run(cmd + [str(ROOT / mp4)], check=True)
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "f.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / mp4),
                            "-frames:v", "1", str(frame)], check=True)
            im = Image.open(frame).convert("RGB")
            poster = save_webp(fit(im, max_h=STRIP_MAX_H, max_w=1600), f"{base}-poster.webp", q=78)
        w, h = probe_size(ROOT / mp4)
        return {"kind": "loop" if gif else "video", "src": mp4, "poster": poster,
                "w": w, "h": h, "files": [mp4, poster]}

    def save(self):
        # Drop entries (and files) no page references any more.
        keep = {k: v for k, v in self.manifest.items() if k in self.used}
        live = {f for v in keep.values() for f in v["files"]}
        for f in MEDIA.iterdir():
            rel = f"media/{f.name}"
            if f.name != "manifest.json" and rel not in live:
                f.unlink()
        MANIFEST.write_text(json.dumps(dict(sorted(keep.items())), indent=1))


def sniff(path):
    head = path.read_bytes()[:12]
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp":
        return "mp4"
    return "image"


def has_alpha(im):
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        alpha = im.convert("RGBA").getchannel("A")
        return alpha.getextrema()[0] < 250
    return False


def fit(im, max_edge=None, max_w=None, max_h=None):
    w, h = im.size
    scale = 1.0
    if max_edge:
        scale = min(scale, max_edge / max(w, h))
    if max_w:
        scale = min(scale, max_w / w)
    if max_h:
        scale = min(scale, max_h / h)
    if scale >= 1:
        return im
    return im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def save_webp(im, filename, q):
    rel = f"media/{filename}"
    im.save(ROOT / rel, "WEBP", quality=q, method=4)
    return rel


def probe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


# ---------------------------------------------------------------- items

def video_kind(vid):
    return "vimeo" if vid.isdigit() else "youtube"


def gallery_item(raw, media, site):
    """Normalize a gallery entry from content JSON into data for the page."""
    if isinstance(raw, str):
        raw = {"src": raw}
    item = {k: raw[k] for k in ("title", "desc", "tools", "link", "cap", "zoom") if k in raw}
    if "v" in raw:
        vid = raw["v"]
        meta = site["videos"][vid]
        poster = media.get(meta["poster"])
        item.update(type=video_kind(vid), id=vid, vw=meta["w"], vh=meta["h"],
                    thumb=poster.get("sm", poster["src"]), w=poster["w"], h=poster["h"])
        return item
    name = raw.get("src") or raw.get("mp4")
    # "light": true (720px) or a width in px asks for a smaller encode of a heavy loop, for this item only
    light = raw.get("light")
    m = media.get(name, f"light{light if isinstance(light, int) and light is not True else ''}" if light else "default")
    if m["kind"] == "image":
        item.update(type="image", thumb=m.get("sm", m["src"]), full=m["src"], w=m["w"], h=m["h"])
        if m.get("box"):
            item["box"] = m["box"]
    else:
        item.update(type=m["kind"], src=m["src"], thumb=m["poster"], w=m["w"], h=m["h"])
    return item


def fix_paths(item, root):
    out = dict(item)
    for k in ("thumb", "full", "src"):
        if k in out:
            out[k] = root + out[k]
    if "link" in out:
        out["link"] = {**out["link"], "href": root + out["link"]["href"]}
    return out


# ---------------------------------------------------------------- HTML

PLAY_ICON = '<span class="play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg></span>'


def tile(item, i, root, crop=None, inline=False, play="hover", gid=0):
    label = item.get("title") or {"image": "image", "loop": "animation", "video": "video"}.get(item["type"], "video")
    alt = esc(item.get("title", ""))
    w, h = item["w"], item["h"]
    embed = item["type"] in ("vimeo", "youtube")
    if item["type"] == "loop" or (item["type"] == "video" and play == "auto"):
        # GIF-loops always play; an uploaded video plays silently only where Wix autoplays it.
        media = (f'<video class="tile-media" muted loop playsinline preload="none" '
                 f'poster="{root}{item["thumb"]}" data-src="{root}{item["src"]}" width="{w}" height="{h}" '
                 f'aria-hidden="true"></video>')
    else:
        media = (f'<img class="tile-media" src="{root}{item["thumb"]}" width="{w}" height="{h}" '
                 f'alt="{alt}" loading="lazy" decoding="async">')
    autoplaying = play == "auto" and item["type"] in ("vimeo", "youtube", "video")
    play_icon = PLAY_ICON if item["type"] in ("vimeo", "youtube", "video") and not autoplaying else ""
    # A video tile takes the video's own shape, so vertical videos sit one gallery
    # gap from their neighbours; a gallery can still crop every tile to one shape.
    shape = crop or (f'{item["vw"]}/{item["vh"]}' if embed else None)
    action = "Play video" if inline else "View larger"
    attrs = (f' data-video="{item["type"]}:{item["id"]}" data-vw="{item["vw"]}" data-vh="{item["vh"]}"'
             if embed else "")
    # Width comes from height x ratio in plain CSS math; Safari ignores aspect-ratio on buttons.
    if shape:
        sw, sh = (float(x) for x in shape.split("/"))
        ratio = sw / sh
    else:
        ratio = w / h
    cls = "tile tile-video" if embed else "tile"
    # a caption under the tile (the piece's title and his part in it), when the gallery has one
    cap, by = "", ""
    if item.get("cap"):
        cap = f'<p class="tile-cap" id="cap-{gid}-{i}"><strong>{esc(item.get("title", ""))}</strong><span>{esc(item["cap"])}</span></p>'
        by = f' aria-describedby="cap-{gid}-{i}"'
    box = item.get("box")
    inset = f"--cl:{box[0] * 100:.2f}%;--cr:{(1 - box[2]) * 100:.2f}%;" if box else ""
    zoom = f' style="--zoom:{item["zoom"]}"' if item.get("zoom") else ""   # crops in a little, for a poster with letterbox bars
    return (f'<li class="tile-wrap" style="--r:{ratio:.4f};{inset}"><button class="{cls}" type="button" data-index="{i}"{attrs}{by}{zoom} '
            f'aria-label="{action}: {esc(label)}">{media}{play_icon}</button>{cap}</li>')


def json_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


CHEVRON_L = '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>'
CHEVRON_R = '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>'
STRIP_IDS = itertools.count(1)   # keeps tile caption ids unique across the galleries on a page


def strip(items, root, label, opts=None, kind="gallery", hint=False):
    """A Wix-style slider. opts carries the per-gallery Wix settings: height, gap,
    crop, speed (continuous auto-scroll in px/s; absent = still), loop and label."""
    opts = opts or {}
    inline = kind == "videos"
    data = json_script([fix_paths(it, root) for it in items])
    gid = next(STRIP_IDS)
    tiles = "".join(tile(it, i, root, opts.get("crop"), inline, opts.get("play", "hover"), gid) for i, it in enumerate(items))
    style = "".join(f"--{k}:{opts[o]}px;" for o, k in (("height", "tile-h"), ("gap", "gap")) if o in opts)
    # the widest piece's ratio: on a narrow screen every tile shrinks to the height that piece fits at, so a
    # strip keeps one height instead of each tile shrinking on its own
    def _ratio(it):
        shape = opts.get("crop") or (f'{it["vw"]}/{it["vh"]}' if it["type"] in ("vimeo", "youtube") else None)
        if shape:
            a, b_ = (float(x) for x in shape.split("/"))
            return a / b_
        return it["w"] / it["h"]
    if items:
        style += f"--rmax:{max(_ratio(it) for it in items):.4f};"
    data_attrs = (f' data-speed="{opts.get("speed", 0)}" data-play="{opts.get("play", "click" if inline else "hover")}"'
                  + (' data-loop' if opts.get("loop") else "") + (' data-restart' if opts.get("restart") else ""))
    cls = "strip strip-videos" if inline else "strip"
    if opts.get("ground"):
        cls += " strip-ground"   # a light band behind the tiles, for white screenshots on the white page
    caption = ""
    if opts.get("label"):
        caption = f'<p class="gal-label{" above" if opts.get("label_pos") == "above" else ""}">{esc(opts["label"])}</p>'
    section = f'''
<section class="{cls}" data-gallery aria-label="{esc(label)}"{data_attrs}{f' style="{style}"' if style else ""}>
  <div class="strip-viewport" tabindex="0">
    <ul class="strip-track">{tiles}</ul>
  </div>
  <button class="strip-arrow strip-prev" type="button" aria-label="Previous item">{CHEVRON_L}</button>
  <button class="strip-arrow strip-next" type="button" aria-label="Next item">{CHEVRON_R}</button>
  <script type="application/json" class="gallery-data">{data}</script>
</section>'''
    if hint:
        caption += '<p class="strip-hint"><span class="hint-mouse">Hover to Slow Down / Swipe to See More / Click to View Closer</span><span class="hint-touch">Swipe to See More / Tap to View Closer</span></p>'
    return (caption + section) if opts.get("label_pos") == "above" else (section + caption)


def paragraphs(ps):
    out = []
    for p in ps:
        if isinstance(p, dict) and "quote" in p:
            out.append(f'<blockquote><p>“{esc(p["quote"])}”</p></blockquote>')
        else:
            out.append(f"<p>{esc(p)}</p>")
    return "\n".join(out)


def asset_version(rel):
    """Short content hash, so browsers fetch the file again whenever it changes."""
    return hashlib.md5((ROOT / rel).read_bytes()).hexdigest()[:8]



def contact_links(site, root, cls):
    """Email, LinkedIn and resume links, each only when site.json has it, so nothing prints a placeholder."""
    links = []
    if site.get("email"):
        links.append(f'<a href="mailto:{esc(site["email"])}">{esc(site["email"])}</a>')
    if site.get("linkedin"):
        links.append(f'<a href="{esc(site["linkedin"])}" rel="noopener">LinkedIn</a>')
    if site.get("resume"):
        links.append(f'<a href="{root}files/christian-sanchez-resume.pdf">Resume (PDF)</a>')
    return f'<span class="{cls}">{"".join(links)}</span>' if links else ""


def footer_links(site):
    return contact_links(site, "", "footer-links")


def layout(page, site, root, body, media, og_image=None):
    nav = []
    active = page.get("nav_active", "")
    for n in site["nav"]:
        cur = n["slug"] == active
        href = root + (n["slug"] + "/" if n["slug"] else "")
        attrs = ' class="seg-item is-active" aria-current="page"' if cur else ' class="seg-item"'
        nav.append(f'<a{attrs} href="{href}">{esc(n["label"])}</a>')
    avatar = media.get(site["avatar"])
    if page["type"] in ("category", "case"):
        header = category_banner(site, root, media)
    else:
        header = "" if page["type"] == "home" else f'''
<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="{root}">
      <img class="avatar" src="{root}{avatar.get("sm", avatar["src"])}" width="96" height="96" alt="">
      <span class="brand-text"><span class="wordmark">{esc(site["wordmark"])}</span><span class="byline">{esc(site["byline"])}</span></span>
    </a>
  </div>
</header>'''
    desc = page.get("description", site["description"])
    robots = f'\n<meta name="robots" content="{page["robots"]}">' if page.get("robots") else ""
    # every page shares the same preview: the top of the home page (absolute URL, as link previews need)
    share = "https://csworkportfolio.github.io/assets/share.jpg"
    og = (f'\n<meta property="og:image" content="{share}">\n<meta property="og:image:width" content="1200">'
          f'\n<meta property="og:image:height" content="630">\n<meta name="twitter:card" content="summary_large_image">'
          f'\n<meta name="twitter:image" content="{share}">')
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(page["title"])}</title>
<meta name="description" content="{esc(desc)}">{robots}
<meta property="og:title" content="{esc(page.get("og_title") or page["title"])}">
<meta property="og:description" content="{esc(desc)}">{og}
<meta name="theme-color" content="#2b2b2b">
<script defer src="https://cloud.umami.is/script.js" data-website-id="cfb8039e-58d3-4d85-b5f8-6567b963fee6" data-domains="csworkportfolio.github.io"></script>
<script>/* like the Job Search AI app: "ios" on an iPhone or iPad, or any window 720px wide or less, gets touch-sized controls */
(function(){{var r=document.documentElement,i=/iPhone|iPad|iPod/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1),m=matchMedia("(max-width: 720px)");function a(){{r.setAttribute("data-os",i||m.matches?"ios":"mac")}}a();m.addEventListener&&m.addEventListener("change",a)}})();</script>
<link rel="stylesheet" href="{root}assets/css/style.css?v={asset_version("assets/css/style.css")}">
<link rel="icon" type="image/png" sizes="32x32" href="{root}assets/icons/favicon-32.png">
<link rel="icon" type="image/png" sizes="512x512" href="{root}assets/icons/icon-512.png">
<link rel="apple-touch-icon" href="{root}assets/icons/apple-touch-icon.png">
<script src="{root}assets/js/main.js?v={asset_version("assets/js/main.js")}" defer></script>
</head>
<body id="top" class="page-{page["type"]}{" " + page["body_class"] if page.get("body_class") else ""}">
<a class="skip-link" href="#main">Skip to content</a>{header}
<nav class="pills" aria-label="Portfolio sections">
  <div class="seg">{"".join(nav)}</div>
</nav>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap footer-row">
    <span>© {esc(site["name"])}</span>{footer_links(site)}
    <a href="#top" class="to-top">Back to top ↑</a>
  </div>
</footer>
<dialog class="lightbox" aria-label="Enlarged view" tabindex="-1">
  <div class="lb-inner">
    <div class="lb-media"></div>
    <div class="lb-caption"></div>
  </div>
  <button class="lb-btn lb-close" type="button" aria-label="Close"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
  <button class="lb-btn lb-prev" type="button" aria-label="Previous"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg></button>
  <button class="lb-btn lb-next" type="button" aria-label="Next"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></button>
</dialog>
</body>
</html>
'''


def shine_colors(path, n=4):
    """The main colours of a case row's photo, made vivid enough to read through the Read More glass."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((96, 96))
    q = im.quantize(16, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    cols = []
    for count, i in q.getcolors():
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in pal[i * 3:i * 3 + 3]))
        cols.append((count * (0.15 + s) * (0.2 + v), h, s, v))  # common, colourful and bright wins
    picked = []
    for _, h, s, v in sorted(cols, reverse=True):
        if all(min(abs(h - p[0]), 1 - abs(h - p[0])) > 0.06 or abs(s - p[1]) > .35 for p in picked):
            picked.append((h, s, v))
        if len(picked) == n:
            break
    for i in range(n - len(picked)):  # too few distinct colours: add lighter tints of the ones found
        h, s, v = picked[i % len(picked)]
        picked.append((h, s * .45, 1))
    out = []
    for h, s, v in picked:
        if s > .12:  # greys stay grey
            s = min(1, s * 1.35 + .1)
        v = min(1, max(.7, v * 1.4))
        out.append("#%02x%02x%02x" % tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v)))
    return out


def slideshow(names, title, root, media):
    """Auto-advancing slideshow of work samples for a home-page case row."""
    slides = []
    for i, name in enumerate(names):
        m = media.get(name)
        hidden = "" if i == 0 else ' aria-hidden="true"'
        if m["kind"] == "image":
            el = (f'<img src="{root}{m.get("sm", m["src"])}" width="{m["w"]}" height="{m["h"]}" alt="" '
                  f'loading="{"eager" if i == 0 else "lazy"}" decoding="async">')
        else:
            el = (f'<video muted loop playsinline preload="none" poster="{root}{m["poster"]}" '
                  f'data-src="{root}{m["src"]}" width="{m["w"]}" height="{m["h"]}"></video>')
        slides.append(f'<li class="slide{" is-current" if i == 0 else ""}"{hidden}>{el}</li>')
    return f'''<div class="slideshow" data-slideshow aria-roledescription="carousel" aria-label="Work samples: {esc(title)}">
      <ul class="slides">{"".join(slides)}</ul>
    </div>'''


def category_banner(site, root, media):
    """The category pages' header: a short band of the home hero's dark gradient with just a centred photo,
    either the home page's cut-out portrait or the round avatar (site.json "category_header")."""
    kind = site.get("category_header", "portrait")
    img = media.get(site["home"]["portrait"] if kind == "portrait" else site["avatar"])
    title, sub = site.get("category_title"), site.get("category_sub")
    text = ""
    if title:
        words = site.get("category_words") or []
        rot = ""
        if words:  # "{word}" in the line: one field at a time, underlined, cycled by main.js; screen readers get the whole list
            spans = "".join(f'<span class="rot-word{" is-on" if i == 0 else ""}">{esc(w)}</span>' for i, w in enumerate(words))
            rot = f'<span class="rotator" aria-hidden="true">{spans}</span><span class="sr-only">{esc(", ".join(words))}</span>'
        sub_ = ""
        if sub:
            # split at the first comma, so phones can put "rooted in…" on its own line
            head, sep, tail = esc(sub).partition(", ")
            line = f'<span class="sub-a">{head}{sep.strip()}</span> <span class="sub-b">{tail}</span>' if sep else head
            sub_ = f'<span class="cat-hero-sub">{line.replace("{word}", rot)}</span>'
        text = f'<span class="cat-hero-text"><span class="cat-hero-title">{esc(title)}</span>{sub_}</span>'
    alt = "" if title else "Christian Sanchez, back to the home page"
    return f'''
<header class="cat-hero cat-hero-{kind}">
  <a class="cat-hero-link" href="{root}"><img src="{root}{img.get("sm", img["src"])}" width="{img["w"]}" height="{img["h"]}" alt="{alt}">{text}</a>
</header>'''


def intro_hero(home, root, media, tag):
    """The "Hi, Christian Sanchez here." intro with the portrait: the home page's hero, and the header of the
    category pages (where the greeting is not the page's heading, so it is a <p>)."""
    portrait = media.get(home["portrait"])
    src = root + portrait.get("sm", portrait["src"])
    # A second copy of the portrait sits at the start of the text, floated with its own outline as the wrap
    # shape, so on big phones to small desktops the intro flows around the silhouette (CSS shows one or other).
    # an invisible spacer floats above it so the portrait sits on the bottom edge (main.js sizes the spacer)
    shaped = (f'<span class="hero-spacer" aria-hidden="true"></span>'
              f'<img class="home-portrait-float" src="{src}" width="{portrait["w"]}" height="{portrait["h"]}" alt="" '
              f'aria-hidden="true" style="shape-outside:url(\'{src}\')">')
    return f'''
<section class="home-hero">
  <div class="wrap home-hero-inner">
    <div class="home-hero-text">
      {shaped}
      <{tag} class="hero-hi">{esc(home["greeting"])}</{tag}>
      {paragraphs(home["intro"])}
    </div>
    <img class="home-portrait" src="{root}{portrait.get("sm", portrait["src"])}" width="{portrait["w"]}" height="{portrait["h"]}" alt="Christian Sanchez">
  </div>
</section>'''


def render_home(page, site, media):
    root = ""
    rows = []
    for c in page["cases"]:
        bg = media.get(c["bg"], "bg")
        slides = slideshow(c["slides"], c["title"], root, media)
        shine = ";".join(f"--s{i}:{col}" for i, col in enumerate(shine_colors(ROOT / bg["src"]), 1))
        rows.append(f'''
<article class="case-row" style="background-image:url('{root}{bg["src"]}')">
  <div class="wrap case-row-inner">
    <div class="case-row-text">
      <p class="kicker">{esc(c["kicker"])}</p>
      <h2>{esc(c["title"])}</h2>
      <span class="shine" style="{shine}"><a class="btn btn-red" href="{root}{c["slug"]}/">Read More<span class="sr-only">: {esc(c["title"])}</span></a></span>
    </div>
    {slides}
  </div>
</article>''')
    hero = intro_hero(page, root, media, "h1")
    page = {**page, "nav_active": ""}
    body = '<h2 class="sr-only">Case studies</h2>' + "".join(rows)
    html_ = layout(page, site, root, body, media)
    # The home hero sits above the section nav, like the original site.
    return html_.replace('<a class="skip-link" href="#main">Skip to content</a>',
                         '<a class="skip-link" href="#main">Skip to content</a>' + hero, 1)


def render_locked(page, site, media):
    """A password-locked page (Ghostwriting): the category layout, with its gallery and text stored encrypted
    (tools/lock_ghostwriting.py) and unlocked in the browser by main.js. Linked only from Social & Writing."""
    lock = (CONTENT / page["lock"]).read_text().strip()
    body = f'''
<section class="wrap lock" data-lock>
  <h1>{esc(page["heading"])}</h1>
  <p class="lock-note">These posts were published under executives' names, so this page is password protected.<br>
  To view it, enter the last four digits of my phone number, listed at the top of my resume.</p>
  <form class="lock-form">
    <label class="sr-only" for="lock-pw">Password</label>
    <input id="lock-pw" class="lock-input" type="password" inputmode="numeric" autocomplete="off" placeholder="Last 4 digits" required>
    <button class="btn" type="submit">Unlock</button>
  </form>
  <p class="lock-error" role="alert" hidden>That password didn't work. Try again.</p>
  <noscript><p class="lock-error">This page needs JavaScript to unlock.</p></noscript>
  <script type="application/json" class="lock-data">{lock}</script>
</section>
<div class="lock-content" hidden></div>'''
    page = {**page, "type": "category", "robots": "noindex, nofollow"}
    return layout(page, site, "../", body, media)


def render_category(page, site, media):
    root = "../"
    parts = []
    first_heading = True
    for b in page["blocks"]:
        if "gallery" in b:
            items = [gallery_item(r, media, site) for r in b["gallery"]]
            parts.append(strip(items, root, "Gallery", b, hint=True))
        else:
            tag = "h1" if first_heading else "h2"
            first_heading = False
            tools = f'<p class="tools">Tools: {esc(b["tools"])}</p>' if b.get("tools") else ""
            parts.append(f'''
<section class="wrap cat-text">
  <{tag}>{esc(b["heading"])}</{tag}>
  <p class="kicker-italic">{esc(b["kicker"])}</p>
  {tools}
  {paragraphs(b["body"])}
</section>''')
    page = {**page, "nav_active": page["slug"]}
    return layout(page, site, root, "\n".join(parts), media)


def glance(rows):
    """The figures under a case study's intro: a large figure and what it counts."""
    cells = "".join(f'<div><dt>{esc(d)}</dt><dd>{esc(n)}</dd></div>' for n, d in rows)
    return f'<div class="wrap glance-wrap"><dl class="glance">{cells}</dl></div>'


def section_open(b, cls="", tag="section"):
    sid = f' id="{esc(b["id"])}"' if b.get("id") else ""
    return f'<{tag} class="wrap prose{cls}"{sid}><h2>{esc(b["h"])}</h2>\n{paragraphs(b.get("p", []))}'


def flow(b, media, root):
    """Request-to-live: a scroll scene. The stage pins under the switcher while the section scrolls past;
    each stage's words take the left side and a real placement, in a phone held in 3D, goes through that
    stage on the right (its layers apart for the brief, together for the build, scanned, signed off,
    scheduled, live). Without script, or with reduced motion, it is the stages in order beside the phone."""
    n = len(b["steps"])
    me_cls = ' class="is-me"'
    names = "".join(
        f'<li><button type="button" data-go="{i}"{me_cls if s.get("who", "me") == "me" else ""}>{esc(s["t"])}</button></li>'
        for i, s in enumerate(b["steps"]))
    panels = []
    for i, s in enumerate(b["steps"]):
        mine = s.get("who", "me") == "me"
        checks = "".join(f"<li>{esc(c)}</li>" for c in s.get("checks", []))
        panels.append(
            f'<div class="sc-panel" data-panel="{i}">'
            f'<p class="sc-who{" is-me" if mine else ""}">{"My Part" if mine else esc(s["who"])}</p>'
            f'<h3>{esc(s.get("title", s["t"]))}</h3><p>{esc(s["d"])}</p>'
            + (f'<ul class="sc-checks">{checks}</ul>' if checks else "") + "</div>")
    if not b.get("phone"):
        # a still walkthrough: the scene never pins; a captioned photograph rides beside the stages, and with
        # "figures" (one per stage) the photograph changes as each stage comes into view
        figs = b.get("figures") or [{"src": b["photo"], "alt": b.get("alt", ""), "caption": b.get("caption", "")}]
        parts = []
        for fg in figs:
            m = media.get(fg["src"])
            cap = f'<figcaption>{esc(fg["caption"])}</figcaption>' if fg.get("caption") else ""
            img = (f'<img src="{root}{m.get("sm", m["src"])}" width="{m["w"]}" height="{m["h"]}" '
                   f'alt="{esc(fg.get("alt", ""))}" loading="lazy" decoding="async">')
            if fg.get("v"):
                # a video figure: it plays silently in place once on screen, and a click opens it in the lightbox
                item = {"type": video_kind(fg["v"]), "id": fg["v"], "vw": 16, "vh": 9, "thumb": root + m.get("sm", m["src"]),
                        "w": m["w"], "h": m["h"], "title": fg.get("title", ""), "desc": fg.get("desc", "")}
                img = (f'<button class="sc-video" type="button" data-video="{item["type"]}:{fg["v"]}" data-vw="16" data-vh="9" '
                       f'aria-label="Play video: {esc(fg.get("title", ""))}">{img}{PLAY_ICON}</button>'
                       f'<script type="application/json" class="sc-video-data">{json_script(item)}</script>')
            parts.append(f'<figure class="sc-photo">{img}{cap}</figure>')
        figure = f'<div class="sc-figs">{"".join(parts)}</div>' if len(parts) > 1 else parts[0]
        return (f'<section class="scene sc-still" id="{esc(b.get("id", "process"))}" data-scene="flow" style="--n:{n}" aria-label="{esc(b["h"])}">'
                '<div class="sc-stage"><div class="wrap sc-grid">'
                f'<div class="sc-text"><h2>{esc(b["h"])}</h2>{paragraphs(b.get("p", []))}'
                f'<ol class="sc-names">{names}</ol><div class="sc-panels">{"".join(panels)}</div></div>'
                f'<div class="sc-visual">{figure}</div></div></div></section>')
    m = media.get(b["phone"])
    img = f'{root}{m["src"]}'
    cuts = b.get("layers", [0, 1])
    layers = []
    for i in range(len(cuts) - 1):
        t, h = cuts[i], cuts[i + 1] - cuts[i]
        layers.append(
            f'<div class="ph-layer" style="--i:{i};top:{t * 100:.2f}%;height:{h * 100:.2f}%">'
            f'<img src="{img}" alt="" style="top:{-t / h * 100:.2f}%;height:{100 / h:.2f}%" loading="lazy"></div>')
    reach = esc(b.get("reach", ""))
    nxt = media.get(b["next"]) if b.get("next") else None
    next_img = f'<img class="ph-next" src="{root}{nxt["src"]}" alt="" loading="lazy">' if nxt else ""
    # "sets": other placements the reader can switch the phone to (the same cuts apply: Nike's story template)
    sets = [{"name": s_["name"], "src": root + media.get(s_["phone"])["src"], "next": root + media.get(s_["next"])["src"]} for s_ in b.get("sets", [])]
    switch = ""
    if len(sets) > 1:
        on_cls = ' class="is-on"'
        btns = "".join(f'<button type="button" data-set="{i}"{on_cls if i == 0 else ""}>{esc(s_["name"])}</button>' for i, s_ in enumerate(sets))
        switch = (f'<div class="sc-switch" role="group" aria-label="Choose the placement shown">{btns}</div>'
                  f'<script type="application/json" class="sc-sets">{json_script(sets)}</script>')
    phone = (f'<figure class="ph" aria-hidden="true"><div class="ph-body">'
             f'<div class="ph-screen"><div class="ph-roll">{"".join(layers)}{next_img}</div></div>'
             '<span class="ph-island"></span><span class="ph-key ph-key-action"></span><span class="ph-key ph-key-up"></span>'
             '<span class="ph-key ph-key-down"></span><span class="ph-key ph-key-side"></span>'
             '<span class="ph-halo"></span><span class="ph-glow"></span><span class="ph-copybox"></span>'
             '<span class="ph-stamp"><svg viewBox="0 0 48 48"><path d="M14 25l7 7 13-15"/></svg>QA approved</span>'
             '<span class="ph-chip">Scheduled for its publish window</span>'
             '<span class="ph-live">Live</span></div></figure>')
    return (f'<section class="scene" id="{esc(b.get("id", "process"))}" data-scene="flow" style="--n:{n}" aria-label="{esc(b["h"])}">'
            '<div class="sc-stage"><div class="wrap sc-grid">'
            f'<div class="sc-text"><h2>{esc(b["h"])}</h2>{paragraphs(b.get("p", []))}'
            f'<ol class="sc-names">{names}</ol><div class="sc-panels">{"".join(panels)}</div></div>'
            f'<div class="sc-visual">{phone}{switch}'
            + (f'<p class="sc-count" aria-hidden="true"><strong data-to="{b.get("reach_to", 20000000)}">{b.get("reach_to", 20000000):,}+</strong>{reach}</p>' if reach else "")
            + '</div></div></div></section>')


def timeline(b):
    """Campaign timeline as a dark scoreboard. Scrolling moves a date from the first day of the contract to
    the last: each campaign's bar fills up to that date, and the readout says the date and how many were
    live. Without script, or with reduced motion, the bars are drawn whole."""
    from datetime import date
    start, end = (date.fromisoformat(d) for d in b["range"])
    span = (end - start).days
    pct = lambda d: round((date.fromisoformat(d) - start).days / span * 100, 2)
    months, d = [], start.replace(day=1)
    while d <= end:
        months.append(f'<span style="left:{max(0, (d - start).days / span * 100):.2f}%">{d.strftime("%B")}</span>')
        d = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)
    lanes = "".join(
        f'<li class="tl-lane{" tl-lane-always" if l.get("always") else ""}" data-start="{pct(l["start"])}" data-end="{pct(l["end"])}"{" data-always" if l.get("always") else ""}>'
        + (f'<a class="tl-label" href="{esc(l["href"])}"><strong>{esc(l["t"])}</strong><span>{esc(l["note"])}</span></a>' if l.get("href")
           else f'<span class="tl-label"><strong>{esc(l["t"])}</strong><span>{esc(l["note"])}</span></span>')
        + f'<div class="tl-track"><span class="tl-bar" style="left:{pct(l["start"])}%;width:{pct(l["end"]) - pct(l["start"]):.2f}%"><i></i></span></div></li>'
        for l in b["lanes"])
    return (f'<section class="tl-scene" id="{esc(b["id"])}" data-scene="timeline" data-start="{start.isoformat()}" data-days="{span}">'
            '<div class="tl-stage"><div class="wrap tl-wrap">'
            f'<div class="tl-head"><h2>{esc(b["h"])}</h2>{paragraphs(b.get("p", []))}</div>'
            '<p class="tl-readout" aria-hidden="true"><strong class="tl-date">June to August</strong><span class="tl-live"></span></p>'
            f'<div class="tl-board"><div class="tl-months">{"".join(months)}<span class="tl-now"></span></div><ol class="tl-lanes">{lanes}</ol></div>'
            + (f'<p class="tl-note">{esc(b["caption"])}</p>' if b.get("caption") else "")
            + '</div></div></section>')


def phases(b):
    """Learn-then-teach: a scene. On a desktop the stage holds while each phase word fills from grey to ink
    in turn and its line appears beside it; on phones, with reduced motion or without script, the words
    fill as they reach the middle of the screen."""
    items = "".join(f'<li><strong>{esc(p["t"])}</strong><span>{esc(p["d"])}</span></li>' for p in b["phases"])
    return (f'<section class="scene ph-scene" id="{esc(b.get("id", "guide"))}" data-scene="phases" style="--n:{len(b["phases"])}" aria-label="{esc(b["h"])}">'
            f'<div class="ph-stage"><div class="wrap prose ph-section"><h2>{esc(b["h"])}</h2>\n{paragraphs(b.get("p", []))}'
            f'<ol class="phases" data-fill>{items}</ol>'
            + (f'<p class="ph-topics">{esc(b["topics"])}</p>' if b.get("topics") else "")
            + "</div></div></section>")


def render_case(page, site, media):
    root = "../"
    hero = page["hero"]
    bg = media.get(hero["bg"], "bg")
    logos = "".join(
        f'<img src="{root}{(m := media.get(l["src"])).get("sm", m["src"])}" width="{m["w"]}" height="{m["h"]}" alt="{esc(l["alt"])}">'
        for l in hero["logos"])
    parts = [f'''
<section class="case-hero" style="background-image:url('{root}{bg["src"]}')">
  <div class="wrap case-hero-inner">
    {f'<div class="case-logos">{logos}</div>' if logos else ""}
    <h1>{esc(hero["title"])}</h1>
    <p class="case-sub">{esc(hero["subtitle"])}</p>
  </div>
</section>
<div class="wrap prose lede-wrap"><p class="lede">{esc(page["lede"])}</p></div>''']
    if page.get("glance"):
        parts.append(glance(page["glance"]))
    for b in page["blocks"]:
        if "steps" in b:
            parts.append(flow(b, media, root))
        elif "lanes" in b:
            parts.append(timeline(b))
        elif "phases" in b:
            parts.append(phases(b))
        elif b.get("notes"):
            # a reference's table of contents, as a two-column list in a tinted band
            # drawn as the document itself: a page with its contents, on a light band beside the words
            items = "".join(f"<li>{esc(t)}</li>" for t in b["items"])
            parts.append(section_open(b, " ph-notes") + paragraphs(b.get("p2", [])) + "</section>"
                         f'<div class="ref-figure"><div class="ref-band"><div class="ref-page" role="img" aria-label="The contents of the authoring reference">'
                         f'<p class="ref-title">{esc(b.get("doc_title", "Authoring reference"))}</p><p class="ref-sub">Contents</p>'
                         f'<ol class="ref-list">{items}</ol></div></div></div>')
        elif "statement" in b:
            parts.append(f'<div class="wrap prose statement-wrap"><p class="statement">{esc(b["statement"])}</p></div>')
        elif "gallery" in b:
            items = [gallery_item(r, media, site) for r in b["gallery"]]
            parts.append(strip(items, root, "Project gallery", b))
        elif "videos" in b:
            items = [gallery_item({"v": v}, media, site) for v in b["videos"]]
            parts.append(strip(items, root, "Videos", {**b, "height": 378}, kind="videos"))
        else:
            intro = " intro" if b["h"] in ("THE PROBLEM", "THE SOLUTION") else ""
            parts.append(section_open(b, intro) + "</section>")
    if page.get("contact"):
        # the page's ending: one line to the reader and the ways to reach him (from site.json)
        parts.append(f'<section class="wrap prose statement-wrap" id="contact"><p class="statement">{esc(page["contact"]["statement"])}</p>'
                     f'{contact_links(site, root, "contact-row")}</section>')
    nxt = page["next"]
    parts.append(f'''
<nav class="wrap case-nav" aria-label="Case study navigation">
  <a class="case-nav-link" href="{root}">Back to Case Studies</a>
  <a class="btn btn-rust" href="{root}{nxt["slug"]}/">{esc(nxt["label"])}</a>
</nav>''')
    page = {**page, "nav_active": "", "description": page.get("description") or page["lede"][:155].rsplit(" ", 1)[0] + "…"}
    if page.get("glance") or any("steps" in b for b in page["blocks"]):
        page["body_class"] = "case-v2"   # the larger type scale that the scene pages use
    return layout(page, site, root, "\n".join(parts), media, og_image=bg["src"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", action="append",
                    help="folder holding original media (repeatable)")
    args = ap.parse_args()
    src_dirs = args.src or [ROOT.parent / "wix-export", ROOT.parent / "source-extra"]
    MEDIA.mkdir(exist_ok=True)
    media = Media(src_dirs)
    site = json.loads((CONTENT / "site.json").read_text())

    pages = [json.loads((CONTENT / "home.json").read_text())]
    site["home"] = pages[0]  # the category pages reuse its intro
    for f in ("categories.json", "cases-1.json", "cases-2.json"):
        pages += json.loads((CONTENT / f).read_text())
    if (CONTENT / "ghostwriting.lock.json").exists():
        pages.append({"type": "locked", "slug": "ghostwriting", "lock": "ghostwriting.lock.json",
                      "nav_active": "organic-social", "heading": "Executive Ghostwriting",
                      "title": "Christian's Executive Ghostwriting",
                      "description": "Executive ghostwriting samples (password protected)."})

    for page in pages:
        print(f"page /{page['slug']}")
        render = {"home": render_home, "category": render_category, "case": render_case, "locked": render_locked}[page["type"]]
        out = render(page, site, media)
        dest = ROOT / page["slug"] / "index.html" if page["slug"] else ROOT / "index.html"
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(out)
    media.save()

    total = sum(f.stat().st_size for f in MEDIA.iterdir())
    print(f"done: {len(pages)} pages, media {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
