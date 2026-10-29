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
        if entry and entry.get("kind") == "image" and entry.get("boxv") != 3:
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
        # the file name carries the processing version, so a browser that cached an older version (say, with
        # the old baked-in shadow) fetches the new one instead of showing it from cache
        base += "-v3"
        im = Image.open(src)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if has_alpha(im) else "RGB")
        if im.mode == "RGBA" and role != "bg":
            # many old exports sit on a wide transparent canvas (with a baked-in shadow): crop to the artwork
            # itself, so a strip spaces pieces by their real edges and the site's own shadow takes over
            bb = im.getchannel("A").point(lambda a: 255 if a > 128 else 0).getbbox()
            if bb and bb != (0, 0, *im.size):
                im = im.crop(bb)
            # the old baked-in shadow is near-black at partial opacity: clear it, so it can't end in a hard line at
            # the crop's edge (the site draws its own shadow); the artwork's anti-aliased edges keep their colour
            px = im.load()
            a = im.getchannel("A")
            mx = im.convert("RGB").point(lambda v: v).split()
            dark = Image.merge("RGB", mx).convert("L").point(lambda v: 255 if v < 60 else 0)
            soft = a.point(lambda v: 255 if v < 235 else 0)
            from PIL import ImageChops
            kill = ImageChops.multiply(dark, soft)
            im.putalpha(ImageChops.subtract(a, kill))
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
        out["boxv"] = 3
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
    item = {k: raw[k] for k in ("title", "desc", "tools", "link", "cap", "zoom", "note", "bare") if k in raw}
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
        if raw.get("dark"):
            # the same piece with its app interface in dark mode, shown to visitors in dark mode
            md = media.get(raw["dark"])
            item.update(thumb_dark=md.get("sm", md["src"]), full_dark=md["src"])
    else:
        item.update(type=m["kind"], src=m["src"], thumb=m["poster"], w=m["w"], h=m["h"])
        if raw.get("dark"):
            md = media.get(raw["dark"])
            item.update(src_dark=md["src"], thumb_dark=md["poster"])
        if raw.get("pop"):
            # a still for the pop-up (the moving tile is for the strip; opened, the piece holds still)
            mp = media.get(raw["pop"])
            item.update(pop_full=mp["src"], pop_w=mp["w"], pop_h=mp["h"])
        if raw.get("tile_light"):
            # a lighter encode for the strip tile only; the lightbox keeps the full clip
            item["tile_src"] = media.get(name, f"light{raw['tile_light']}")["src"]
            if raw.get("dark"):
                item["tile_src_dark"] = media.get(raw["dark"], f"light{raw['tile_light']}")["src"]
    return item


def fix_paths(item, root):
    out = dict(item)
    for k in ("thumb", "full", "src", "tile_src", "tile_src_dark", "thumb_dark", "full_dark", "src_dark", "pop_full"):
        if k in out:
            out[k] = root + out[k]
    if "link" in out:
        out["link"] = {**out["link"], "href": root + out["link"]["href"]}
    return out


# ---------------------------------------------------------------- HTML

PLAY_ICON = '<span class="play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg></span>'


def tile(item, i, root, crop=None, inline=False, play="hover", gid=0, eager=False):
    label = item.get("title") or {"image": "image", "loop": "animation", "video": "video"}.get(item["type"], "video")
    alt = esc(item.get("title", ""))
    w, h = item["w"], item["h"]
    embed = item["type"] in ("vimeo", "youtube")
    if item["type"] == "loop" or (item["type"] == "video" and play == "auto"):
        # GIF-loops always play; an uploaded video plays silently only where Wix autoplays it.
        media = (f'<video class="tile-media" muted loop playsinline preload="none" '
                 f'poster="{root}{item["thumb"]}" data-src="{root}{item.get("tile_src", item["src"])}" width="{w}" height="{h}" '
                 + (f'data-src-dark="{root}{item.get("tile_src_dark", item["src_dark"])}" data-poster-dark="{root}{item["thumb_dark"]}" ' if item.get("src_dark") else "")
                 + 'aria-hidden="true"></video>')
    else:
        # the first tiles of a page's first strip load straight away, so it never opens as an empty band
        load = ('eager" fetchpriority="high' if i < 2 else "eager") if eager else "lazy"
        media = (f'<img class="tile-media" src="{root}{item["thumb"]}" width="{w}" height="{h}" '
                 f'alt="{alt}" loading="{load}" decoding="async">')
        if item.get("thumb_dark"):
            media = (f'<picture class="tile-pic"><source media="(prefers-color-scheme: dark)" '
                     f'srcset="{root}{item["thumb_dark"]}">{media}</picture>')
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
    if item.get("note"):
        cls += " is-note"
    if item.get("bare"):
        cls += " is-bare"   # a piece shot on the strip's own ground (the shuffling study pages): no card edge of its own   # a document shown as a paper note with an expand mark, as on Social & Writing
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
EXPAND = '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>'
STRIP_IDS = itertools.count(1)   # keeps tile caption ids unique across the galleries on a page


def strip(items, root, label, opts=None, kind="gallery", hint=False, eager=0):
    """A Wix-style slider. opts carries the per-gallery Wix settings: height, gap,
    crop, speed (continuous auto-scroll in px/s; absent = still), loop and label."""
    opts = opts or {}
    inline = kind == "videos"
    data = json_script([fix_paths(it, root) for it in items])
    gid = next(STRIP_IDS)
    tiles = "".join(tile(it, i, root, opts.get("crop"), inline, opts.get("play", "hover"), gid, i < eager)
                    for i, it in enumerate(items))
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
    elif opts.get("rmax"):
        style += f"--rmax:{opts['rmax']};"   # pieces added after (locked tiles): the shape to size them by on phones
    data_attrs = (f' data-speed="{opts.get("speed", 0)}" data-play="{opts.get("play", "click" if inline else "hover")}"'
                  + (' data-loop' if opts.get("loop") else "") + (' data-restart' if opts.get("restart") else ""))
    cls = "strip strip-videos" if inline else "strip"
    if opts.get("ground"):
        cls += " strip-ground"   # a light band behind the tiles, for white screenshots on the white page
    if opts.get("notes"):
        cls += " strip-ground strip-notes"   # long-form pieces as rounded paper notes on the light band
    caption = ""
    if opts.get("label"):
        caption = f'<p class="gal-label{" above" if opts.get("label_pos") == "above" else ""}">{esc(opts["label"])}</p>'
    # one expand button with the arrows opens the piece in view (strips of pieces that play keep just the arrows)
    expand = ("" if all(it["type"] in ("vimeo", "youtube", "video") for it in items) else
              f'\n  <button class="strip-arrow strip-open" type="button" aria-label="View the piece in view larger">{EXPAND}</button>')
    section = f'''
<section class="{cls}" data-gallery aria-label="{esc(label)}"{data_attrs}{f' style="{style}"' if style else ""}>
  <div class="strip-viewport" tabindex="0">
    <ul class="strip-track">{tiles}</ul>
  </div>
  <button class="strip-arrow strip-prev" type="button" aria-label="Previous item">{CHEVRON_L}</button>
  <button class="strip-arrow strip-next" type="button" aria-label="Next item">{CHEVRON_R}</button>{expand}
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
        elif isinstance(p, dict) and "phone" in p:
            # one line said differently on phones (where, say, a play button replaces scrolling)
            out.append(f'<p><span class="only-wide">{esc(p["p"])}</span><span class="only-phone">{esc(p["phone"])}</span></p>')
        else:
            out.append(f"<p>{esc(p)}</p>")
    return "\n".join(out)


def split_top(sel):
    """Split a selector list at its top-level commas only, so :is(a, b) stays whole."""
    parts, depth, cur = [], 0, ""
    for ch in sel:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    return parts + [cur]


def themed_css():
    """style.css follows the device with @media (prefers-color-scheme) blocks. The site also has a light/dark
    switch, which puts .theme-light or .theme-dark on <html>. Write assets/css/site.css: each such block now
    steps aside when the visitor picked the other mode, and a copy of it applies when they picked this one."""
    css = (ROOT / "assets/css/style.css").read_text()
    out, i = [], 0
    pat = re.compile(r"@media \(prefers-color-scheme: (dark|light)\)((?: and \([^)]*\))*)\s*\{")
    for m in pat.finditer(css):
        if m.start() < i:
            continue
        mode, extra = m.group(1), m.group(2)
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        body = css[m.end():j - 1]
        other = "light" if mode == "dark" else "dark"

        def rewrite(state):
            rules = []
            for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", body, flags=re.S)):
                sels = []
                for one in split_top(sel):
                    one = one.strip()
                    if not one:
                        continue
                    h = re.match(r"^(html|:root)((?:\.[\w-]+|\[[^\]]*\])*)(.*)$", one, re.S)
                    if h:
                        sels.append(f"{h.group(1)}{state}{h.group(2)}{h.group(3)}")
                    elif one.startswith("::"):   # a pseudo-element of the root (::view-transition) hangs off html itself
                        sels.append(f"html{state}{one}")
                    else:
                        sels.append(f"html{state} {one}")
                rules.append(f"{', '.join(sels)} {{{decl}}}")
            return "\n  ".join(rules)

        out.append(css[i:m.start()])
        out.append(f"@media (prefers-color-scheme: {mode}){extra} {{\n  {rewrite(f':not(.theme-{other})')}\n}}\n")
        forced = rewrite(f".theme-{mode}")
        out.append(f"@media all{extra} {{\n  {forced}\n}}" if extra else forced)
        i = j
    out.append(css[i:])
    (ROOT / "assets/css/site.css").write_text("/* generated by tools/build.py from style.css: edit style.css */\n" + "".join(out))


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
    # every page but the home page follows the device's light or dark setting (style.css, html.can-dark)
    dark_cls = "" if page["type"] == "home" else ' class="can-dark"'
    return f'''<!doctype html>
<html lang="en"{dark_cls}>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(page["title"])}</title>
<meta name="description" content="{esc(desc)}">{robots}
<meta property="og:title" content="{esc(page.get("og_title") or page["title"])}">
<meta property="og:description" content="{esc(desc)}">{og}
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#e8e8ed">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#000000">
<script defer src="https://cloud.umami.is/script.js" data-website-id="cfb8039e-58d3-4d85-b5f8-6567b963fee6" data-domains="csworkportfolio.github.io"></script>
<script>/* the visitor's light/dark choice from the switch, applied before anything paints: the class for the
   stylesheet, the canvas colour (so the first frame isn't the other mode's white or black) and the browser's bar */
