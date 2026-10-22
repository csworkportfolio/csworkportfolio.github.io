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
        base = self.slug(name) + ("-bg" if role == "bg" else "")
        kind = sniff(src)
        if kind == "gif":
            return self.to_video(src, base, gif=True)
        if kind == "mp4":
            return self.to_video(src, base, gif=False)
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
        out["files"] = [v for k, v in out.items() if k in ("src", "sm")]
        return out

    def to_video(self, src, base, gif):
        mp4 = f"media/{base}.mp4"
        crf = "27" if gif else "26"
        vf = f"scale='trunc(min({VIDEO_MAX_W},iw)/2)*2':-2:flags=lanczos"
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
    item = {k: raw[k] for k in ("title", "desc", "tools", "link") if k in raw}
    if "v" in raw:
        vid = raw["v"]
        meta = site["videos"][vid]
        poster = media.get(meta["poster"])
        item.update(type=video_kind(vid), id=vid, vw=meta["w"], vh=meta["h"],
                    thumb=poster.get("sm", poster["src"]), w=poster["w"], h=poster["h"])
        return item
    name = raw.get("src") or raw.get("mp4")
    m = media.get(name)
    if m["kind"] == "image":
        item.update(type="image", thumb=m.get("sm", m["src"]), full=m["src"], w=m["w"], h=m["h"])
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


def tile(item, i, root, crop=None, inline=False, play="hover"):
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
    return (f'<li class="tile-wrap"><button class="{cls}" type="button" data-index="{i}"{attrs} '
            f'style="--r:{ratio:.4f}" aria-label="{action}: {esc(label)}">{media}{play_icon}</button></li>')


def json_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


CHEVRON_L = '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>'
CHEVRON_R = '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>'


def strip(items, root, label, opts=None, kind="gallery", hint=False):
    """A Wix-style slider. opts carries the per-gallery Wix settings: height, gap,
    crop, speed (continuous auto-scroll in px/s; absent = still), loop and label."""
    opts = opts or {}
    inline = kind == "videos"
    data = json_script([fix_paths(it, root) for it in items])
    tiles = "".join(tile(it, i, root, opts.get("crop"), inline, opts.get("play", "hover")) for i, it in enumerate(items))
    style = "".join(f"--{k}:{opts[o]}px;" for o, k in (("height", "tile-h"), ("gap", "gap")) if o in opts)
    data_attrs = (f' data-speed="{opts.get("speed", 0)}" data-play="{opts.get("play", "click" if inline else "hover")}"'
                  + (' data-loop' if opts.get("loop") else ""))
    cls = "strip strip-videos" if inline else "strip"
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
<meta property="og:title" content="{esc(page["title"])}">
<meta property="og:description" content="{esc(desc)}">{og}
<meta name="theme-color" content="#2b2b2b">
<script>/* like the Job Search AI app: "ios" on an iPhone or iPad, or any window 720px wide or less, gets touch-sized controls */
(function(){{var r=document.documentElement,i=/iPhone|iPad|iPod/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1),m=matchMedia("(max-width: 720px)");function a(){{r.setAttribute("data-os",i||m.matches?"ios":"mac")}}a();m.addEventListener&&m.addEventListener("change",a)}})();</script>
<link rel="stylesheet" href="{root}assets/css/style.css?v={asset_version("assets/css/style.css")}">
<link rel="icon" type="image/png" sizes="32x32" href="{root}assets/icons/favicon-32.png">
<link rel="icon" type="image/png" sizes="512x512" href="{root}assets/icons/icon-512.png">
<link rel="apple-touch-icon" href="{root}assets/icons/apple-touch-icon.png">
<script src="{root}assets/js/main.js?v={asset_version("assets/js/main.js")}" defer></script>
</head>
<body id="top" class="page-{page["type"]}">
<a class="skip-link" href="#main">Skip to content</a>{header}
<nav class="pills" aria-label="Portfolio sections">
  <div class="seg">{"".join(nav)}</div>
</nav>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap footer-row">
    <span>© {esc(site["name"])}</span>
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
    for b in page["blocks"]:
        if "gallery" in b:
            items = [gallery_item(r, media, site) for r in b["gallery"]]
            parts.append(strip(items, root, "Project gallery", b))
        elif "videos" in b:
            items = [gallery_item({"v": v}, media, site) for v in b["videos"]]
            parts.append(strip(items, root, "Videos", {**b, "height": 378}, kind="videos"))
        else:
            intro = " intro" if b["h"] in ("THE PROBLEM", "THE SOLUTION") else ""
            parts.append(f'<section class="wrap prose{intro}"><h2>{esc(b["h"])}</h2>\n{paragraphs(b["p"])}</section>')
    nxt = page["next"]
    parts.append(f'''
<nav class="wrap case-nav" aria-label="Case study navigation">
  <a class="btn btn-rust" href="{root}">Back to Case Studies</a>
  <a class="btn btn-gray" href="#top">Top of Page</a>
  <a class="btn btn-rust" href="{root}{nxt["slug"]}/">{esc(nxt["label"])}</a>
</nav>''')
    page = {**page, "nav_active": "", "description": page["lede"][:155].rsplit(" ", 1)[0] + "…"}
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