(function(){{try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark"){{var r=document.documentElement;r.classList.add("theme-"+t);r.style.colorScheme=t;r.style.background=t==="dark"?"#000":"#fff";document.addEventListener("DOMContentLoaded",function(){{r.style.background=""}});document.querySelectorAll('meta[name="theme-color"]').forEach(function(m){{m.content=t==="dark"?"#000000":"#e8e8ed"}})}}}}catch(e){{}}}})();</script>
<script>/* like the Job Search AI app: "ios" on an iPhone or iPad, or any window 720px wide or less, gets touch-sized controls */
(function(){{var r=document.documentElement,i=/iPhone|iPad|iPod/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1),m=matchMedia("(max-width: 720px)");function a(){{r.setAttribute("data-os",i||m.matches?"ios":"mac")}}a();m.addEventListener&&m.addEventListener("change",a)}})();</script>
<link rel="stylesheet" href="{root}assets/css/site.css?v={asset_version("assets/css/site.css")}">
<link rel="icon" type="image/png" sizes="32x32" href="{root}assets/icons/favicon-32.png">
<link rel="icon" type="image/png" sizes="512x512" href="{root}assets/icons/icon-512.png">
<link rel="apple-touch-icon" href="{root}assets/icons/apple-touch-icon.png">
<script src="{root}assets/js/main.js?v={asset_version("assets/js/main.js")}" defer></script>
</head>
<body id="top" class="page-{page["type"]}{" " + page["body_class"] if page.get("body_class") else ""}">
<a class="skip-link" href="#main">Skip to content</a>
<button class="theme-toggle" type="button" aria-label="Switch to dark mode"><svg class="tt-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1Z"/></svg><svg class="tt-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg></button>{header}
<nav class="pills" aria-label="Portfolio sections">
  <div class="seg">{"".join(nav)}</div>
</nav>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap footer-row">
    <a href="#top" class="to-top">Back to top <span aria-hidden="true">↑</span></a>
    <span class="footer-meta"><span>© {esc(site["name"])}</span>{footer_links(site)}</span>
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


def piece_titles():
    """Each work sample's title from the galleries (category pages and case studies), by source file,
    so a home slideshow can name what it shows."""
    titles = {}
    def walk(x):
        if isinstance(x, dict):
            name = x.get("src") or x.get("mp4")
            if isinstance(name, str) and x.get("title"):
                titles.setdefault(name, x["title"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for f in ["categories.json", *sorted(p.name for p in CONTENT.glob("cases-*.json"))]:
        walk(json.loads((CONTENT / f).read_text()))
    return titles


def slideshow(names, title, root, media, titles=None):
    """Auto-advancing slideshow of work samples for a home-page case row."""
    titles = titles or {}
    slides = []
    for i, name in enumerate(names):
        m = media.get(name)
        hidden = "" if i == 0 else ' aria-hidden="true"'
        alt = esc(titles.get(name, ""))
        if m["kind"] == "image":
            el = (f'<img src="{root}{m.get("sm", m["src"])}" width="{m["w"]}" height="{m["h"]}" alt="{alt}" '
                  f'loading="{"eager" if i == 0 else "lazy"}" decoding="async">')
        else:
            label = f' aria-label="{alt}"' if alt else ""
            el = (f'<video muted loop playsinline preload="none" poster="{root}{m["poster"]}" '
                  f'data-src="{root}{m["src"]}" width="{m["w"]}" height="{m["h"]}"{label}></video>')
        slides.append(f'<li class="slide{" is-current" if i == 0 else ""}"{hidden}>{el}</li>')
    return f'''<div class="slideshow" data-slideshow aria-roledescription="carousel" aria-label="Work samples: {esc(title)}">
      <ul class="slides">{"".join(slides)}</ul>
    </div>'''


def light_pic(img_html, light, root):
    """Wrap a portrait <img> so light mode shows the colour photo (source media follows the device; main.js
    retargets it when the visitor uses the switch). The <picture> takes no box of its own (style.css)."""
    if not light:
        return img_html
    return (f'<picture class="theme-pic"><source media="(prefers-color-scheme: light)" '
            f'srcset="{root}{light.get("sm", light["src"])}">{img_html}</picture>')


def category_banner(site, root, media):
    """The category pages' header: a short band of the home hero's dark gradient with just a centred photo,
    either the home page's cut-out portrait or the round avatar (site.json "category_header")."""
    kind = site.get("category_header", "portrait")
    img = media.get(site["home"]["portrait"] if kind == "portrait" else site["avatar"])
    lkey = site["home"].get("portrait_light") if kind == "portrait" else site.get("avatar_light")
    light = media.get(lkey) if lkey else None
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
  <a class="cat-hero-link" href="{root}">{light_pic(f'<img src="{root}{img.get("sm", img["src"])}" width="{img["w"]}" height="{img["h"]}" alt="{alt}">', light, root)}{text}</a>
</header>'''


def intro_hero(home, root, media, tag, site=None):
    """The "Hi, Christian Sanchez here." intro with the portrait: the home page's hero, and the header of the
    category pages (where the greeting is not the page's heading, so it is a <p>)."""
    portrait = media.get(home["portrait"])
    light = media.get(home["portrait_light"]) if home.get("portrait_light") else None   # the colour photo, light mode
    src = root + portrait.get("sm", portrait["src"])
    # A second copy of the portrait sits at the start of the text, floated with its own outline as the wrap
    # shape, so on big phones to small desktops the intro flows around the silhouette (CSS shows one or other).
    # an invisible spacer floats above it so the portrait sits on the bottom edge (main.js sizes the spacer)
    shaped = (f'<span class="hero-spacer" aria-hidden="true"></span>'
              + light_pic(f'<img class="home-portrait-float" src="{src}" width="{portrait["w"]}" height="{portrait["h"]}" alt="" '
                          f'aria-hidden="true" style="shape-outside:url(\'{src}\')">', light, root))
    # on the home page the email and LinkedIn sit under the intro; it stays a <p>, the last one, since
    # main.js stands the portrait beside the intro's last paragraph
    contact = ""
    if tag == "h1" and site and home.get("hero_contact"):
        links = contact_links(site, root, "contact-row")
        if site.get("email"):  # phones show "Email" on the pill, the full address doesn't fit beside the portrait
            e = esc(site["email"])
            links = links.replace(f'>{e}</a>', f'><span class="hc-full">{e}</span><span class="hc-short">Email</span></a>', 1)
        contact = f'\n      <p class="hero-contact">{links}</p>'
    return f'''
<section class="home-hero">
  <div class="wrap home-hero-inner">
    <div class="home-hero-text">
      {shaped}
      <{tag} class="hero-hi">{esc(home["greeting"])}</{tag}>
      {paragraphs(home["intro"])}{contact}
    </div>
    {light_pic(f'<img class="home-portrait" src="{root}{portrait.get("sm", portrait["src"])}" width="{portrait["w"]}" height="{portrait["h"]}" alt="Christian Sanchez">', light, root)}
  </div>
</section>'''


def render_home(page, site, media):
    root = ""
    cases = []
    titles = piece_titles()
    n = len(page["cases"])
    # each case's quick view: its samples, large, beside a short summary taken from the start of its case study
    ledes = {c["slug"]: c.get("lede", "") for f in ("cases-1.json", "cases-2.json")
             for c in json.loads((CONTENT / f).read_text())}
    def summary(text):
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
            if "\u2014" in sent or len(out) == 2:
                break
            out.append(sent)
        return " ".join(out)
    for i, c in enumerate(page["cases"]):
        bg = media.get(c["bg"], "bg")
        slides = slideshow(c["slides"], c["title"], root, media, titles)
        shine = ";".join(f"--s{k}:{col}" for k, col in enumerate(shine_colors(ROOT / bg["src"]), 1))
        figs = ""
        if c.get("figures"):
            cells = "".join(f'<div><dt>{esc(d)}</dt><dd data-count="{esc(v)}">{esc(v)}</dd></div>' for v, d in c["figures"])
            figs = f'\n      <dl class="wk-figs">{cells}</dl>'
        elif c.get("result"):
            figs = f'\n      <p class="case-result">{esc(c["result"])}</p>'
        quick = []
        for name in c["slides"]:
            m = media.get(name)
            it = {"title": titles.get(name, ""), "link": {"href": f'{c["slug"]}/', "label": "Read the Case Study"},
                  "quick": {"kicker": c["kicker"], "title": c["title"], "figures": c.get("figures", []),
                            "lede": summary(ledes.get(c["slug"], "")), "shine": shine}}
            if m["kind"] == "image":
                it.update(type="image", thumb=m.get("sm", m["src"]), full=m["src"], w=m["w"], h=m["h"])
            else:
                it.update(type=m["kind"], src=m["src"], thumb=m["poster"], w=m["w"], h=m["h"])
            quick.append(fix_paths(it, root))
        box_bg = (f'style="background-image:url(\'{root}{bg["src"]}\')"' if i == 0 else
                  f'data-bg="{root}{bg["src"]}"')   # later cases fetch their photo and slides as they come near (main.js)
        if i > 0:
            slides = re.sub(r'(<img[^>]*?) src="', r'\1 data-defer-src="', slides)
        cases.append(f'''
<article class="wk-case" data-case="{i}" style="--k:{i}">
  <script type="application/json" class="wk-quick">{json_script(quick)}</script>
  <div class="wk-text">
      <p class="kicker">{esc(c["kicker"])}</p>
      <h2>{esc(c["title"])}</h2>{figs}
      <span class="shine" style="{shine}"><a class="btn btn-red" href="{root}{c["slug"]}/">Read More<span class="sr-only">: {esc(c["title"])}</span></a></span>
  </div>
  <div class="wk-box" {box_bg}>
    {slides}
  </div>
</article>''')
    # the case studies as one scene: on a desktop the stage holds under the tab bar and each case's box
    # slides up over the last as the section scrolls past (main.js); phones, short windows and reduced
    # motion get the cases one after another
    names = "".join(f'<li><button type="button" data-go="{i}">{esc(c.get("name", c["slug"]))}</button></li>'
                    for i, c in enumerate(page["cases"]))
    rows = [f'''
<section class="work" data-scene="work" style="--n:{n}" aria-label="Case studies">
  <div class="wk-stage">
    <div class="wk-inner">
      <ol class="wk-names" aria-label="Case studies">{names}</ol>
      <div class="wk-cases">{"".join(cases)}
      </div>
    </div>
  </div>
</section>''']
    hero = intro_hero(page, root, media, "h1", site)
    page = {**page, "nav_active": ""}
    body = '<h2 class="sr-only">Case studies</h2>' + "".join(rows)
    if page.get("contact"):
        body += (f'\n<section class="wrap prose statement-wrap" id="contact"><p class="statement">'
                 f'{esc(page["contact"]["statement"])}</p>{contact_links(site, root, "contact-row")}</section>')
    html_ = layout(page, site, root, body, media)
    # The home hero sits above the section nav, like the original site.
    return html_.replace('<a class="skip-link" href="#main">Skip to content</a>',
                         '<a class="skip-link" href="#main">Skip to content</a>' + hero, 1)


LOCK_IDS = itertools.count(1)


def tile_caption(title, cap):
    """The title and caption under a piece, as a strip shows them (tile-cap)."""
    return f'<p class="tile-cap"><strong>{esc(title)}</strong><span>{esc(cap)}</span></p>' if cap else ""


LOCK_ICON = ('<span class="gw-lock"><svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2.5"/>'
             '<path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></span>')
# a locked piece in a carousel carries a Slide to Unlock track; sliding its knob to the end (or Return on it)
# brings up the passcode bubble (gw-ask)
SLIDE = ('<span class="gw-slide"><span class="gw-slide-text" aria-hidden="true">Slide to Unlock</span>'
         '<button class="gw-knob" type="button" aria-label="Slide to unlock the executive posts">'
         f'{CHEVRON_R}</button></span>')


def lock_widget(src, shapes, height=470, gap=20, note=True, lead="", lead_r=None, row="", reads=False):
    """The locked ghostwriting posts: a row of empty liquid-glass panes, each the height and shape of the post it
    hides (shapes are width / height), and a four-dot passcode
    that fills as the digits go in. The right code decrypts the posts in the browser (main.js) and the
    bubbles pop open into them. Nothing readable is in the page until then.
    "row": a whole carousel to show instead (open pieces and locked ones, locked_strip_row); its passcode then
    waits in a bubble that pops up only when a locked piece is slid open. "reads": once unlocked, the posts
    open as the reading scene (the Ghostwriting posts) rather than staying a carousel."""
    n = next(LOCK_IDS)
    lock_icon = LOCK_ICON
    # "lead": a piece shown in the open before the locked ones, the same height
    first = f'<li class="gw-bubble gw-lead" style="--i:0;--r:{lead_r:.4f}">{lead}</li>' if lead else ""
    k = 1 if lead else 0
    bubbles = first + "".join(f'<li class="gw-bubble" style="--i:{i + k};--r:{r}" aria-hidden="true">{lock_icon}</li>'
                              for i, r in enumerate(shapes))
    n_locked = len(shapes)
    shapes = ([lead_r] if lead else []) + list(shapes)
    rmax = max(shapes)
    rsum = sum(shapes)
    hide = "" if lead else ' aria-hidden="true"'
    ul = row or (f'<ul class="gw-bubbles"{hide} '
                 f'style="--gh:{height}px;--gg:{gap}px;--rmax:{rmax}">{bubbles}</ul>')
    ask_open = ('<div class="gw-ask" role="dialog" aria-label="Unlock the executive posts" hidden>'
                '<button class="gw-ask-close" type="button" aria-label="Close"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>\n  '
                if row else "")
    ask_close = "\n  </div>" if row else ""
    dots = '<span class="gw-dot"></span>' * 4
    # the posts' shapes, for the reading layout the locked posts take on desktop (main.js)
    shapes_attr = f' data-shapes="{",".join(f"{r:.4f}" for r in shapes[-n_locked:])}"' if reads else ""
    first_line = note if isinstance(note, str) else "These posts were published under executives' names, so they're locked."
    hint = (f'<p class="lock-note">{esc(first_line)}<br>'
            'To open them, enter the last four digits of my phone number, listed at the top of my resume.</p>') if note else ""
    return f'''
<div class="gw" data-lock{" data-plain" if lead or (row and not reads) else ""}{" data-row" if row else ""}{shapes_attr} data-src="{src}" style="--gg:{gap}px;--gn:{len(shapes) - 1};--rsum:{rsum:.4f}">
  {ul}
  {ask_open}{hint}
  <form class="lock-form gw-form">
    <label class="sr-only" for="lock-pw-{n}">Passcode: the last four digits of my phone number</label>
    <p class="gw-label" aria-hidden="true">Enter passcode</p>
    <div class="gw-pin">
      <input id="lock-pw-{n}" class="lock-input gw-input" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="4" autocomplete="off" required>
      <span class="gw-dots" aria-hidden="true">{dots}</span>
    </div>
    <button class="sr-only" type="submit">Unlock</button>
  </form>
  <p class="lock-error" role="alert" hidden>That code didn't work. Try again.</p>{ask_close}
  <noscript><p class="lock-error">These posts need JavaScript to unlock.</p></noscript>
</div>
<div class="lock-content" hidden></div>'''


def locked_strip_items(b, media, site):
    """The open pieces of a locked_strip block, in order: the lead (a newsletter loop), then each "open" piece,
    or before the lead when it says "first". tools/lock_cohesity.py builds the unlocked carousel from the same list."""
    lead = b["lead"]
    news = gallery_item({k: lead[k] for k in ("v", "title", "desc", "cap") if k in lead}, media, site)
    items = [news]
    for raw in b.get("open", []):
        it = gallery_item(raw, media, site)
        items.insert(items.index(news), it) if raw.get("first") else items.append(it)
    return items


def locked_strip_opts(b):
    """A locked_strip block's carousel settings, the standard strip's: captions, controls, scrolling on its own."""
    return {"height": b.get("height", 470), "gap": b.get("gap", 50), "label": "", "ground": True, "play": "auto",
            "speed": b.get("speed", 35), "restart": True}


def locked_row(items, count, caps, root, label, opts, r=0.8):
    """A standard carousel for locked posts: any open pieces as ordinary tiles, then one glass tile per locked
    post, all one shape (r, 4:5 unless set; they no longer copy the hidden posts' shapes, so they are wide
    enough to slide), each with its caption (caps, else "Locked Executive Post") and a Slide to Unlock track."""
    html = strip(items, root, label, opts)
    def cap(i):
        return caps[i] if i < len(caps) else ["Locked Executive Post", "A post I wrote for an executive."]
    locked = "".join(
        f'<li class="tile-wrap tile-wrap-locked" style="--r:{r:.4f}"><div class="tile tile-locked gw-bubble">'
        f'<span class="gw-pane" aria-hidden="true">{LOCK_ICON}</span>{SLIDE}</div>{tile_caption(*cap(i))}</li>'
        for i in range(count))
    return html.replace("</ul>", locked + "</ul>", 1)


def locked_strip_row(b, media, site, root):
    """The Cohesity carousel shown while locked: its open pieces (locked_strip_items), then its locked posts."""
    return locked_row(locked_strip_items(b, media, site), len(b["shapes"]), b.get("caps", []), root,
                      b.get("aria", "Newsletter and executive posts"), locked_strip_opts(b), b.get("locked_r", 0.8))


def locked_posts_row(b, root):
    """The Ghostwriting posts while locked (Social & Writing and the Ghostwriting page): locked tiles only, in
    the standard carousel, moving on its own."""
    # rmax: on narrow screens they size like the carousels around them (about 0.86 of the width over 1.2),
    # not by their own 4:5 shape, which would make them nearly full-screen
    opts = {"height": b.get("row_height", 380), "gap": 50, "label": "", "ground": True, "speed": 35, "restart": True, "rmax": 1.2}
    return locked_row([], len(b["shapes"]), b.get("caps", []), root, "Executive ghostwriting, locked", opts)


def publish_lock(name, root):
    """The encrypted posts go out as their own file, fetched only when someone enters the passcode, so the page
    itself stays light. Returns its address from the page."""
    out = ROOT / "files" / name
    out.parent.mkdir(exist_ok=True)
    data = (CONTENT / name).read_bytes()
    if not out.exists() or out.read_bytes() != data:
        out.write_bytes(data)
    return f"{root}files/{name}?v={hashlib.md5(data).hexdigest()[:8]}"


def locked_shape():
    """The locked block on Social & Writing, which the standalone Ghostwriting page shows the same way."""
    for pg in json.loads((CONTENT / "categories.json").read_text()):
        for b in pg["blocks"]:
            if b.get("locked"):
                return b
    return {"shapes": [0.5] * 5}


def render_locked(page, site, media):
    """A password-locked page (Ghostwriting): the category layout, with its gallery and text stored encrypted
    (tools/lock_ghostwriting.py) and unlocked in the browser by main.js. Linked only from Social & Writing."""
    lock = publish_lock(page["lock"], "../")
    body = f'''
<section class="wrap lock">
  <h1>{esc(page["heading"])}</h1>
  {lock_widget(lock, locked_shape()["shapes"], row=locked_posts_row(locked_shape(), "../"), reads=True)}
</section>'''
    # the newer category style, as on Social & Writing: its carousel controls (play/pause, arrows) sit bottom right
    page = {**page, "type": "category", "robots": "noindex, nofollow", "body_class": "cat-v2"}
    return layout(page, site, "../", body, media)


def render_category(page, site, media):
    root = "../"
    parts = []
    first_heading = True
    first_gallery = True
    blocks = page["blocks"]
    for n, b in enumerate(blocks):
        if "gallery" in b:
            items = [gallery_item(r, media, site) for r in b["gallery"]]
            # a strip takes its name from the heading just above it, when there is one
            prev = blocks[n - 1] if n else None
            label = f'{prev["heading"]} gallery' if page.get("v2") and prev and "heading" in prev else "Gallery"
            eager = page.get("eager_first", 0) if first_gallery else 0
            first_gallery = False
            parts.append(strip(items, root, label, b, eager=eager))   # no hint line: the zoom cursor and the arrows say it
        elif b.get("locked"):
            tag = "h1" if first_heading else "h2"
            first_heading = False
            lock = publish_lock(b["locked"], root)
            parts.append(f'''
<section class="wrap cat-text is-lead cat-locked">
  <{tag}>{esc(b["heading"])}</{tag}>
  <p class="kicker-italic">{esc(b["kicker"])}</p>
  {paragraphs(b.get("body", []))}
</section>
<section class="gw-wrap gw-mixed">{lock_widget(lock, b["shapes"], row=locked_posts_row(b, root), reads=True)}
</section>''')
        else:
            tag = "h1" if first_heading else "h2"
            first_heading = False
            tools = f'<p class="tools">Tools: {esc(b["tools"])}</p>' if b.get("tools") else ""
            # a heading that introduces the strip below it sits close to that strip
            lead = ""
            if page.get("v2") and n + 1 < len(blocks) and "gallery" in blocks[n + 1]:
                lead = " is-lead is-first" if n == 0 else " is-lead"
            parts.append(f'''
<section class="wrap cat-text{lead}">
  <{tag}>{esc(b["heading"])}</{tag}>
  <p class="kicker-italic">{esc(b["kicker"])}</p>
  {tools}
  {paragraphs(b["body"])}
</section>''')
    if page.get("contact"):
        parts.append(f'<section class="wrap cat-text cat-contact" id="contact"><p>{esc(page["contact"]["statement"])}</p>'
                     f'{contact_links(site, root, "contact-row")}</section>')
    page = {**page, "nav_active": page["slug"]}
    if page.get("v2"):
        page["body_class"] = "cat-v2"   # the case-v2 type scale for this category's headings
    return layout(page, site, root, "\n".join(parts), media)


def glance(rows, logos=""):
    """The figures under a case study's intro: a large figure and what it counts. With logos (the partners a
    figure counts), they follow the figures in a row ending in a "+", for the many more."""
    cells = "".join(f'<div><dt>{esc(d)}</dt><dd>{esc(n)}</dd></div>' for n, d in rows)
    if logos:
        cells += f'<div class="glance-logos">{logos}<span class="glance-more">and many more</span></div>'
    return f'<div class="wrap glance-wrap"><dl class="glance">{cells}</dl></div>'


def section_open(b, cls="", tag="section"):
    sid = f' id="{esc(b["id"])}"' if b.get("id") else ""
    return f'<{tag} class="wrap prose{cls}"{sid}><h2>{esc(b["h"])}</h2>\n{paragraphs(b.get("p", []))}'


def sc_figure(fg, media, root):
    """One captioned picture (a photo, a loop, an inline line drawing or a click-to-play video), as beside a
    walkthrough's stages or under a section."""
    m = None if fg.get("svg") else media.get(fg["src"])
    cap = f'<figcaption>{esc(fg["caption"])}</figcaption>' if fg.get("caption") else ""
    if fg.get("caption_phone"):   # a shorter label on phones, where the step's own text sits right below
        cap = (f'<figcaption><span class="only-wide">{esc(fg["caption"])}</span>'
               f'<span class="only-phone">{esc(fg["caption_phone"])}</span></figcaption>')
    if fg.get("svg"):
        # a drawing in line work (assets/svg), inline so its lines take the page's text colour in light and dark
        img = (ROOT / "assets" / "svg" / fg["svg"]).read_text().strip()
    elif m["kind"] != "image":
        # a short loop (an old GIF): it plays silently in place, like the picture it stands in for
        img = (f'<video src="{root}{m["src"]}" poster="{root}{m["poster"]}" width="{m["w"]}" height="{m["h"]}" '
               f'muted loop playsinline autoplay preload="none" aria-label="{esc(fg.get("alt", ""))}"></video>')
    else:
        img = (f'<img src="{root}{m.get("sm", m["src"])}" width="{m["w"]}" height="{m["h"]}" '
               f'alt="{esc(fg.get("alt", ""))}" loading="lazy" decoding="async">')
    if fg.get("v"):
        # a video figure: it plays silently in place once on screen, and a click opens it in the lightbox
        item = {"type": video_kind(fg["v"]), "id": fg["v"], "vw": 16, "vh": 9, "thumb": root + m.get("sm", m["src"]),
                "w": m["w"], "h": m["h"], "title": fg.get("title", ""), "desc": fg.get("desc", "")}
        img = (f'<button class="sc-video" type="button" data-video="{item["type"]}:{fg["v"]}" data-vw="16" data-vh="9" '
               f'aria-label="Play video: {esc(fg.get("title", ""))}">{img}{PLAY_ICON}</button>'
               f'<script type="application/json" class="sc-video-data">{json_script(item)}</script>')
    return (f'<figure class="sc-photo{" sc-wire" if fg.get("svg") else ""}">{img}{cap}</figure>')


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
        parts = [sc_figure(fg, media, root) for fg in figs]
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
    # a set can also be a placement's screen recording ("video", with a still "poster"), which the 3D phone plays;
    # the flat phone shows its poster
    sets = [{"name": s_["name"], "src": root + s_["poster"], "next": root + s_["poster"], "video": f'{root}{s_["video"]}?v={asset_version(s_["video"])}', "sound": bool(s_.get("sound"))} if s_.get("video")
            else {"name": s_["name"], "src": root + media.get(s_["phone"])["src"], "next": root + media.get(s_["next"])["src"]}
            for s_ in b.get("sets", [])]
    # "phone3d": a still of the 3D phone for each placement (tools/make_phone_stills.cjs) stands in wherever the 3D
    # phone can't run (Reduce Motion, no WebGL); it replaces the drawn phone
    if b.get("phone3d"):
        for i, s_ in enumerate(b.get("sets", [])):
            sets[i]["still"] = f"{root}assets/phone/nike-{i}.webp?v={asset_version(f'assets/phone/nike-{i}.webp')}" if (ROOT / f"assets/phone/nike-{i}.webp").exists() else ""
    switch = ""
    if len(sets) > 1:
        on_cls = ' class="is-on"'
        btns = "".join(f'<button type="button" data-set="{i}"{on_cls if i == 0 else ""}>{esc(s_["name"])}</button>' for i, s_ in enumerate(sets))
        switch = (f'<div class="sc-switch" role="group" aria-label="Choose the placement shown">{btns}</div>'
                  f'<script type="application/json" class="sc-sets">{json_script(sets)}</script>')
    if b.get("phone3d"):
        first = sets[0].get("still", "") if sets else ""
        phone = (f'<figure class="ph ph-still" aria-hidden="true" data-cuts="{json_script(cuts)}">'
                 + (f'<img src="{first}" alt="" decoding="async">' if first else "") + '</figure>')
    else:
      phone = (f'<figure class="ph" aria-hidden="true"><div class="ph-body">'
               f'<div class="ph-screen"><div class="ph-roll">{"".join(layers)}{next_img}</div></div>'
               '<span class="ph-island"></span><span class="ph-key ph-key-action"></span><span class="ph-key ph-key-up"></span>'
               '<span class="ph-key ph-key-down"></span><span class="ph-key ph-key-side"></span>'
               '<span class="ph-halo"></span><span class="ph-glow"></span><span class="ph-copybox"></span>'
               '<span class="ph-stamp"><svg viewBox="0 0 48 48"><path d="M14 25l7 7 13-15"/></svg>QA approved</span>'
               '<span class="ph-chip">Scheduled for its publish window</span>'
               '<span class="ph-live">Live</span></div></figure>')
    # "phone3d": the phone in three.js (assets/js/nike-phone.js); where it can't run, the still above stands in.
    # three.js comes through an import map and loads only when the section nears.
    p3d = ""
    if b.get("phone3d"):
        p3d = ('<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.min.js"}}</script>'
               f'<script type="module" src="{root}assets/js/nike-phone.js?v={asset_version("assets/js/nike-phone.js")}"></script>')
    return (p3d + f'<section class="scene" id="{esc(b.get("id", "process"))}" data-scene="flow"{" data-phone3d" if b.get("phone3d") else ""} style="--n:{n}" aria-label="{esc(b["h"])}">'
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


def case_shine(slug, media):
    """The colours of a case's Read More on the home page (from its card photo), so a button pointing at that
    case wears the same shine."""
    for c in json.loads((CONTENT / "home.json").read_text())["cases"]:
        if c["slug"] == slug:
            bg = media.get(c["bg"], "bg")
            return ";".join(f"--s{k}:{col}" for k, col in enumerate(shine_colors(ROOT / bg["src"]), 1))
    return ""


def scene_credit(b):
    """The scene's "How I Made This" note: its button (the third control, after pause and start over) and the note,
    which opens at the bottom of the picture (post-journey.js also opens it at the end of the loop and when the
    reader scrolls to the bottom of the scene). Named tools in the text link to their sites."""
    c = b.get("credit")
    if not c:
        return "", ""
    text = esc(c["text"])
    for name, url in c.get("links", {}).items():
        text = text.replace(esc(name), f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)}</a>', 1)
    button = (f'<button class="pj-btn pj-credit-btn" type="button" aria-label="{esc(c["title"])}" aria-expanded="false" '
              f'aria-controls="pj-credits"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="6.8" r="1.5"/>'
              f'<path d="M12 11v7.5"/></svg></button>')
    return button, (f'<aside class="pj-credits" id="pj-credits" aria-label="{esc(c["title"])}">'
            f'<button class="pj-credits-close" type="button" aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="M7 7l10 10M17 7L7 17"/></svg></button>'
            f'<p class="pj-credits-title">{esc(c["title"])}</p><p>{text}</p></aside>')


def scene(b, root):
    """An animated three.js scene under a section (assets/js/<scene>.js), with its subtitles over the picture
    and its controls (pause, start over, How I Made This). The script loads three.js only when the scene nears the screen. Screen readers get
    the description instead of the moving subtitles."""
    name = b["scene"]
    credit_btn, credit = scene_credit(b)
    return (f'<script src="{root}assets/js/{name}.js?v={asset_version(f"assets/js/{name}.js")}" defer></script>'
            f'<div class="pj-pin"><figure class="pj">'
            f'<div class="pj-stage" data-earth="{root}assets/scenes/earth-night.jpg">'
            f'<canvas aria-hidden="true"></canvas>'
            f'<div class="pj-caption" aria-hidden="true"><span class="pj-line"></span>'
            f'<span class="pj-kicker">{esc(b["kicker"])}</span></div>'
            f'<div class="pj-dock"><div class="pj-drawer">'
            f'<button class="pj-tab" type="button" aria-label="Show controls" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="M14.5 5.5L8.5 12l6 6.5"/></svg></button>'
            f'<div class="pj-controls">'
            f'<button class="pj-btn pj-toggle" type="button" aria-label="Pause animation"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path class="i-pause" d="M9 6v12M15 6v12"/><path class="i-play" d="M8 5.5v13l11-6.5z"/></svg></button>'
            f'<button class="pj-btn pj-restart" type="button" aria-label="Start over"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4v4h4"/></svg></button>{credit_btn}</div></div></div>{credit}</div>'
            f'<figcaption class="sr-only">{esc(b["alt"])}</figcaption></figure></div>')


# ---------- the AI page's demos (content/ai.json, assets/js/ai-page.js) ----------
# Each demo is drawn here in its finished state, so it reads without script and with Reduce Motion on;
# ai-page.js then plays it while it is on screen. Its data rides along as JSON for the script.

AI_SOUND = ('<button class="ai-btn ai-sound" type="button" aria-pressed="false" aria-label="Turn sound on">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><mask id="ai-snd-cut"><rect width="24" height="24" fill="#fff"/>'
            '<path d="M3.5 20.5 20.5 3.5" stroke="#000" stroke-width="5"/></mask></defs>'   # muted: the speaker and its waves, struck through
            '<g class="i-off"><g mask="url(#ai-snd-cut)"><path class="i-spk" d="M3 9.5h3.5L11 5.5v13l-4.5-4H3z"/>'
            '<path d="M14.5 9a4 4 0 0 1 0 6M17 6.5a7.5 7.5 0 0 1 0 11"/></g><path d="M3.5 20.5 20.5 3.5"/></g>'
            '<g class="i-on"><path class="i-spk" d="M3 9.5h3.5L11 5.5v13l-4.5-4H3z"/><path d="M14.5 9a4 4 0 0 1 0 6M17 6.5a7.5 7.5 0 0 1 0 11"/></g></svg></button>')
AI_PAUSE = ('<button class="ai-btn ai-toggle" type="button" aria-label="Pause animation"><svg viewBox="0 0 24 24" aria-hidden="true">'
            '<path class="i-pause" d="M9 6v12M15 6v12"/><path class="i-play" d="M8 5.5v13l11-6.5z"/></svg></button>')
AI_SPARK = ('<svg class="ai-spark" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7'
            '-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7Z"/></svg>')


def ai_window(title, inner, cls=""):
    return (f'<div class="ai-window{cls}"><div class="ai-bar" aria-hidden="true"><span class="ai-dots"><i></i><i></i><i></i></span>'
            f'<span class="ai-title">{esc(title)}</span></div>{inner}</div>')


def front_switch(first):
    """The switch for which of a demo's two windows is in front: automatic, then the first one locked in front, then
    the other, then automatic again (ai-page.js keeps its label and state)."""
    return (f'<button class="ai-front" type="button" data-mode="auto" aria-label="Window in front: automatic. Press to keep {esc(first)} in front">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="8" width="13" height="11" rx="2"/><path d="M8 8V6a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>'
            '<span>Auto</span></button>')


def ai_figure(b, label, inner, pause=True):
    data = {k: v for k, v in b.items() if k not in ("h", "p", "id", "note", "link", "demo")}
    note = f'<figcaption class="ai-note">{esc(b["note"])}</figcaption>' if b.get("note") else ""
    nav = '<nav class="hb-chapters"'
    if note and nav in inner:   # a demo told in steps: its caption sits right under the window, like a tutorial
        inner = inner.replace(nav, f'<p class="ai-note ai-live">{esc(b["note"])}</p>{nav}', 1)
        note = ""
    return (f'<figure class="wrap ai-demo ai-{b["demo"]}" data-demo="{b["demo"]}" aria-label="{esc(label)}">'
            f'<script type="application/json" class="ai-data">{json_script(data)}</script>'
            f'<div class="ai-stage">{inner}{AI_PAUSE if pause else ""}</div>{note}</figure>')


HB_ICONS = {   # line icons for the Hub copy, drawn on a 24 grid
    "swap": "M7 4 3 8l4 4M3 8h14M17 12l4 4-4 4M21 16H7",
    "play": "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    "board": "M6 7h12v13H6zM9 4h12v13",
    "cup": "M7 4h10v5a5 5 0 0 1-10 0zM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3M12 14v4M8 20h8",
    "badge": "M12 3l2.5 2 3.2-.2.6 3.1 2.6 1.9-1.4 2.9 1 3.1-2.9 1.3-1.1 3-3.2-.5L12 21l-2.4-2.1-3.2.5-1.1-3-2.9-1.3 1-3.1L2 9.8l2.6-1.9.6-3.1 3.2.2zM8.5 12l2.5 2.5 4.5-5",
    "people": "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 21 21M8 9a2.5 2.5 0 1 0 5 0 2.5 2.5 0 0 0-5 0M6.5 15c1-2 7-2 8 0",
    "cal": "M4 6h16v14H4zM4 10h16M8 3v5M16 3v5",
    "admin": "M14 6a4 4 0 0 0 5 5l-9 9a2 2 0 0 1-3-3zM5 3 3 5l3 3 2-2z",
    "trend": "M3 17l6-6 4 4 8-8M15 7h6v6",
    "filter": "M4 5h16l-6 7v6l-4 2v-8z",
    "sliders": "M6 4v16M12 4v16M18 4v16M4 9h4M10 15h4M16 7h4",
    "search": "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 21 21",
    "edit": "M4 20h4L19 9l-4-4L4 16zM4 4h8M4 4v8",
    "doc": "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6",
    "adduser": "M9 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM2 20c1-4 13-4 14 0M19 8v6M16 11h6",
    "bell": "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20h4",
    "help": "M9 9a3 3 0 1 1 4 2.8c-.7.3-1 1-1 1.7V15M12 18v.5",
    "like": "M7 10v10H4V10zM7 10l4-7c2 0 2.5 1.5 2 3l-1 4h6a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 16.8 20H7",
    "star": "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
    "share": "M14 4h6v6M20 4l-8 8M18 14v6H4V6h6",
    "plus": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM12 8v8M8 12h8",
    "chev": "M6 9l6 6 6-6",
    "close": "M5 5l14 14M19 5 5 19",
    "addimg": "M4 6h11M4 6v14h16v-9M8 16l3-4 3 3 2-2 4 3M18 3v6M15 6h6",
    "translate": "M3 5h10M8 3v2M5 5c1 4 4 7 7 8M11 5c-1 4-4 7-7 8M13 21l4-10 4 10M14.5 18h5",
}


def hb_icon(name, cls="hb-i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="{HB_ICONS[name]}"/></svg>'


def demo_localize(b, root):
    """The localization agent inside a copy of the real Champions Hub (from Christian's screen recording, drawn
    at its 1280 by 708 desktop size and scaled to fit): the Trending Posts feed, and the LinkedIn Share window
    whose Translate link opens the agent's regions. Drawn on the Korean version after a Champion's review."""
    img = lambda n: f"{root}assets/ai/hub/{n}.jpg"
    ko = next(r for r in b["regions"] if r.get("review"))
    before, old, new, after = re.match(r"(.*)\[(.*)\|(.*)\](.*)", ko["text"]).groups()
    # each menu item, with the shorter title the phone's tab bar uses
    rail = "".join(f'<li class="hb-nav{c}">{hb_icon(i)}<span class="hb-d">{t}</span><span class="hb-m">{m}</span>{s}</li>' for i, t, m, c, s in (
        ("play", "Play", "Play", " is-on", ""), ("board", "Leaderboards", "Leaderboards", "", ""),
        ("cup", "May Challeng\u2026", "Challenge", " is-challenge", "<small>It\u2019s time to get sta\u2026</small>"),
        ("badge", "My badges", "My Badges", "", ""), ("people", "People directory", "Directory", "", ""), ("cal", "Calendar", "Calendar", "", ""),
        ("admin", "Admin", "Admin", "", "")))
    tools = "".join(f'<span class="hb-round">{hb_icon(i)}</span>' for i in ("edit", "adduser", "bell", "help"))
    tick = '<span class="hb-tick"></span>'

    def card(c, i):
        if c.get("post"):
            thumb = guide(b["art"])
        else:
            thumb = (f'<span class="hb-blur" style="background-image:url({img(c["img"])})"></span>'
                     f'<img src="{img(c["img"])}" alt="" loading="lazy">' + ('<span class="hb-playbtn"></span>' if c.get("video") else ""))
        if c.get("count"):
            thumb += f'<span class="hb-count">{esc(c["count"])}</span><span class="hb-arr is-l"></span><span class="hb-arr is-r"></span>'
        acts = (f'<div class="hb-acts">{hb_icon("like")}<b>{c.get("likes", 4)}</b>{hb_icon("star")}'
                f'<span class="hb-share">{hb_icon("share")}</span><span class="hb-more">\u2026</span></div>')
        body = f'<p class="hb-body">{esc(c["body"])}</p>' if c.get("body") else ""
        cls = (" is-tall" if c.get("tall") else "") + (" is-post" if c.get("post") else "")
        return (f'<article class="hb-card{cls}" data-i="{i}"><div class="hb-thumb">{thumb}'
                f'<span class="hb-tag">{esc(c["tag"])}</span>{hb_icon("plus", "hb-i hb-plus")}</div>'
                f'<p class="hb-src"><span class="hb-src-i">{hb_icon("share")}</span><span class="hb-src-v">{esc(c.get("src", "Content for Sharing"))}</span>'
                f'{tick}<span class="hb-when">{esc(c.get("when", "3 days ago"))}</span></p>'
                f'<h4>{esc(c["title"])}</h4>{body}{acts}<span class="hb-sweep"></span></article>')

    # the post's graphic, in the style of Cohesity's own: a visual on top under the wordmark, a condensed
    # headline whose last line is pink, and a green button; its words change with the region
    art_img = f'<img class="hb-guide-art" src="{img("guide-photo")}" alt="" loading="lazy">'   # cut from a Cohesity webinar post he designed

    def guide(art):
        return (f'<span class="hb-guide">{art_img}<span class="hb-guide-logo"><img src="{root}assets/ai/hub/cohesity-wordmark.png" alt=""></span>'
                f'<b>{esc(art[0])}</b><b>{esc(art[1])}</b><b class="is-pink">{esc(art[2])}</b><span class="hb-guide-btn">{esc(art[3])}</span></span>')

    cards = "".join(card(c, i) for i, c in enumerate(b["feed"]))
    activity = "".join(
        f'<li><span class="hb-face"></span><p><b>{n} Champions</b> shared</p>'
        f'<span class="hb-ua-pic"><img src="{img("ua" + str(i + 1))}" alt="" loading="lazy"></span></li>'
        for i, n in enumerate((12, 24, 14, 26)))
    langs = "".join(f'<li data-code="{esc(r["code"])}"{" class=is-on" if r is ko else ""}><b>{esc(r["code"])}</b>{esc(r["name"])}</li>'
                    for r in b["regions"])
    srcs = " · ".join(esc(s) for s in b["sources"])
    hub = f'''
<div class="hb-view"><div class="hb is-open is-lang is-review" lang="en" aria-hidden="true">
  <nav class="hb-rail">
    <span class="hb-logo" style="-webkit-mask-image:url({root}assets/ai/hub/cohesity-s.png);mask-image:url({root}assets/ai/hub/cohesity-s.png)"></span>
    {hb_icon("swap", "hb-i hb-swap")}
    <span class="hb-me"><img src="{img("me")}" alt=""><span>My account</span></span>
    <ul>{rail}</ul>
  </nav>
  <header class="hb-top">
    <span class="hb-tile">{hb_icon("trend")}</span>
    <div><p class="hb-h">Trending Posts{hb_icon("chev")}{hb_icon("filter")}{hb_icon("sliders")}</p>
      <p class="hb-sub">Find all the content with the highest activity over the last 7 days.</p></div>
    <span class="hb-auto">{hb_icon("translate")}Localize Every Post<span class="hb-state"><span class="is-off">Off</span><span class="is-on">{esc(b["auto"]["name"])}</span></span></span>
    <span class="hb-search">{hb_icon("search")}Search</span>{tools}
  </header>
  <div class="hb-feed">{cards}</div>
  <aside class="hb-ua"><p class="hb-ua-h">User Activity<span>»</span></p><ul>{activity}</ul></aside>
  <div class="hb-dim"></div>
  <div class="hb-modal">
    <p class="hb-mh"><span class="hb-in">in</span>Share{hb_icon("close", "hb-i hb-x")}</p>
    <div class="hb-mb">
      <p class="hb-row"><span>My Comment</span>
        <span class="hb-lang"><span class="hb-lang-v">{esc(ko["name"])}</span> · Tone: <span class="hb-tone">{esc(ko["tone"])}</span></span>
        <span class="hb-tr">{hb_icon("translate")}Translate</span></p>
      <div class="hb-menu">
        <p class="hb-menu-h">{AI_SPARK}<span>Localize with the Brand Agent<small>{srcs}</small></span></p>
        <ul>{langs}<li class="hb-menu-more">+ More Regions</li></ul>
      </div>
      <div class="hb-text">
        <p class="hb-t" lang="ko">{esc(before)}<del>{esc(old)}</del> <ins>{esc(new)}</ins>{esc(after)}</p>
        <p class="hb-hash">{esc(ko["tags"])}</p>
        <p class="hb-busy">{AI_SPARK}<span class="hb-busy-v">Localizing</span></p>
        <p class="hb-review"><span class="hb-ca">CA</span><span><b>Champion Advocate</b> <span class="hb-review-v">{esc(ko["review"])}</span></span></p>
      </div>
      <p class="hb-tags">Click on a tag to add it to your post: <span>@Cohesity</span> <span>#Cohesity</span></p>
      <p class="hb-photos-h">You Can Select Photos</p>
      <div class="hb-photos"><span class="hb-photo">{guide(ko["art"])}<i>1</i></span><span class="hb-addimg">{hb_icon("addimg")}</span></div>
      <div class="hb-btns"><span class="hb-learned">{AI_SPARK}<span class="hb-count-v">1</span> <span class="hb-unit">fix</span> learned</span>
        <span class="hb-b is-brown">Schedule</span><span class="hb-b is-brown">Share next</span><span class="hb-b is-blue">Share now</span></div>
    </div>
  </div>
  <div class="hb-preview"><p class="hb-preview-h">Photo \u00b7 <span class="hb-preview-v">{esc(ko["name"])}</span>{hb_icon("close", "hb-i hb-x")}</p>{guide(ko["art"])}</div>
  <p class="hb-toast">Shared on LinkedIn</p>
  <svg class="hb-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg>
</div></div>'''
    chapters = "".join(f'<button type="button" style="--p:0"><span class="hb-fill"></span><span class="hb-ch-t">{esc(c)}</span></button>'
                       for c in b["chapters"])
    views = "".join(f'<button type="button" data-view="{v.lower()}" aria-pressed="{str(i == 0).lower()}">{esc(v)}</button>'
                    for i, v in enumerate(b["views"]))
    inner = (f'<div class="hb-views" role="group" aria-label="Show the Hub on">{views}</div>'
             + ai_window("Champions Hub  ·  Trending Posts", hub, " hb-window")
             + f'<nav class="hb-chapters" aria-label="Skip to a part of the demo">{chapters}</nav>')
    return ai_figure(b, "Illustration: the localization agent in a copy of the Champions Hub", inner)


MB_LOGO = '<span class="mb-logo"><i></i><i></i><i></i></span>'
CLAUDE_MARK = ('<svg class="zp-claude" viewBox="0 0 24 24" aria-hidden="true">'
               + "".join(f'<path d="M12 12 12 3.2" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 30)) + "</svg>")
ZAP_MARK = ('<svg class="zp-mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4"/></svg>')


def demo_board(b, root):
    """The editorial calendar in a copy of Monday.com work management, and the Zapier workflow behind its Generate
    button (each drawn at 1200 by 640 and scaled to fit; a phone gets narrower mobile layouts). Clicking Generate
    slides the board away to the zap: Monday's button starts it, Claude writes with instructions built from the
    do's and don'ts, and the result goes back into the board."""
    ico = lambda n: hb_icon(n, "hb-i mb-i")
    last = len(b["statuses"]) - 1
    me = f'<img class="mb-face" src="{root}assets/ai/hub/me.jpg" alt="">'
    head = ("<span></span><span>Item</span><span>Person</span><span>Status</span><span>Channel</span><span>Date</span>"
            f'<span>AI Output</span><span>Generate</span>')
    rows = "".join(
        f'<div class="mb-row" data-i="{i}"><span class="mb-check"></span><span class="mb-item">{esc(r["item"])}</span>'
        f'<span class="mb-person">{me}</span>'
        f'<span class="mb-status s{min(i + 1, last)}">{esc(b["statuses"][min(i + 1, last)])}</span>'
        f'<span class="mb-dim">{esc(r["channel"])}</span><span class="mb-dim">{esc(r["date"])}</span>'
        f'<span class="mb-ai is-on"><span class="mb-ai-v">{esc(r["ai"])}</span></span>'
        f'<span class="mb-gen"><span class="mb-btn">{AI_SPARK}Generate</span></span></div>' for i, r in enumerate(b["rows"]))
    held = [min(i + 1, last) for i in range(len(b["rows"]))]
    battery = "".join(f'<i class="s{k}" style="--n:{held.count(k) * 5 / len(held)}"></i>' for k in range(len(b["statuses"])))
    side = "".join(f'<li class="mb-nav{c}">{ico("board")}<span>{esc(t)}</span></li>' for t, c in (
        ("Editorial Calendar", " is-on"), ("Content Briefs", ""), ("Campaigns", "")))
    monday = f'''
  <div class="mb-pane">
    <header class="mb-top">{MB_LOGO}<b>monday</b><span class="mb-product">work management</span>
      <span class="mb-top-r">{ico("bell")}{ico("search")}{ico("help")}{me}</span></header>
    <nav class="mb-side">
      <p class="mb-side-row">{ico("play")}Home</p>
      <p class="mb-side-row">{ico("cal")}My work</p>
      <p class="mb-ws"><span class="mb-ws-i">M</span>Marketing{ico("chev")}</p>
      <ul>{side}</ul>
    </nav>
    <main class="mb-main">
      <div class="mb-title"><h4>Editorial Calendar</h4>{ico("chev")}
        <span class="mb-title-r"><span class="mb-ghost">Integrate</span><span class="mb-ghost">Automate</span><span class="mb-invite">Invite / 1</span></span></div>
      <div class="mb-tabs"><span class="is-on">Main table</span><span>Calendar</span><span class="mb-plus">+</span></div>
      <div class="mb-tools"><span class="mb-new">New item<i></i></span>
        <span>{ico("search")}Search</span><span>{ico("people")}Person</span><span>{ico("filter")}Filter</span><span>{ico("sliders")}Sort</span></div>
      <p class="mb-group">{ico("chev")}This week<small>{len(b["rows"])} items</small></p>
      <div class="mb-table">
        <div class="mb-row mb-head">{head}</div>{rows}
        <div class="mb-row mb-add"><span class="mb-check"></span><span>+ Add item</span></div>
        <div class="mb-row mb-sum"><span></span><span></span><span></span><span class="mb-battery">{battery}</span></div>
      </div>
      <p class="mb-group is-next">{ico("chev")}Next week<small>4 items</small></p>
    </main>
    <p class="mb-toast">{ZAP_MARK}Zap ran: {esc(b["zap"]["name"])}</p>
  </div>'''

    z = b["zap"]
    def step(n, mark, kind, title, sub, cls=""):
        return (f'<div class="zp-step{cls}" data-n="{n}"><span class="zp-app">{mark}</span>'
                f'<span class="zp-step-t"><small>{kind}</small><b>{n}. {esc(title)}</b><em>{esc(sub)}</em></span>'
                f'<span class="zp-state"></span></div>')
    mday = f'<span class="zp-mday">{MB_LOGO}</span>'
    steps = (step(1, mday, "Trigger", "Button Clicked in monday.com", "Editorial Calendar · Generate column")
             + '<span class="zp-link"><i>+</i></span>'
             + step(2, CLAUDE_MARK, "Action", "Send Message in Claude", "Instructions from our knowledge base", " is-sel")
             + '<span class="zp-link"><i>+</i></span>'
             + step(3, mday, "Action", "Update Item in monday.com", "AI Output, then Status to Brief"))
    li = lambda xs, mark: "".join(f"<li><b>{mark}</b>{esc(x)}</li>" for x in xs)
    pill = lambda t: f'<span class="zp-pill">{mday}{esc(t)}</span>'
    msg = " ".join(pill(t) if i % 2 else esc(t) for i, t in enumerate(z["message"]))
    zapier = f'''
  <div class="zp-pane">
    <header class="zp-top"><span class="zp-logo"><i></i>zapier</span><span class="zp-name">{esc(z["name"])}{ico("edit")}</span>
      <span class="zp-top-r"><span class="zp-saved">Saved</span><span class="zp-pub">Publish</span></span></header>
    <nav class="zp-rail">{ico("play")}{ico("sliders")}{ico("cal")}{ico("help")}</nav>
    <div class="zp-canvas">
      <div class="zp-steps">{steps}</div>
      <aside class="zp-panel">
        <p class="zp-ph">{CLAUDE_MARK}<b>2. Send Message</b><span>Claude</span></p>
        <p class="zp-tabs"><span>Setup</span><span class="is-on">Configure</span><span>Test</span></p>
        <div class="zp-fields">
          <p class="zp-label">Model</p><p class="zp-input">{esc(z["model"])}{ico("chev")}</p>
          <p class="zp-label">Instructions</p>
          <div class="zp-area"><p>{esc(z["intro"])}</p><ul>{li(b["dos"], "+")}</ul></div>
          <p class="zp-label">Knowledge base</p>
          <p class="zp-files">{"".join(f'<span class="zp-file">{ico("doc")}{esc(f)}</span>' for f in z["files"])}<span class="zp-upload">+ Upload</span></p>
          <p class="zp-label">User Message</p><p class="zp-input zp-msg">{msg}</p>
        </div>
        <p class="zp-out"><span class="zp-out-busy">Claude is writing…</span><span class="zp-out-v"></span></p>
      </aside>
    </div>
  </div>'''
    canvas = (f'<div class="mb-view"><div class="mb" lang="en" aria-hidden="true"><div class="mb-track">{monday}{zapier}</div>'
              f'<svg class="mb-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg></div></div>')
    chapters = "".join(f'<button type="button" style="--p:0"><span class="hb-fill"></span><span class="hb-ch-t">{esc(c)}</span></button>'
                       for c in b["chapters"])
    # the window's bar holds a browser tab for each app; the one on screen is the open tab
    tabs = (f'<span class="mbt is-mb">{MB_LOGO}monday.com \u00b7 Editorial Calendar</span>'
            f'<span class="mbt is-zp"><i class="mbt-z"></i>Zapier \u00b7 {esc(b["zap"]["name"])}</span>')
    window = (f'<div class="ai-window mb-window"><div class="ai-bar mb-bar" aria-hidden="true"><span class="ai-dots"><i></i><i></i><i></i></span>'
              f'<span class="mbt-row">{tabs}</span></div>{canvas}</div>')
    inner = (window + front_switch("monday.com")
             + f'<nav class="hb-chapters" aria-label="Skip to a part of the demo">{chapters}</nav>')
    return ai_figure(b, "Illustration: an editorial calendar in Monday.com whose Generate button runs a Zapier workflow with Claude", inner)


def tc(sec, fps=30):
    """Seconds as Premiere's timecode, HH:MM:SS:FF."""
    f = int(round(sec * fps))
    return f"{f // (3600 * fps):02d}:{f // (60 * fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"


def demo_cut(b, root):
    """The Mars Men PSA in a copy of Adobe Premiere Pro (drawn at 1280 by 800 and scaled to fit; a phone gets a
    narrower layout): the transcript of every take in the Text panel with the cut lines struck, the vertical video
    in the Program monitor, the six takes in the Project panel, and the 43-second cut on the timeline, whose
    playhead, timecode and highlighted line follow the video."""
    ico = lambda n: hb_icon(n, "hb-i pr-i")
    hues = {t["id"]: i for i, t in enumerate(b["takes"])}
    dur = b["duration"]

    def line(l):
        at = f' data-at="{l["at"][0]}" data-to="{l["at"][1]}"' if l.get("at") else ""
        return f'<span class="ct-line{"" if l["keep"] else " is-cut"}"{at}>{esc(l["t"])}</span>'

    clock = 0.0
    blocks = []
    for t in b["takes"]:
        blocks.append(f'<li class="pr-block"><span class="pr-who">••• {esc(t["id"])}</span>'
                      f'<span class="pr-tc">{tc(clock)} - {tc(clock + t["len"])}</span><p>'
                      + " ".join(line(l) for l in t["lines"])
                      + ('<span class="ct-pick">The hook</span>' if t["id"] == "Hook 1" else "") + "</p></li>")
        clock += t["len"]
    raw_total = clock
    takes = "".join(f'<li class="pr-file"><i class="pr-chip h{hues[t["id"]]}"></i><span class="pr-fico"></span>{esc(t["id"])}.MOV'
                    f'<em>{tc(t["len"])[3:]}</em></li>' for t in b["takes"])
    bins = "".join(f'<li class="pr-bin"><i></i>{ico("chev")}<span class="pr-folder"></span>{n}</li>'
                   for n in ("001 SEQUENCES", "002 RAW TAKES", "003 CAPTIONS", "004 MUSIC"))
    ticks = "".join(f'<span style="left:{s / dur * 100:.3f}%">{tc(s)}</span>' for s in range(0, int(dur) + 1, 10))
    clips = "".join(f'<span class="pr-clip ct-clip h{hues[s["take"]]}" style="left:{s["from"] / dur * 100:.3f}%;width:{(s["to"] - s["from"]) / dur * 100:.3f}%">'
                    f'<b>{esc(s["take"])}.MOV</b></span>' for s in b["final"])
    broll = "".join(f'<span class="pr-clip pr-bclip" style="left:{c["from"] / dur * 100:.3f}%;width:{(c["to"] - c["from"]) / dur * 100:.3f}%">'
                    f'<b>{esc(c["name"])}</b></span>' for c in b.get("broll", []))
    audio = "".join(f'<span class="pr-clip pr-aclip ct-clip" style="left:{s["from"] / dur * 100:.3f}%;width:{(s["to"] - s["from"]) / dur * 100:.3f}%"></span>'
                    for s in b["final"])
    caps = "".join(f'<span class="pr-cap" style="left:{l["at"][0] / dur * 100:.3f}%;width:{(l["at"][1] - l["at"][0]) / dur * 100:.3f}%">{esc(l["t"])}</span>'
                   for t in b["takes"] for l in t["lines"] if l.get("at"))
    track = lambda name, inner, cls="": (f'<div class="pr-track{cls}"><span class="pr-th"><b>{name}</b>{ico("bell") if False else ""}'
                                          f'<i class="pr-lock"></i></span><div class="pr-lane">{inner}</div></div>')
    tools = "".join(ico(n) for n in ("play", "sliders", "search", "edit", "people"))
    # the chat with ChatGPT, in its own window over Premiere's corner (he worked it out with ChatGPT before opening
    # Premiere): his timestamped transcript and ChatGPT's cuts, then the B-roll search; each message shows from the
    # chapter it belongs to
    def msg(m):
        extra = ""
        if m.get("file"):
            extra += f'<span class="cl-file"><i></i>{esc(m["file"])}</span>'
        if m.get("cuts"):
            extra += "<ul>" + "".join(f'<li><b class="cl-at">{esc(c["at"])}</b> {esc(c["t"])}</li>' for c in m["cuts"]) + "</ul>"
        if m.get("links"):
            extra += '<ul class="cl-links">' + "".join(f"<li><span>pexels.com</span>{esc(c)}</li>" for c in m["links"]) + "</ul>"
        return (f'<li class="cl-msg is-{m["who"]}" data-ch="{m["ch"]}">'
                + f'<div><p>{esc(m["text"])}</p>{extra}</div></li>')
    chat = "".join(msg(m) for m in b["chat"])
    src = f'{root}assets/ai/marsmen.mp4?v={asset_version("assets/ai/marsmen.mp4")}'
    canvas = f'''
<div class="pr-view"><div class="pr" lang="en">
  <header class="pr-top" aria-hidden="true"><span class="pr-dots"><i></i><i></i><i></i></span>{ico("play")}
    <span class="pr-ws">Import</span><span class="pr-ws is-on">Edit</span><span class="pr-ws">Export</span>
    <span class="pr-name">MarsMen_PSA - Edited</span></header>
  <section class="pr-panel pr-text" aria-label="Transcript of the six takes">
    <p class="pr-ph" aria-hidden="true">Text<i class="pr-menu"></i></p>
    <p class="pr-tabs" aria-hidden="true"><span class="is-on">Transcript</span><span>Captions</span><span>Graphics</span><em>MarsMen_Takes</em></p>
    <p class="pr-search" aria-hidden="true"><span>{ico("search")}Search</span>{ico("filter")}{ico("sliders")}{ico("edit")}</p>
    <ol class="ct-script pr-script">{"".join(blocks)}</ol>
  </section>
  <section class="pr-panel pr-mon">
    <p class="pr-ptabs" aria-hidden="true"><span>Source: Body 1.MOV</span><span class="is-on">Program: Mars Men PSA<i class="pr-menu"></i></span></p>
    <div class="pr-screen"><video class="ct-video pr-video" src="{src}" poster="{root}assets/ai/marsmen.jpg" muted loop playsinline preload="metadata"
      aria-label="Mars Men PSA, the finished cut, muted with captions"></video></div>
    <p class="pr-mbar" aria-hidden="true"><b class="pr-tc-now">{tc(0)}</b><span class="pr-sel">Fit{ico("chev")}</span>
      <span class="pr-sel">Full{ico("chev")}</span><em>{tc(dur)}</em></p>
    <p class="pr-scrub" aria-hidden="true"><i class="pr-scrub-head"></i></p>
    <p class="pr-transport" aria-hidden="true"><i class="t-mark"></i><i class="t-in"></i><i class="t-out"></i><i class="t-back"></i><i class="t-play"></i><i class="t-fwd"></i><i class="t-lift"></i><i class="t-cam"></i></p>
  </section>
  <section class="pr-panel pr-proj" aria-hidden="true">
    <p class="pr-ptabs"><span>Markers</span><span class="is-on">Project: MarsMen_PSA<i class="pr-menu"></i></span></p>
    <p class="pr-path"><span class="pr-folder"></span>MarsMen_PSA.prproj</p>
    <p class="pr-psearch">{ico("search")}<em>1 of 10 items</em></p>
    <p class="pr-cols"><span>Name</span><span>Media Duration</span></p>
    <ul>{bins}{takes}</ul>
    <p class="pr-foot">6 takes · {int(raw_total // 60)}:{int(raw_total % 60):02d} of footage</p>
  </section>
  <section class="pr-panel pr-tl" aria-hidden="true">
    <nav class="pr-tools">{tools}</nav>
    <div class="pr-seq">
      <p class="pr-stab">× Mars Men PSA<i class="pr-menu"></i></p>
      <p class="pr-shead"><b class="pr-tc-now">{tc(0)}</b><span class="pr-ruler">{ticks}</span></p>
      <div class="pr-tracks">
        {track("C1", caps, " is-cap")}
        {track("V2", broll, " is-v2")}
        {track("V1", clips, " is-v1")}
        {track("A1", audio, " is-a1")}
        {track("A2", "")}
        <span class="pr-head ct-head"></span>
      </div>
    </div>
    <div class="pr-meter"><i></i><i></i></div>
  </section>
</div></div>'''
    # sound: the video starts muted (browsers only play sound after a click); this turns his voice on
    sound = AI_SOUND
    chapters = "".join(f'<button type="button" style="--p:0" data-from="{c["from"]}" data-to="{c["to"]}"><span class="hb-fill"></span>'
                       f'<span class="hb-ch-t">{esc(c["label"])}</span></button>' for c in b["chapters"])
    gpt = (f'<div class="ai-window cl-window" aria-label="The chat with ChatGPT about the cut"><div class="cl-app" lang="en">'
           f'<div class="ai-bar cl-bar" aria-hidden="true"><span class="ai-dots"><i></i><i></i><i></i></span>'
           f'<span class="ai-title">ChatGPT</span></div>'
           f'<p class="cl-head" aria-hidden="true">ChatGPT{ico("chev")}</p>'
           f'<ol class="cl-chat">{chat}</ol>'
           f'<p class="cl-input" aria-hidden="true"><b>+</b>Ask anything<i></i></p></div></div>')
    # which window is in front: on its own, ChatGPT comes forward in the chapters it was used in; each press of this
    # button moves on, from automatic to ChatGPT locked in front, Premiere locked in front, and back to automatic
    front = front_switch("ChatGPT")
    inner = (f'<div class="pr-stage">{ai_window("Adobe Premiere Pro  ·  Mars Men PSA", canvas, " pr-window")}{gpt}</div>' + sound + front
             + f'<nav class="hb-chapters" aria-label="Skip to a part of the video">{chapters}</nav>')
    return ai_figure(b, "The Mars Men PSA in Premiere Pro: its transcript, the vertical cut and the timeline", inner)


def demo_fan(b, root):
    """One podcast episode (its real waveform) with five moments marked, and the five real pieces cut from them: a
    square clip and a vertical one with captions, a quote card, a newsletter blurb and a blog outline. Each card
    shows its piece small; a click opens it large (the clips with sound)."""
    ep = b["episode"]
    mm = lambda s: f"{s // 60}:{s % 60:02d}"
    src = lambda path: f'{root}{path}?v={asset_version(path)}'
    marks = "".join(f'<span class="fn-mark" style="left:{o["at"] / ep["length"] * 100:.2f}%"><button type="button" data-i="{i}" '
                    f'aria-label="Open the {esc(o["kind"])}, {mm(o["at"])} in the episode">{i + 1}</button></span>'
                    for i, o in enumerate(b["outputs"]))
    cards, opens = [], []
    for i, o in enumerate(b["outputs"]):
        label = f'{esc(o["kind"])}: {esc(o.get("topic") or o.get("quote", ""))}'
        if o.get("video"):
            art = (f'<video class="fn-video" src="{src(o["video"])}" poster="{src(o["poster"])}" muted loop playsinline preload="none" '
                   f'aria-hidden="true"></video>')
            big = (f'<video class="fn-big-video" src="{src(o["video"])}" poster="{src(o["poster"])}" controls playsinline preload="none" '
                   f'aria-label="{label}"></video>')
        elif o.get("quote"):
            img = f'<img src="{src(o["image"])}" alt="Quote card: \u201c{esc(o["quote"])}\u201d {esc(o["by"])}, Resilience Universe" loading="lazy">'
            art, big = img, img
        elif o.get("outline"):
            body = (f'<span class="fn-doc-t">{esc(o["topic"])}</span>'
                    f'<span class="fn-outline">{"".join(f"<span>{k + 1}. {esc(x)}</span>" for k, x in enumerate(o["outline"]))}</span>')
            hero = f'<img class="fn-hero" src="{src(o["image"])}" alt="" loading="lazy">' if o.get("image") else ""   # the episode's art heads the post
            art, big = hero + body, f'<div class="fn-big-doc">{hero}{body}</div>'
        else:
            # the top of a LinkedIn newsletter issue, like Security Spotlight: its bar, the green header, the title,
            # who posted it, and the intro paragraph, cut off where the reader would click through
            top = (f'<span class="li-nl-bar"><img class="li-nl-s" src="{src("assets/ai/hub/cohesity-s.png")}" alt="">'
                   f'<span class="li-nl-n"><b>{esc(o["newsletter"])}</b><small>Newsletter</small></span><span class="li-nl-sub">+ Subscribe</span></span>'
                   f'<img class="li-nl-hero" src="{src(o["image"])}" alt="{esc(o["topic"])}" loading="lazy">'
                   f'<span class="li-nl-t">{esc(o["topic"])}</span>'
                   f'<span class="li-nl-by"><img class="li-nl-s" src="{src("assets/ai/hub/cohesity-s.png")}" alt=""><b>Cohesity</b></span>'
                   f'<span class="li-nl-p">{esc(o["blurb"])}</span>')
            art = f'<span class="li-nl">{top}</span>'
            big = (f'<div class="li-nl is-big">{top}<a class="fn-link" href="{esc(ep["href"])}" target="_blank" rel="noopener">'
                   f'Listen to the Episode</a></div>')
        cards.append(f'<li class="fn-card fn-{esc(o["shape"].replace(":", "x"))}"><button class="fn-open" type="button" aria-label="Open the {label}">'
                     f'<span class="fn-art">{art}</span></button>'
                     f'<p class="fn-kind"><span class="fn-num">{i + 1}</span>{esc(o["kind"])}</p>'   # its time is in the caption under the cards
                     f'<ol class="fn-path" aria-label="How it gets made">{"".join(f"<li>{esc(x)}</li>" for x in o["path"])}</ol>'
                     f'<p class="fn-where">{esc(o["where"])}</p></li>')
        opens.append(f'<div class="fn-big fn-{esc(o["shape"].replace(":", "x"))}" data-i="{i}" hidden>{big}'
                     f'<p class="fn-big-cap"><span class="fn-num">{i + 1}</span>{esc(o["kind"])} \u00b7 '
                     f'<span class="fn-path">{"".join(f"<span>{esc(x)}</span>" for x in o["path"])}</span> \u00b7 {mm(o["at"])} in the episode</p></div>')
    head = (f'<div class="fn-ep"><div class="fn-ep-head"><span class="fn-ep-t">{esc(ep["title"])}</span>'
            f'<a class="fn-ep-a" href="{esc(ep["href"])}" target="_blank" rel="noopener">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5A.8.8 0 0 0 8 5.2z"/></svg>Watch Episode</a></div>'
            f'<div class="fn-wavebar"><canvas class="fn-canvas" aria-hidden="true"></canvas>{marks}</div>'
            f'<p class="fn-ep-len"><span class="fn-ep-now">0:00</span><span>{mm(ep["length"])}</span></p></div>')
    sheet = (f'<div class="fn-sheet" hidden><button class="fn-close" type="button" aria-label="Close">'
             f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>{"".join(opens)}</div>')
    # its caption sits in the box, right under the pieces it describes
    live = f'<p class="ai-note ai-live">{esc(b["note"])}</p>' if b.get("note") else ""
    return ai_figure({**b, "note": None}, "One podcast episode turned into five formats",
                     f'{head}<ol class="fn-cards">{"".join(cards)}</ol>{live}{sheet}{AI_SOUND}')


def ranking(v):
    """Semrush's Position Tracking box: visibility, how many keywords rank in the top 3, 10, 20 and 100, and the top
    keywords. The keywords are examples from the demo; every position, share and count is hidden."""
    area = ('<svg class="sr-area" viewBox="0 0 200 80" preserveAspectRatio="none" aria-hidden="true">'
            '<path d="M0 34 L14 22 L28 36 L44 20 L60 26 L74 16 L88 30 L102 24 L116 38 L130 30 L146 44 L160 36 L176 48 L200 46 V80 H0Z"/></svg>')
    tops = "".join(f'<li><span>{n}</span><span class="sr-ring"></span>{v}<svg class="sr-spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true">'
                   '<path d="M0 14 L12 12 L20 15 L30 8 L40 11 L52 6 L62 10 L74 5 L86 9 L100 7"/></svg></li>'
                   for n in ("Top 3", "Top 10", "Top 20", "Top 100"))
    kws = "".join(f'<li><span>{k}</span><i class="sr-tag sr-tag-{t.lower()}">{t}</i>{v}{v}</li>'
                  for k, t in (("oee software", "Keyword"), ("what is oee", "Question"), ("how to improve oee", "Question"),
                               ("manufacturing downtime", "Keyword"), ("frontline production", "Keyword")))
    return ('<section class="sr-box sr-wide"><p class="sr-tab sr-tab-pt">Position Tracking</p><div class="sr-pt">'
            f'<div class="sr-vis"><p class="sr-h">Visibility</p>{v}{area}</div>'
            f'<div><p class="sr-h">Keywords</p><ul class="sr-tops">{tops}</ul></div>'
            '<div><p class="sr-h">Top Keywords</p><p class="sr-kh"><span>Keywords</span><span></span><span>Position</span><span>Visibility</span></p>'
            f'<ul class="sr-kw">{kws}</ul></div></div></section>')


def semrush(c):
    """Where it was measured: a copy of Semrush's SEO dashboard, its AI Search and SEO boxes, with every value
    hidden (no QAD Redzone numbers are confirmed for the page)."""
    v = '<b class="sr-v" aria-hidden="true"></b>'
    ai_rows = "".join(f'<li><span class="sr-src sr-{k}"></span>{n}{v}{v}</li>' for k, n in (("g", "AI Overview"), ("g", "AI Mode"), ("gpt", "ChatGPT")))
    seo = "".join(f'<li><span>{n}</span>{v}</li>' for n in ("Authority Score", "Organic Traffic", "Organic Keywords", "Ref. Domains"))
    cited = "".join(f'<li><span class="sr-kind">{k}</span><span class="sr-url">{u}</span>{v}</li>'
                    for k, u in (("FAQ", "/faq/what-is-oee"), ("Blog", "/blog/how-frontline-teams-improve-oee")))
    return (f'<div class="geo-sr">'
            + ai_window("Semrush  \u00b7  SEO Dashboard: QAD Redzone",
                        '<div class="sr-grid">'
                        '<section class="sr-box"><p class="sr-tab sr-tab-ai">AI Search</p>'
                        f'<div class="sr-tot"><p><span>AI Visibility</span><span class="sr-gauge"></span>{v}</p><p><span>Mentions</span>{v}</p><p><span>Cited pages</span>{v}</p></div>'
                        f'<ul class="sr-ai">{ai_rows}'
                        '<li><span class="sr-src sr-gem"></span>Gemini<i class="sr-soon">soon</i></li></ul>'
                        f'<p class="sr-h sr-cited-h">Top cited pages</p><ul class="sr-cited">{cited}</ul></section>'
                        f'<section class="sr-box"><p class="sr-tab sr-tab-seo">SEO</p><ul class="sr-seo">{seo}</ul></section>'
                        f'{ranking(v)}</div>', " sr-window")
            + f'<p class="geo-k sr-note">{esc(c["platform"])}</p></div>')


GEO_THUMB = {   # a shadow of what each search result would show
    "shoe": '<path class="gt-fill" d="M2.5 15.2c0-1.4.6-2.6 1.6-3.3l2.3-1.6c.6-.4 1-1.1 1.1-1.8l.2-1.3c.1-.5.7-.7 1.1-.4 1.5 1.2 3.2 1.9 5 2l2.2.2c2.4.2 4.6 1.4 5.8 3.4.4.7.2 1.6-.5 2-.3.2-.6.2-.9.2H3.6c-.6 0-1.1-.5-1.1-1.1z"/>'
            '<path class="gt-line" d="M2.6 17.6h18.6c.5 0 .9-.3 1-.8"/><path class="gt-line" d="M9.8 9.2l1.3 1.5M11.8 9.9l1.1 1.4"/>',
    "guide": '<rect class="gt-fill" x="5.5" y="3" width="13" height="18" rx="2"/><path class="gt-line" d="M8.5 8h7M8.5 11.5h7M8.5 15h4.5"/>',
    "team": '<circle class="gt-fill" cx="8.5" cy="9" r="3"/><circle class="gt-fill" cx="15.8" cy="9.5" r="2.5"/>'
            '<path class="gt-fill" d="M3 19c.4-3.2 2.7-5.3 5.5-5.3s5.1 2.1 5.5 5.3zM13.6 14.3c.7-.4 1.4-.6 2.2-.6 2.4 0 4.3 1.8 4.7 4.6h-5.4c-.2-1.6-.7-2.9-1.5-4z"/>',
    "dash": '<rect class="gt-fill" x="3" y="4.5" width="18" height="15" rx="2.5"/><path class="gt-line" d="M6.5 15.5l3.2-3.6 2.8 2.2 4.8-5.6"/><path class="gt-line" d="M6.5 8h3"/>',
}


def demo_geo(b):
    """The same need typed as a search and asked as a question, and the page fields both of them read: once for a
    Nike product page, once for QAD Redzone's FAQ and blog. The demo plays one, then the other; the switch picks."""
    cases = []
    for k, c in enumerate(b["cases"]):
        res = "".join(f'<li><span class="geo-thumb" aria-hidden="true"><svg viewBox="0 0 24 24">{GEO_THUMB[i]}</svg></span>{esc(r)}</li>'
                      for r, i in zip(c["results"], c["thumbs"]))
        fields = '<ul class="geo-fields">' + "".join(f'<li><span class="ai-label">{esc(f)}</span><span>{esc(v)}</span></li>' for f, v in c["fields"]) + "</ul>"
        search = ai_window("Search engine", f'<div class="geo-in geo-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>'
                           f'<span class="geo-typed" data-text="{esc(c["search"])}">{esc(c["search"])}</span></div><ul class="geo-results">{res}</ul>', " geo-pane")
        ask = ai_window("AI assistant", f'<div class="geo-in geo-ask"><span class="geo-typed" data-text="{esc(c["ask"])}">{esc(c["ask"])}</span></div>'
                        f'<p class="geo-answer">{AI_SPARK}<span>{esc(c["answer"])}</span></p><p class="geo-cite">{esc(c["cite"])}</p>', " geo-pane")
        cases.append(f'<div class="geo-case geo-{esc(c["id"])}" data-case="{k}"{"" if k == 0 else " hidden"}>'
                     f'<div class="geo-grid"><p class="geo-k">Keywords</p><p class="geo-k">A question</p>{search}{ask}</div>'
                     f'<div class="geo-src">{ai_window(c["source"], fields)}</div>{semrush(c) if c.get("platform") else ""}</div>')
    switch = ('<div class="hb-views geo-switch" role="group" aria-label="Which example">'
              + "".join(f'<button type="button" data-case="{k}" aria-pressed="{"true" if k == 0 else "false"}">{esc(c["label"])}</button>'
                        for k, c in enumerate(b["cases"])) + "</div>")
    return ai_figure(b, "Illustration: a Nike product and a QAD Redzone FAQ, each found by a keyword search and by an AI answer",
                     switch + "".join(cases))


def demo_tools(b, root):
    cards = []
    for t in b["tools"]:
        v = lambda f: f'{root}assets/ai/{f}?v={asset_version("assets/ai/" + f)}'
        if t.get("video"):
            screen = (f'<video class="tl-video" src="{v(t["video"])}" poster="{v(t["img"])}" muted loop playsinline preload="none" '
                      f'aria-label="{esc(t["name"])}, a short tour of its screens"></video>')
        elif t.get("img"):
            screen = f'<img src="{v(t["img"])}" alt="{esc(t["name"])}" loading="lazy">'
        else:
            screen = f'<span class="tl-icon"><img src="{v(t["icon"])}" alt="" loading="lazy"></span><span class="tl-soon-n">Screen recording coming soon</span>'
        cta = (f'<a class="tl-cta" href="{esc(t["href"])}" target="_blank" rel="noopener">{esc(t["cta"])}</a>' if t.get("href")
               else '<span class="tl-cta is-soon">Coming soon</span>')
        cards.append(f'<li class="tl-card"><div class="tl-screen{"" if t.get("video") or t.get("img") else " is-empty"}">{screen}</div>'
                     f'<div class="tl-body"><h3>{esc(t["name"])}</h3><p>{esc(t["line"])}</p>{cta}</div></li>')
    return f'<div class="wrap ai-demo ai-tools" data-demo="tools"><ul class="tl-grid">{"".join(cards)}</ul></div>'


def demo_meta(b, root):
    """The site inside itself: a browser window that zooms out from this page, holding a live copy of it (an
    iframe at desktop size, scaled down) that a cursor scrolls through and back to this very section, where the
    copy shows the window again. ai-page.js stops the copies two deep."""
    chips = "".join(f'<span class="mt-chip">{esc(c)}</span>' for c in b["chips"])
    inner = (f'<div class="mt-zoom"><div class="ai-window mt-win"><div class="ai-bar mt-bar" aria-hidden="true"><span class="ai-dots"><i></i><i></i><i></i></span>'
             f'<span class="mt-url">{esc(b["address"])}</span></div><div class="mt-view">'
             f'<iframe class="mt-frame" title="This page, inside itself" tabindex="-1" loading="lazy" data-src="{root}ai/?frame=1#site"></iframe>'
             f'<svg class="mt-cursor" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg>'
             f'<span class="mt-here" aria-hidden="true">You are here</span></div></div></div><div class="mt-chips" aria-hidden="true">{chips}</div>')
    return ai_figure(b, "This page, shown inside itself", inner)


def demo_machine(b, root):
    """The page as one content machine: its steps in order, each a jump to the demo that shows it, the way back to
    the start, and results from the programs it ran in."""
    steps = "".join(f'<li><a href="{esc(st["href"])}"><span class="mc-n">{k}</span><b>{esc(st["n"])}</b><span>{esc(st["t"])}</span></a></li>'
                    for k, st in enumerate(b["steps"], 1))
    res = "".join(f'<li><b>{esc(r["v"])}</b><span>{esc(r["t"])}</span></li>' for r in b["results"])
    return (f'<div class="wrap ai-demo ai-machine" id="{esc(b["id"])}"><ol class="mc-steps">{steps}</ol>'
            f'<p class="mc-back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v4.5h-4.5"/></svg>{esc(b["back"])}</p>'
            f'<ul class="mc-results">{res}</ul></div>')


def ai_block(b, root):
    """A section of the AI page: its words, then its demo."""
    links = ""
    if b.get("link"):
        links = f'<p class="ai-links"><a href="{root}{esc(b["link"]["href"])}">{esc(b["link"]["label"])}</a></p>'
    if b.get("links"):
        links = '<p class="ai-links">' + "".join(f'<a href="{root}{esc(l["href"])}">{esc(l["label"])}</a>' for l in b["links"]) + "</p>"
    words = section_open(b, " ai-sec") + links + "</section>" if b.get("h") else ""   # the opening's words are in the page's own head
    if b.get("step"):   # which step of the loop at the top this section shows, in the loop's own blue
        words = words.replace("<h2>", f'<p class="ai-step">{esc(b["step"])}</p><h2>', 1)
    kind = b.get("demo")
    if not kind:
        return words
    fig = {"geo": demo_geo}.get(kind)
    if kind in ("localize", "board", "cut", "fan", "tools", "meta", "machine"):
        return words + {"machine": demo_machine, "localize": demo_localize, "board": demo_board, "cut": demo_cut, "fan": demo_fan, "tools": demo_tools, "meta": demo_meta}[kind](b, root)
    return words + fig(b)


def render_ai(page, site, media):
    """The hidden AI page (content/ai.json): a case study's frame (banner, hero, lede, sections, the way on),
    with a demo under most sections. In the switcher as AI Workflows."""
    root = "../"
    hero = page["hero"]
    # it opens as a category page does (title, description, tools, a paragraph), and the content machine's loop
    # comes straight after as the first thing shown
    opening = next(b for b in page["blocks"] if b["demo"] == "machine")
    parts = [f'''<script src="{root}assets/js/ai-page.js?v={asset_version("assets/js/ai-page.js")}" defer></script>
<section class="wrap cat-text is-lead is-first ai-head">
  <h1>{esc(hero["title"])}</h1>
  <p class="kicker-italic">{esc(page["lede"])}</p>
  <p class="tools">{esc(page["tools"])}</p>
  {paragraphs(opening["p"])}
</section>''']
    parts += [ai_block(b, root) for b in page["blocks"]]
    nxt = page["next"]
    parts.append(f'''
<nav class="wrap case-nav" aria-label="Case study navigation">
  <a class="case-nav-link" href="{root}">Back to Case Studies</a>
  <a class="btn btn-rust" href="{root}{nxt["slug"]}/" style="{case_shine(nxt["slug"], media)}">{esc(nxt["label"])}</a>
</nav>''')
    page = {**page, "type": "case", "nav_active": "ai", "body_class": "case-v2 cat-v2 ai-page"}
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
    {f'<div class="case-logos">{logos}</div>' if logos and not hero.get("logos_in_glance") else ""}
    <h1>{esc(hero["title"])}</h1>
    <p class="case-sub">{esc(hero["subtitle"])}</p>
  </div>
</section>
<div class="wrap prose lede-wrap"><p class="lede">{esc(page["lede"])}</p></div>''']
    if page.get("glance"):
        parts.append(glance(page["glance"], logos if hero.get("logos_in_glance") else ""))
    for b in page["blocks"]:
        if "steps" in b:
            parts.append(flow(b, media, root))
        elif "lanes" in b:
            parts.append(timeline(b))
        elif "phases" in b:
            parts.append(phases(b))
        elif b.get("notes"):
            # a reference drawn as the document itself: the words and a page with its contents, side by side on a
            # light band (stacked on phones)
            items = "".join(f"<li>{esc(t)}</li>" for t in b["items"])
            sid = f' id="{esc(b["id"])}"' if b.get("id") else ""
            parts.append(f'<section class="ref-figure ph-notes"{sid}><div class="ref-band"><div class="wrap ref-split">'
                         f'<div class="prose ref-words"><h2>{esc(b["h"])}</h2>\n{paragraphs(b.get("p", []) + b.get("p2", []))}</div>'
                         f'<div class="ref-page" role="img" aria-label="The contents of the authoring reference">'
                         f'<p class="ref-title">{esc(b.get("doc_title", "Authoring reference"))}</p><p class="ref-sub">Contents</p>'
                         f'<ol class="ref-list">{items}</ol></div></div></div></section>')
        elif "statement" in b:
            parts.append(f'<div class="wrap prose statement-wrap"><p class="statement">{esc(b["statement"])}</p></div>')
        elif b.get("locked_strip"):
            # a standard carousel of open pieces and locked ones (an executive's ghostwritten posts): the encrypted
            # strip (tools/lock_cohesity.py) replaces it once the passcode is entered
            lock = publish_lock(b["locked_strip"], root)
            parts.append(f'<section class="gw-wrap gw-mixed" aria-label="{esc(b.get("aria", "Newsletter and executive posts"))}">'
                         f'{lock_widget(lock, b["shapes"], note=b.get("note", True), row=locked_strip_row(b, media, site, root))}</section>')
        elif "scene" in b:
            # the words can sit above the scene (h, p), below it (h2, p2), or both
            sid = f' id="{esc(b["id"])}"' if b.get("id") and not b.get("h") else ""
            head = f'<h2>{esc(b["h2"])}</h2>' if b.get("h2") else ""
            after = f'<section class="wrap prose pj-after"{sid}>{head}{paragraphs(b["p2"])}</section>' if b.get("p2") else ""
            parts.append((section_open(b) + "</section>" if b.get("h") else "") + scene(b, root) + after)
        elif "gallery" in b:
            items = [gallery_item(r, media, site) for r in b["gallery"]]
            parts.append(strip(items, root, "Project gallery", b))
        elif "videos" in b:
            items = [gallery_item({"v": v}, media, site) for v in b["videos"]]
            parts.append(strip(items, root, "Videos", {**b, "height": 378}, kind="videos"))
        else:
            intro = " intro" if b["h"] in ("THE PROBLEM", "THE SOLUTION") else ""
            fig = f'<div class="sec-fig">{sc_figure(b["figure"], media, root)}</div>' if b.get("figure") else ""
            parts.append(section_open(b, intro) + fig + "</section>")
    if page.get("contact"):
        # the page's ending: one line to the reader and the ways to reach him (from site.json)
        parts.append(f'<section class="wrap prose statement-wrap" id="contact"><p class="statement">{esc(page["contact"]["statement"])}</p>'
                     f'{contact_links(site, root, "contact-row")}</section>')
    nxt = page["next"]
    parts.append(f'''
<nav class="wrap case-nav" aria-label="Case study navigation">
  <a class="case-nav-link" href="{root}">Back to Case Studies</a>
  <a class="btn btn-rust" href="{root}{nxt["slug"]}/" style="{case_shine(nxt["slug"], media)}">{esc(nxt["label"])}</a>
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
    themed_css()
    media = Media(src_dirs)
    site = json.loads((CONTENT / "site.json").read_text())

    pages = [json.loads((CONTENT / "home.json").read_text())]
    site["home"] = pages[0]  # the category pages reuse its intro
    for f in ("categories.json", "cases-1.json", "cases-2.json"):
        pages += json.loads((CONTENT / f).read_text())
    # the AI page: built like a case study, linked from nowhere yet (it isn't in site.json's nav)
    pages += [{**p, "type": "ai"} for p in json.loads((CONTENT / "ai.json").read_text())]
    if (CONTENT / "ghostwriting.lock.json").exists():
        pages.append({"type": "locked", "slug": "ghostwriting", "lock": "ghostwriting.lock.json",
                      "nav_active": "social-writing", "heading": "Executive Ghostwriting",
                      "title": "Christian's Executive Ghostwriting",
                      "description": "Executive ghostwriting samples (password protected)."})

    for page in pages:
        print(f"page /{page['slug']}")
        render = {"home": render_home, "category": render_category, "case": render_case, "locked": render_locked,
                  "ai": render_ai}[page["type"]]
        out = render(page, site, media)
        dest = ROOT / page["slug"] / "index.html" if page["slug"] else ROOT / "index.html"
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(out)
    media.save()

    total = sum(f.stat().st_size for f in MEDIA.iterdir())
    print(f"done: {len(pages)} pages, media {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
