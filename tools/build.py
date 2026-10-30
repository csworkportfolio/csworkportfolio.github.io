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
    # Back to Top, and on a page that asks for it, its way back beside the pill
    footer_start = '<a href="#top" class="to-top">Back to top <span aria-hidden="true">↑</span></a>'
    if page.get("footer_back"):
        footer_start = (f'<span class="footer-start">{footer_start}'
                        f'<a class="footer-back" href="{root}{page["footer_back"]["href"]}">{esc(page["footer_back"]["label"])}</a></span>')
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
    {footer_start}
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
            tools = f'<p class="tools">{esc(b["tools"])}</p>' if b.get("tools") else ""
            # a heading that introduces the strip below it sits close to that strip
            lead = ""
            if page.get("v2") and n + 1 < len(blocks) and "gallery" in blocks[n + 1]:
                lead = " is-lead is-first" if n == 0 else " is-lead"
            parts.append(f'''
<section class="wrap cat-text{lead}">
  <{tag}>{esc(b["heading"])}</{tag}>
  {tools}
  <p class="kicker-italic">{esc(b["kicker"])}</p>
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
AI_RESET = ('<button class="ai-btn ai-reset" type="button" aria-label="Play again from the start"><svg viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 3.5v4h4"/></svg></button>')
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


def ai_figure(b, label, inner, pause=True):   # pause="reset": a demo that plays once gets a reset button instead
    data = {k: v for k, v in b.items() if k not in ("h", "p", "id", "note", "link", "demo")}
    note = f'<figcaption class="ai-note">{esc(b["note"])}</figcaption>' if b.get("note") else ""
    nav = '<nav class="hb-chapters"'
    if note and nav in inner:   # a demo told in steps: its caption sits right under the window, like a tutorial
        inner = inner.replace(nav, f'<p class="ai-note ai-live">{esc(b["note"])}</p>{nav}', 1)
        note = ""
    return (f'<figure class="wrap ai-demo ai-{b["demo"]}" data-demo="{b["demo"]}" aria-label="{esc(label)}">'
            f'<script type="application/json" class="ai-data">{json_script(data)}</script>'
            f'<div class="ai-stage">{inner}{AI_RESET if pause == "reset" else AI_PAUSE if pause else ""}</div>{note}</figure>')


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
            big = f'<div class="fn-big-doc">{hero}{body}</div>'
            art = f'<span class="fn-fit" aria-hidden="true">{big}</span>'   # the opened post itself, scaled down to fit the card
        else:
            # the top of a LinkedIn newsletter issue, like Security Spotlight: its bar, the green header, the title,
            # who posted it, and the intro paragraph, cut off where the reader would click through
            top = (f'<span class="li-nl-bar"><img class="li-nl-s" src="{src("assets/ai/hub/cohesity-s.png")}" alt="">'
                   f'<span class="li-nl-n"><b>{esc(o["newsletter"])}</b><small>Newsletter</small></span><span class="li-nl-sub">+ Subscribe</span></span>'
                   f'<img class="li-nl-hero" src="{src(o["image"])}" alt="{esc(o["topic"])}" loading="lazy">'
                   f'<span class="li-nl-t">{esc(o["topic"])}</span>'
                   f'<span class="li-nl-by"><img class="li-nl-s" src="{src("assets/ai/hub/cohesity-s.png")}" alt=""><b>Cohesity</b></span>'
                   f'<span class="li-nl-p">{esc(o["blurb"])}</span>')
            art = f'<span class="fn-fit" aria-hidden="true"><span class="li-nl is-big">{top}</span></span>'   # the opened issue, scaled down
            big = (f'<div class="li-nl is-big">{top}<a class="fn-link" href="{esc(ep["href"])}" target="_blank" rel="noopener">'
                   f'Listen to the Episode</a></div>')
        cards.append(f'<li class="fn-card fn-{esc(o["shape"].replace(":", "x"))}"><button class="fn-open" type="button" aria-label="Open the {label}">'
                     f'<span class="fn-art">{art}</span></button>'
                     f'<p class="fn-kind"><span class="fn-num">{i + 1}</span>{esc(o["kind"])}</p>'   # its time is in the caption under the cards
                     f'<ol class="fn-path" aria-label="How it gets made">{"".join(f"<li>{esc(x)}</li>" for x in o["path"])}</ol>'
                     f'<p class="fn-where">{esc(o["where"])}</p></li>')
        opens.append(f'<div class="fn-big fn-{esc(o["shape"].replace(":", "x"))}" data-i="{i}" hidden>{big}'
                     f'<div class="fn-big-cap"><p class="fn-big-kind">{esc(o["kind"])} \u00b7 {mm(o["at"])} in the episode</p>'
                     f'<p class="fn-path fn-big-path">{"".join(f"<span>{esc(x)}</span>" for x in o["path"])}</p></div></div>')
    head = (f'<div class="fn-ep"><div class="fn-ep-head"><span class="fn-ep-t">{esc(ep["title"])}</span>'
            f'<a class="fn-ep-a" href="{esc(ep["href"])}" target="_blank" rel="noopener">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5A.8.8 0 0 0 8 5.2z"/></svg>Watch Episode</a></div>'
            f'<div class="fn-wavebar"><canvas class="fn-canvas" aria-hidden="true"></canvas>{marks}</div>'
            f'<p class="fn-ep-len"><span class="fn-ep-now">0:00</span><span>{mm(ep["length"])}</span></p></div>')
    # the opened view: the piece full size, its path large under it, and glass arrows to the piece before and after
    sheet = (f'<div class="fn-sheet" hidden><button class="fn-close" type="button" aria-label="Close">'
             f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>'
             '<button class="fn-step fn-prev" type="button" aria-label="Previous format"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg></button>'
             '<button class="fn-step fn-next" type="button" aria-label="Next format"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg></button>'
             f'{"".join(opens)}</div>')
    # its caption sits in the box, right under the pieces it describes
    live = f'<p class="ai-note ai-live">{esc(b["note"])}</p>' if b.get("note") else ""
    return ai_figure({**b, "note": None}, "One podcast episode turned into five formats",
                     f'{head}<ol class="fn-cards">{"".join(cards)}</ol>{live}{sheet}{AI_SOUND}')


def ranking(n):
    """Semrush's Position Tracking box: visibility, how many keywords rank in the top 3, 10, 20 and 100, and the top
    keywords. The keywords are examples from the demo; the figures are example figures (content: numbers)."""
    v = lambda x: f'<b class="sr-n">{esc(x)}</b>'
    area = ('<svg class="sr-area" viewBox="0 0 200 80" preserveAspectRatio="none" aria-hidden="true">'
            '<path d="M0 34 L14 22 L28 36 L44 20 L60 26 L74 16 L88 30 L102 24 L116 38 L130 30 L146 44 L160 36 L176 48 L200 46 V80 H0Z"/></svg>')
    tops = "".join(f'<li><span>{t}</span><span class="sr-ring"></span>{v(x)}<svg class="sr-spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true">'
                   '<path d="M0 14 L12 12 L20 15 L30 8 L40 11 L52 6 L62 10 L74 5 L86 9 L100 7"/></svg></li>'
                   for t, x in zip(("Top 3", "Top 10", "Top 20", "Top 100"), n["tops"]))
    kws = "".join(f'<li><span>{k}</span><i class="sr-tag sr-tag-{t.lower()}">{t}</i>{v(pos)}{v(vis)}</li>'
                  for (k, t), (pos, vis) in zip((("oee software", "Keyword"), ("what is oee", "Question"), ("how to improve oee", "Question"),
                                                  ("manufacturing downtime", "Keyword"), ("frontline production", "Keyword")), n["keywords"]))
    return ('<section class="sr-box sr-wide"><p class="sr-tab sr-tab-pt">Position Tracking</p><div class="sr-pt">'
            f'<div class="sr-vis"><p class="sr-h">Visibility</p>{v(n["pt_visibility"])}{area}</div>'
            f'<div><p class="sr-h">Keywords</p><ul class="sr-tops">{tops}</ul></div>'
            '<div><p class="sr-h">Top Keywords</p><p class="sr-kh"><span>Keywords</span><span></span><span>Position</span><span>Visibility</span></p>'
            f'<ul class="sr-kw">{kws}</ul></div></div></section>')


def semrush(c):
    """Where it was measured: a copy of Semrush's SEO dashboard (AI Search, SEO and Position Tracking) filled with
    example figures, changed for the page; the fine print under the demo says so."""
    n = c["numbers"]
    v = lambda x: f'<b class="sr-n">{esc(x)}</b>'
    ai_rows = "".join(f'<li><span class="sr-src sr-{k}"></span>{name}{v(m)}{v(p)}</li>'
                      for (k, name), (m, p) in zip((("g", "AI Overview"), ("g", "AI Mode"), ("gpt", "ChatGPT")), n["ai_rows"]))
    seo = "".join(f'<li><span>{name}</span>{v(x)}</li>' for name, x in zip(("Authority Score", "Organic Traffic", "Organic Keywords", "Ref. Domains"), n["seo"]))
    cited = "".join(f'<li><span class="sr-kind">{k}</span><span class="sr-url">{u}</span>{v(x)}</li>'
                    for (k, u), x in zip((("FAQ", "/faq/what-is-oee"), ("Blog", "/blog/how-frontline-teams-improve-oee")), n["cited_pages"]))
    return (f'<div class="geo-sr"><p class="geo-k">Semrush SEO Dashboard: QAD Redzone</p>'
            + ai_window("Semrush  \u00b7  SEO Dashboard: QAD Redzone",
                        '<div class="sr-grid">'
                        '<section class="sr-box"><p class="sr-tab sr-tab-ai">AI Search</p>'
                        f'<div class="sr-tot"><p><span>AI Visibility</span><span class="sr-gauge"></span>{v(n["ai_visibility"])}</p>'
                        f'<p><span>Mentions</span>{v(n["mentions"])}</p><p><span>Cited Pages</span>{v(n["cited"])}</p></div>'
                        f'<ul class="sr-ai">{ai_rows}'
                        '<li><span class="sr-src sr-gem"></span>Gemini<i class="sr-soon">soon</i></li></ul>'
                        f'<p class="sr-h sr-cited-h">Top Cited Pages</p><ul class="sr-cited">{cited}</ul></section>'
                        f'<section class="sr-box"><p class="sr-tab sr-tab-seo">SEO</p><ul class="sr-seo">{seo}</ul></section>'
                        f'{ranking(n)}</div>', " sr-window")
            + '</div>')


GEO_THUMB = {   # a shadow of what each search result would show
    "shoe": '<path class="gt-fill" d="M2.5 15.2c0-1.4.6-2.6 1.6-3.3l2.3-1.6c.6-.4 1-1.1 1.1-1.8l.2-1.3c.1-.5.7-.7 1.1-.4 1.5 1.2 3.2 1.9 5 2l2.2.2c2.4.2 4.6 1.4 5.8 3.4.4.7.2 1.6-.5 2-.3.2-.6.2-.9.2H3.6c-.6 0-1.1-.5-1.1-1.1z"/>'
            '<path class="gt-line" d="M2.6 17.6h18.6c.5 0 .9-.3 1-.8"/><path class="gt-line" d="M9.8 9.2l1.3 1.5M11.8 9.9l1.1 1.4"/>',
    "guide": '<rect class="gt-fill" x="5.5" y="3" width="13" height="18" rx="2"/><path class="gt-line" d="M8.5 8h7M8.5 11.5h7M8.5 15h4.5"/>',
    "team": '<circle class="gt-fill" cx="8.5" cy="9" r="3"/><circle class="gt-fill" cx="15.8" cy="9.5" r="2.5"/>'
            '<path class="gt-fill" d="M3 19c.4-3.2 2.7-5.3 5.5-5.3s5.1 2.1 5.5 5.3zM13.6 14.3c.7-.4 1.4-.6 2.2-.6 2.4 0 4.3 1.8 4.7 4.6h-5.4c-.2-1.6-.7-2.9-1.5-4z"/>',
    "dash": '<rect class="gt-fill" x="3" y="4.5" width="18" height="15" rx="2.5"/><path class="gt-line" d="M6.5 15.5l3.2-3.6 2.8 2.2 4.8-5.6"/><path class="gt-line" d="M6.5 8h3"/>',
}


ROOT_REL = "../"   # the AI page sits one folder down


def demo_geo(b):
    """The same need typed as a search and asked as a question, and the page fields both of them read: once for a
    Nike product page, once for QAD Redzone's FAQ and blog. The demo plays one, then the other; the switch picks."""
    cases = []
    for k, c in enumerate(b["cases"]):
        # a thumb is a picture from the real page when it names a file, otherwise a drawn shape
        thumb = lambda t: (f'<img src="{ROOT_REL}{esc(t)}?v={asset_version(t)}" alt="" loading="lazy">' if "/" in t
                           else f'<svg viewBox="0 0 24 24">{GEO_THUMB[t]}</svg>')
        res = "".join(f'<li><span class="geo-thumb" aria-hidden="true">{thumb(i)}</span>{esc(r)}</li>'
                      for r, i in zip(c["results"], c["thumbs"]))
        # the real product page, when there is one, above the fields both kinds of search read from it
        page = (f'<img class="geo-page" src="{ROOT_REL}{esc(c["page"])}?v={asset_version(c["page"])}" alt="{esc(c["page_alt"])}" loading="lazy">'
                if c.get("page") else "")
        if c.get("page_dark"):   # the same page in dark mode (made from his screenshot: the photos kept, the rest darkened)
            page += (f'<img class="geo-page geo-page-dark" src="{ROOT_REL}{esc(c["page_dark"])}?v={asset_version(c["page_dark"])}" '
                     f'alt="{esc(c["page_alt"])}" loading="lazy">')
        if page:   # the page sits on its own colour, which runs out to the window's sides
            page = f'<div class="geo-page-wrap">{page}</div>'
        fields = '<ul class="geo-fields">' + "".join(f'<li><span class="ai-label">{esc(f)}</span><span>{esc(v)}</span></li>' for f, v in c["fields"]) + "</ul>"
        search = ai_window("Search Engine", f'<div class="geo-in geo-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>'
                           f'<span class="geo-typed" data-text="{esc(c["search"])}">{esc(c["search"])}</span></div><ul class="geo-results">{res}</ul>', " geo-pane")
        ask = ai_window("AI Assistant", f'<div class="geo-in geo-ask"><span class="geo-typed" data-text="{esc(c["ask"])}">{esc(c["ask"])}</span></div>'
                        f'<div class="geo-reply"><p class="geo-dots" aria-hidden="true"><i></i><i></i><i></i></p>'   # the AI typing, as in Messages
                        f'<p class="geo-answer">{AI_SPARK}<span>{esc(c["answer"])}</span></p></div><p class="geo-cite">{esc(c["cite"])}</p>', " geo-pane")
        cases.append(f'<div class="geo-case geo-{esc(c["id"])}" data-case="{k}"{"" if k == 0 else " hidden"}>'
                     f'<div class="geo-grid"><p class="geo-k">Search Engine Keywords</p><p class="geo-k">AI Assistant Questions</p>{search}{ask}</div>'
                     f'<div class="geo-src">{ai_window(c["source"], page + fields)}</div>{semrush(c) if c.get("platform") else ""}</div>')
    switch = ('<div class="hb-views geo-switch" role="group" aria-label="Which example">'
              + "".join(f'<button type="button" data-case="{k}" aria-pressed="{"true" if k == 0 else "false"}">{esc(c["label"])}</button>'
                        for k, c in enumerate(b["cases"])) + "</div>")
    # a caption in the box says what is happening at each step, as the other demos do (ai-page.js)
    # the note on what is real sits faintly at the foot of the box
    fine = "".join(f'<p class="geo-fine" data-case="{k}"{"" if k == 0 else " hidden"}>{esc(c.get("fine") or b.get("note", ""))}</p>'
                   for k, c in enumerate(b["cases"]))   # each example's own note, shown with it
    return ai_figure({**b, "note": None}, "Illustration: a Nike product and a QAD Redzone FAQ, each found by a keyword search and by an AI answer",
                     switch + "".join(cases) + '<p class="ai-note ai-live geo-live"></p>' + fine, pause="reset")


HH_WHALE = ('<svg class="hh-whale" viewBox="4 6 60 56" aria-hidden="true"><path class="hh-tail" d="M31.5 31C28 24 18 15 9 9C7 17 9 27 17 32'
            'C21.5 34.8 26 36 28.6 38.5C29.6 43 29.4 48 28 53L41 53C37.5 50 35.6 45 35.4 40C40 38.5 48 36 54 31C58 27.5 60 22 60.5 16'
            'C52 21 44 24 37 27.5C35 28.6 33.2 29.8 31.5 31Z"/><path class="hh-ripple" d="M17.9 58.6C12 58 7.5 56.5 8.5 53.7'
            'M60.5 53.7C61.5 56.5 57 58 51.1 58.6M44.5 57.1C38 58 31 58 24.5 57.1"/></svg>')
HH_ICONS = {   # SF Symbol look-alikes on a 24 grid
    "search": "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 20 20",
    "plus": "M12 5v14M5 12h14",
    "folder": "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    "tray": "M4 13l2-7h12l2 7v5H4zM4 13h5l1 2h4l1-2h5",
    "trash": "M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12",
    "check": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM8 12l3 3 5-6",
    "gear": "M12 8.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1",
    "spark": "M12 4c.5 3.6 2.4 5.5 6 6-3.6.5-5.5 2.4-6 6-.5-3.6-2.4-5.5-6-6 3.6-.5 5.5-2.4 6-6z",
    "dots": "M6 12h.01M12 12h.01M18 12h.01",
    "share": "M12 3v12M8 7l4-4 4 4M6 11v9h12v-9",
    "stack": "M5 9h14v11H5zM7 6h10M9 3h6",
    "chev": "M9 6l6 6-6 6",
}


def hh_icon(n, cls="hh-i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="{HH_ICONS[n]}"/></svg>'


def demo_heardhum(w, root):
    """heardhum, Christian's Mac menu bar app, in its default navy theme (drawn at 720 by 450 and scaled to the card;
    after the app's SwiftUI views). The menu bar card catches a call, the recording opens in All Files, a voice gets
    its name and a word of the AI summary is fixed. Every name, call and line is made up. Drawn finished."""
    icon = f'<img class="hh-app" src="{root}assets/ai/heardhum-icon.png?v={asset_version("assets/ai/heardhum-icon.png")}" alt="">'
    brand = f'<p class="hh-brand">{icon}<b>heardhum</b></p>'
    files = [[w["call"], w["length"].replace(":", "m ") + "s", "2026-10-29 10:02"]] + w["files"]
    rows = "".join(
        f'<div class="hh-row{" is-new" if i == 0 else ""}"><span class="hh-row-t">{esc(f[0])}'
        f'<small class="hh-badge">{hh_icon("check")}<span class="hh-badge-v">Summarized</span></small></span>'
        f'<span>{esc(f[1])}</span><span>{esc(f[2])}</span><span class="hh-more">{hh_icon("dots")}</span></div>'
        for i, f in enumerate(files))
    side_rows = "".join(
        f'<div class="hh-srow{" is-on" if i == 0 else ""}"><b>{esc(f[0])}</b><small>{esc(f[2][5:].replace("-", "/"))}  |  {esc(f[1])}</small></div>'
        for i, f in enumerate(files[:4]))

    def para(p):
        t, s, text = p
        m = re.match(r"(.*)\[(.*)\](.*)", text)
        body = (f'{esc(m[1])}<span class="hh-sel">{esc(m[2])}</span>{esc(m[3])}' if m else esc(text))
        who = esc(w["name"]) if s == 1 else f"Speaker {s}"
        return (f'<div class="hh-para"><p class="hh-ph"><span class="hh-time">{t}</span>'
                f'<span class="hh-spk" data-s="{s}">{who}</span>{"<span class=hh-ren>Rename</span>" if s == 1 else ""}</p>'
                f'<p class="hh-pt">{body}</p></div>')
    first = next(i for i, p in enumerate(w["transcript"]) if p[1] == 1)
    paras = "".join(para(p).replace('class="hh-para"', 'class="hh-para is-first"', 1) if i == first else para(p)
                    for i, p in enumerate(w["transcript"]))

    def block(kind, text):
        m = re.match(r"(.*)\[(.*)\|(.*)\](.*)", text)
        body = (f'{esc(m[1])}<span class="hh-edit" data-old="{esc(m[2])}">{esc(m[3])}</span>{esc(m[4])}' if m else esc(text))
        if kind == "h":
            return f'<h5>{body}</h5>'
        if kind == "add":
            return f'<li class="hh-add" data-text="{esc(text)}"><span class="hh-add-v">{body}</span><i class="hh-caret"></i></li>'
        return f'<li><span>{body}</span></li>' if kind == "li" else f'<p>{body}</p>'
    summary, ul = "", False
    for kind, text in w["summary"]:
        li = kind in ("li", "add")
        if li and not ul: summary += "<ul>"
        if ul and not li: summary += "</ul>"
        ul = li
        summary += block(kind, text)
    summary += "</ul>" if ul else ""
    nav = "".join(f'<p class="hh-nav{c}">{hh_icon(i)}<span>{t}</span>{n}</p>' for i, t, n, c in (
        ("folder", "All Files", f"<small>({len(files)})</small>", " is-on"), ("tray", "Unfiled", f"<small>({len(files)})</small>", ""),
        ("trash", "Trash", "<small>(0)</small>", "")))
    return f'''<div class="hh-view"><div class="hh is-win is-page" lang="en" aria-hidden="true">
  <div class="hh-desk"></div>
  <p class="hh-bar"><b>Finder</b><span>File</span><span>Edit</span><span>View</span><span>Window</span>
    <span class="hh-bar-r"><span class="hh-mbi">{HH_WHALE}</span><span>Thu Oct 29</span><span>10:02 AM</span></span></p>
  <div class="hh-card">
    <p class="hh-card-h">{icon}<b>heardhum</b><span>{hh_icon("stack")}{hh_icon("folder")}{hh_icon("gear")}</span></p>
    <p class="hh-big"><i class="hh-stop"></i><span class="hh-big-v">Start Recording</span></p>
    <p class="hh-line"><i class="hh-dot"></i><span class="hh-line-v">Watching for calls</span><span class="hh-clock">0:00</span></p>
    <p class="hh-call">{esc(w["call"])}</p>
    <p class="hh-dont">Don’t Record This Call</p>
    <p class="hh-recent">Recent Recordings{hh_icon("chev")}</p>
  </div>
  <div class="hh-win">
    <nav class="hh-side"><span class="hh-lights"><i></i><i></i><i></i></span>{brand}
      <p class="hh-search">{hh_icon("search")}Search</p><p class="hh-upload">{hh_icon("plus")}Upload Recording</p>{nav}
      <p class="hh-sub">Summaries</p><p class="hh-nav">{hh_icon("check")}<span>Summarized</span><small>({len(files)})</small></p>
      <p class="hh-nav hh-gear">{hh_icon("gear")}<span>Settings</span></p>
      <p class="hh-watch"><i></i>Watching for calls</p></nav>
    <main class="hh-list"><h4>All Files{hh_icon("folder")}</h4>
      <div class="hh-row hh-head"><span>Name</span><span>Duration</span><span>Date Created</span><span></span></div>{rows}</main>
    <section class="hh-page">
      <p class="hh-top">{hh_icon("folder")}All Files{hh_icon("chev")}<b>{esc(w["call"])}</b>
        <span class="hh-top-r">{hh_icon("spark")}{hh_icon("dots")}<span class="hh-share">{hh_icon("share")}Share</span></span></p>
      <div class="hh-cols"><div class="hh-slist">{side_rows}</div>
        <div class="hh-detail"><p class="hh-seg"><span class="is-t">Transcript</span><span class="is-s">Summary</span></p>
          <div class="hh-tr">{paras}</div><div class="hh-sum">{summary}</div></div></div>
    </section>
  </div>
  <div class="hh-pop"><b>Who is Speaker 1?</b><span class="hh-field"><span class="hh-field-v">{esc(w["name"])}</span><i class="hh-caret"></i></span>
    <span class="hh-pop-b"><span>Cancel</span><span class="hh-save">Save</span></span></div>
  <svg class="hh-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg>
</div></div><script type="application/json" class="hh-data">{json_script({"name": w["name"], "length": w["length"]})}</script>'''


BG_CATS = {   # Budget AI's built-in categories (src/server/default-categories.ts): name, emoji, colour role
    "groceries": ("Groceries", "🥑", "green"), "restaurants": ("Restaurants", "🍜", "orange"), "rent": ("Rent", "🔑", "amber"),
    "utilities": ("Utilities", "💡", "sky"), "household": ("Household", "🧺", "teal"), "transit": ("Transit & Rides", "🚌", "blue"),
}
BG_ICONS = {   # SF Symbol look-alikes on a 24 grid
    "gear": "M12 8.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1",
    "sync": "M4 12a8 8 0 0 1 13.7-5.6L20 9M20 4v5h-5M20 12a8 8 0 0 1-13.7 5.6L4 15M4 20v-5h5",
    "chev": "M9 6l6 6-6 6",
    "spark": "M12 4c.5 3.6 2.4 5.5 6 6-3.6.5-5.5 2.4-6 6-.5-3.6-2.4-5.5-6-6 3.6-.5 5.5-2.4 6-6z",
    "search": "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 20 20",
}


def bg_icon(n):
    return f'<svg class="bg-i" viewBox="0 0 24 24" aria-hidden="true"><path d="{BG_ICONS[n]}"/></svg>'


def bg_chip(key):
    if not key:
        return '<span class="bg-chip is-none">Uncategorized</span>'
    name, emoji, colour = BG_CATS[key]
    return f'<span class="bg-chip" style="--c: var(--bc-{colour})">{emoji} {esc(name)}</span>'


def demo_budget(p):
    """Budget AI, Christian's budgeting app, on an iPhone (after its phone layout and design/tokens.json, light or dark
    with the page). Drawn at 720 by 450 and scaled to the card; the phone sits 0.79 of its 393pt size and is cropped
    by the card, so the camera pans down for the sheet. The Home Screen widget opens the app, a glance at the pace,
    then the review inbox: a bakery charge takes the suggested category, and the fix becomes a rule that also renames
    it. Every name and amount is made up. Drawn finished."""
    first, *rest = p["review"]
    cat = BG_CATS[p["category"]]
    rows = [f'<div class="bg-row is-first"><span class="bg-name" data-raw="{esc(first[0])}">{esc(p["rename"])}</span>'
            f'<span class="bg-cell">{bg_chip(p["category"])}</span><span class="bg-amt">{esc(first[2])}</span><i class="bg-dot"></i></div>']
    rows += [f'<div class="bg-row"><span class="bg-name">{esc(r[0])}</span><span class="bg-cell">{bg_chip(r[1])}</span>'
             f'<span class="bg-amt">{esc(r[2])}</span><i class="bg-dot is-on"></i></div>' for r in rest]
    n = len(p["review"])

    def opt(key, cls=""):
        name, emoji, colour = BG_CATS[key]
        return f'<p class="bg-opt{cls}"><span class="bg-chip" style="--c: var(--bc-{colour})">{emoji} {esc(name)}</span></p>'
    picker = (f'<div class="bg-pick"><p class="bg-find">Search categories</p>'
              f'<p class="bg-grp">{bg_icon("spark")}Suggested</p>{opt(p["category"], " is-sug")}'
              f'<p class="bg-grp">Food</p>{opt("groceries")}{opt("restaurants")}<p class="bg-grp">Home</p>{opt("rent")}{opt("utilities")}</div>')
    tiles = "".join(f'<i class="bg-tile" style="--t: {t}"></i>' for t in
                    ("#ff9f0a", "#30d158", "#5ac8fa", "#bf5af2", "#ff375f", "#64d2ff", "#ffd60a", "#8e8e93"))
    return f'''<div class="bg-view"><div class="bg is-app is-drawn is-scroll is-con" lang="en" aria-hidden="true">
  <div class="bg-phone"><div class="bg-scr">
    <div class="bg-home">
      <div class="bg-wid is-free"><small>{esc(p["month"])}</small><b>{esc(p["left"])}</b><span>Free to Spend</span><em>{esc(p["pace"])} under pace</em></div>
      <div class="bg-wid is-rev"><small>To Review</small><b class="bg-n" data-n="{n}">{n - 1}</b><span>transactions</span></div>
      <div class="bg-tiles">{tiles}</div>
    </div>
    <div class="bg-app">
      <p class="bg-head">{bg_icon("gear")}<b>Budget AI</b>{bg_icon("sync")}</p>
      <p class="bg-tabs"><span>Cash Flow</span><span class="is-on">Dashboard <i class="bg-n" data-n="{n}">{n - 1}</i></span><span>Budgets</span></p>
      <div class="bg-body">
        <section class="bg-pace"><p class="bg-left">{esc(p["left"])} left</p><p class="bg-of">out of {esc(p["budgeted"])} budgeted</p>
          <svg class="bg-chart" viewBox="0 0 320 96" preserveAspectRatio="none"><path class="bg-even" d="M2 92L318 6"/>
            <path class="bg-fill" d="M2 92L22 91L40 89L58 88L76 84L94 83L112 79L130 77L148 74L166 73L184 71L196 70V94H2Z"/>
            <path class="bg-spent" pathLength="1" d="M2 92L22 91L40 89L58 88L76 84L94 83L112 79L130 77L148 74L166 73L184 71L196 70"/></svg>
          <span class="bg-under">{esc(p["pace"])} under</span></section>
        <p class="bg-rh"><span>To Review · <i class="bg-n" data-n="{n}">{n - 1}</i></span><span>See all{bg_icon("chev")}</span></p>
        <div class="bg-list">{"".join(rows)}</div>
      </div>
      {picker}
      <div class="bg-toast is-fix"><p><b>{esc(first[0])} → {esc(cat[0])}</b><span>Do the same for other transactions with this name?</span></p><span class="bg-act">Make a rule</span></div>
      <div class="bg-toast is-saved"><p><b>Rule saved. New transactions will follow it.</b></p></div>
      <div class="bg-sheet"><i class="bg-grab"></i><h5>Always Use This Category?</h5>
        <p class="bg-desc">Future transactions that match will be categorized automatically. Anything you’ve set by hand stays as it is.</p>
        <p class="bg-set"><span>Set to</span>{bg_chip(p["category"])}</p>
        <p class="bg-lab">Which names match</p><p class="bg-seg"><span class="is-x">This exact name</span><span class="is-c">Names containing…</span></p>
        <p class="bg-lab">Contains</p><p class="bg-field is-con" data-raw="{esc(first[0])}"><span class="bg-v">{esc(p["rename"].lower())}</span><i class="bg-caret"></i></p>
        <p class="bg-lab">Also rename them to (optional)</p><p class="bg-field is-ren"><span class="bg-v">{esc(p["rename"])}</span><i class="bg-caret"></i></p>
        <p class="bg-sw"><span>Also update {p["past"]} past transactions</span><i class="bg-switch"></i></p>
        <p class="bg-btns"><span>Not now</span><span class="bg-save">Save rule</span></p></div>
    </div>
    <div class="bg-island"></div>
    <p class="bg-status"><b>9:41</b><span class="bg-sig"><i></i><i></i><i></i><i></i></span><span class="bg-bat"></span></p>
    <i class="bg-touch"></i>
  </div></div>
</div></div>'''


MK_ICONS = {   # on a 24 grid
    "move": "M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3",
    "marquee": "M5 5h3M11 5h2M16 5h3v3M19 11v2M19 16v3h-3M13 19h-2M8 19H5v-3M5 13v-2M5 8V5",
    "lasso": "M12 5c4.4 0 8 2.2 8 5s-3.6 5-8 5-8-2.2-8-5 3.6-5 8-5zM7 14c-1 2 0 4 2 5",
    "crop": "M6 3v15h15M3 6h15v15",
    "brush": "M14 4l6 6-8 8-3-3zM9 15c-2 0-4 1.5-4 4.5 2 0 4-.5 5-2",
    "eraser": "M8 20h12M5 15l9-9 5 5-9 9H8z",
    "text": "M5 7V4h14v3M12 4v16M9 20h6",
    "drop": "M15 4l5 5-2 2-5-5zM13 6l-8 8v5h5l8-8",
    "hand": "M8 13V6a1.5 1.5 0 0 1 3 0v5V4.5a1.5 1.5 0 0 1 3 0V11V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-3l-2-4a1.5 1.5 0 0 1 2.5-1.5z",
    "zoom": "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 20 20",
    "eye": "M2 12s4-6.5 10-6.5S22 12 22 12s-4 6.5-10 6.5S2 12 2 12zM12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z",
    "pointer": "M6 3l12 7-5.5 1.5L10 17z",
    "pen": "M4 20l1-4L16 5l3 3L8 19zM14 7l3 3",
    "marker": "M5 20h6M8 16l-2-2 9-10 4 4-9 10z",
    "comment": "M5 5h14v10h-9l-4 4v-4H5z",
    "freeze": "M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9M9.5 4.5 12 7l2.5-2.5M9.5 19.5 12 17l2.5 2.5",
    "send": "M21 3 3 10.5l7 3 3 7zM10 13.5 21 3",
    "archive": "M3 5h18v4H3zM5 9v10h14V9M10 13h4",
    "rotate": "M20 12a8 8 0 1 1-2.3-5.7M20 4v4.5h-4.5",
    "scale": "M4 20 20 4M14 4h6v6M4 14v6h6",
    "cube": "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12 4 7.5",
    "camera": "M4 8h11v9H4zM15 11l5-3v9l-5-3",
    "light": "M12 3a6 6 0 0 1 3.5 10.9V17h-7v-3.1A6 6 0 0 1 12 3zM9.5 20h5",
    "mesh": "M12 4l8 15H4z",
    "box": "M4 6h16v13H4zM4 10h16",
    "ball": "M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM4 12h16",
    "play": "M8 5.5v13l11-6.5z",
}
# Claude's spark, as Markup AI draws it on Claude's avatar (the app's own claude-mark.svg, kept next to this script)
MK_SPARK = re.search(r' d="([^"]+)"', (ROOT / "tools/claude-mark.svg").read_text())[1]


def mk_icon(n):
    return f'<svg class="mk-i" viewBox="0 0 24 24" aria-hidden="true"><path d="{MK_ICONS[n]}"/></svg>'


def demo_markup(m):
    """Markup AI, Christian's comment layer for any app, over two made-up apps (drawn at 720 by 450 and scaled to the
    card; its colors and sizes from the app's style.json, dark). In a photo editor he pins the typo on a launch graphic
    for an invented coffee brand, Alder & Fern, sends it with Make It, the fix lands and Claude says so in the thread,
    and he resolves it; then the same in a 3D app, where the can's label turns the brand green. Every name is made up."""
    ph, md = m["photo"], m["model"]
    ph_tools = "".join(f'<i{" class=is-on" if n == "text" else ""}>{mk_icon(n)}</i>' for n in
                       ("move", "marquee", "lasso", "crop", "brush", "eraser", "text", "drop", "hand", "zoom"))
    layers = "".join(f'<p class="mk-layer{" is-on" if i == 0 else ""}">{mk_icon("eye")}<i class="mk-thumb{" is-t" if t else ""}">{"T" if t else ""}</i>{n}</p>'
                     for i, (n, t) in enumerate((("Headline", 1), ("Subline", 1), ("Button", 0), ("Cup", 0), ("Logo", 0), ("Background", 0))))
    photo = f'''<div class="mk-win mk-ph">
    <p class="mk-tb"><span class="mk-lights"><i></i><i></i><i></i></span><b>{esc(ph["file"])} @ 50% (Headline, RGB)</b></p>
    <p class="mk-opt">{mk_icon("text")}<span>Display</span><span>Heavy</span><span>54 pt</span><span class="mk-sw"></span><span>Align Left</span></p>
    <div class="mk-ph-body"><div class="mk-strip">{ph_tools}</div>
      <div class="mk-canvas"><div class="mk-art">
        <p class="mk-logo"><i>A</i>Alder &amp; Fern</p>
        <p class="mk-kicker">New This Summer</p>
        <h4 class="mk-h1">The Cold Brew <span class="mk-typo" data-fix="Collection">Collecton</span> Is Here</h4>
        <p class="mk-sub">Three single-origin cold brews, slow-steeped for 18 hours and poured over ice at every Alder &amp; Fern counter.</p>
        <p class="mk-cta">Find Your Nearest Counter</p>
        <p class="mk-date">From Saturday, June 7</p>
        <div class="mk-cup"><i class="mk-lid"></i><i class="mk-body"></i><i class="mk-band">COLD BREW</i></div>
        <i class="mk-leaf"></i>
      </div></div>
      <div class="mk-panels"><p class="mk-ph-h">Properties</p>
        <p class="mk-f"><span>Font</span><span>Display</span></p><p class="mk-f"><span>Weight</span><span>Heavy</span></p>
        <p class="mk-f"><span>Size</span><span>54 pt</span></p><p class="mk-f"><span>Color</span><span><i class="mk-sw"></i>#1E2A24</span></p>
        <p class="mk-ph-h">Layers</p>{layers}</div>
    </div>
  </div>'''
    outliner = "".join(f'<p class="mk-ol{c}" style="--d:{d}">{mk_icon(i)}{n}</p>' for n, i, d, c in (
        ("Scene Collection", "box", 0, ""), ("Collection", "box", 1, ""), ("Camera", "camera", 2, ""), ("Light", "light", 2, ""),
        ("Can", "mesh", 2, " is-on"), ("Label", "ball", 3, "")))
    can = ('<svg class="mk-can" viewBox="0 0 120 200" aria-hidden="true"><defs>'
           '<linearGradient id="mk-shade" x1="0" x2="1"><stop offset="0" stop-color="#000" stop-opacity=".55"/><stop offset=".32" stop-color="#fff" stop-opacity=".18"/>'
           '<stop offset=".5" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></linearGradient>'
           '<linearGradient id="mk-metal" x1="0" x2="1"><stop offset="0" stop-color="#6d7075"/><stop offset=".35" stop-color="#e3e5e8"/><stop offset="1" stop-color="#55585d"/></linearGradient></defs>'
           '<path class="mk-can-sel" d="M10 22V178A50 10 0 0 0 110 178V22A50 10 0 0 0 10 22Z"/>'
           '<path d="M10 22V178A50 10 0 0 0 110 178V22Z" fill="url(#mk-metal)"/>'
           '<path class="mk-label" d="M10 58A50 10 0 0 0 110 58V146A50 10 0 0 1 10 146Z"/>'
           '<text class="mk-can-t" x="60" y="98" text-anchor="middle">ALDER &amp; FERN</text>'
           '<text class="mk-can-s" x="60" y="116" text-anchor="middle">COLD BREW</text>'
           '<path d="M10 22V178A50 10 0 0 0 110 178V22Z" fill="url(#mk-shade)"/>'
           '<ellipse cx="60" cy="22" rx="50" ry="10" fill="#c9ccd1"/><ellipse cx="60" cy="22" rx="42" ry="7.5" fill="#9fa3a9"/>'
           '<ellipse cx="66" cy="21" rx="9" ry="2.6" fill="#7b7f85"/></svg>')
    ticks = "".join(f'<span style="left:{k * 10}%">{k * 25}</span>' for k in range(10))
    model = f'''<div class="mk-win mk-3d">
    <p class="mk-tb is-3d"><span class="mk-lights"><i></i><i></i><i></i></span><span>File</span><span>Edit</span><span>Render</span><span>Window</span>
      <span class="mk-tabs"><span class="is-on">Layout</span><span>Modeling</span><span>Shading</span></span><b>{esc(md["file"])}</b></p>
    <div class="mk-3d-body"><div class="mk-strip">{"".join(f'<i{" class=is-on" if n == "pointer" else ""}>{mk_icon(n)}</i>' for n in ("pointer", "move", "rotate", "scale", "cube"))}</div>
      <div class="mk-vp"><p class="mk-vp-h"><span>Object Mode</span><span>View</span><span>Select</span><span>Add</span><span>Object</span></p>
        <p class="mk-vp-n">User Perspective<br>(1) Collection | Can</p>
        <div class="mk-floor"></div><i class="mk-shadow"></i>{can}
        <span class="mk-giz"><i class="is-z">Z</i><i class="is-y">Y</i><i class="is-x">X</i></span></div>
      <div class="mk-side"><div class="mk-outl">{outliner}</div>
        <div class="mk-props"><p class="mk-ph-h">{mk_icon("ball")}Label</p><p class="mk-pr-s">Surface</p>
          <p class="mk-f"><span>Base Color</span><span><i class="mk-sw is-lab"></i></span></p>
          <p class="mk-f"><span>Roughness</span><span class="mk-bar"><i style="width:40%"></i>0.40</span></p>
          <p class="mk-f"><span>Metallic</span><span class="mk-bar"><i style="width:0"></i>0.00</span></p></div></div>
    </div>
    <div class="mk-time">{mk_icon("play")}<div class="mk-ruler">{ticks}<i class="mk-play"></i></div></div>
  </div>'''
    spark = f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{MK_SPARK}"/></svg>'
    sw = "".join(f'<i class="mk-swatch{" is-on" if i == 1 else ""}" style="background:{c}"></i>' for i, c in enumerate(("#ff453a", "#ffd60a", "#0a84ff", "#ffffff")))
    menu = "".join(f'<p class="mk-mi{" is-make" if n == "Make It" else ""}"><b>{n}</b><span>{t}</span></p>' for n, t in (
        ("Make It", "Claude makes the change in the app, then tells you here"),
        ("Discuss", "Claude replies with thoughts and options; nothing changes"),
        ("Just Note", "Claude keeps it for later; no reply")))
    data = {k: {"file": v["file"], "thread": v["thread"], "note": v["note"], "reply": v["reply"]} for k, v in m.items()}
    return f'''<div class="mk-view"><div class="mk" lang="en" aria-hidden="true">
  <div class="mk-desk"></div>
  <p class="mk-mbar"><b><span class="is-ph">Photo Editor</span><span class="is-3d">3D Editor</span></b><span>File</span><span>Edit</span><span>View</span><span>Window</span><span>Help</span></p>
  {photo}{model}
  <div class="mk-edge"></div>
  <span class="mk-pin">1</span>
  <div class="mk-card"><p class="mk-head"><span class="mk-pin">1</span><b class="mk-title"></b><span class="mk-res">{mk_icon("archive")}</span></p>
    <div class="mk-msg is-c"><span class="mk-av">CS</span><div><p class="mk-who">Christian<small>now</small></p><p class="mk-t"></p></div></div>
    <div class="mk-msg is-k"><span class="mk-av">{spark}</span><div><p class="mk-who">Claude<small>now</small></p><p class="mk-t"></p></div></div>
    <p class="mk-read"><span class="mk-av">{spark}</span>Claude is reading</p>
    <p class="mk-field"><span class="mk-field-v"></span><i class="mk-caret"></i><span class="mk-ph-t">Reply…</span>{mk_icon("send")}</p></div>
  <div class="mk-tools"><i class="mk-tl">{mk_icon("pointer")}</i><i class="mk-tl">{mk_icon("pen")}</i><i class="mk-tl">{mk_icon("marker")}</i>
    <i class="mk-tl is-cmt">{mk_icon("comment")}</i><span class="mk-sep"></span>{sw}<span class="mk-sep"></span><i class="mk-tl is-frz">{mk_icon("freeze")}</i>
    <span class="mk-send">{mk_icon("send")}Send</span><div class="mk-menu">{menu}</div></div>
  <svg class="mk-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg>
</div></div><script type="application/json" class="mk-data">{json_script(data)}</script>'''


JB_ICONS = {   # on a 24 grid; the tab bar's five are filled like the app's
    "home": ("f", "M12 3.2 2.8 11.4h2.7V20h4.8v-5.6h3.4V20h4.8v-8.6h2.7z"),
    "build": ("f", "M6.5 2.5h7.2l4.8 4.8v13a1.2 1.2 0 0 1-1.2 1.2H6.5a1.2 1.2 0 0 1-1.2-1.2V3.7a1.2 1.2 0 0 1 1.2-1.2zM8.5 12.5h7M8.5 16h5"),
    "track": ("s", "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"),
    "roles": ("f", "M9 4.5h6a1.5 1.5 0 0 1 1.5 1.5v1.5h3.2A1.3 1.3 0 0 1 21 8.8v9.9a1.3 1.3 0 0 1-1.3 1.3H4.3A1.3 1.3 0 0 1 3 18.7V8.8a1.3 1.3 0 0 1 1.3-1.3h3.2V6A1.5 1.5 0 0 1 9 4.5zm.5 3h5V6.5h-5z"),
    "map": ("f", "M3 6.2 8.5 4l7 2.4L21 4.2v13.6L15.5 20l-7-2.4L3 19.8z"),
    "more": ("f", "M12 2.8a9.2 9.2 0 1 1 0 18.4 9.2 9.2 0 0 1 0-18.4z"),
    "search": ("s", "M10.5 4a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM15.5 15.5 20 20"),
    "plus": ("s", "M12 5v14M5 12h14"),
    "check": ("s", "M5.5 12.5l4 4 9-9.5"),
    "chev": ("s", "M9 6l6 6-6 6"),
    "back": ("s", "M15 5l-7 7 7 7"),
    "star": ("f", "M12 3.5l2.6 5.5 6 .7-4.4 4.1 1.2 5.9L12 16.8l-5.4 2.9 1.2-5.9-4.4-4.1 6-.7z"),
    "x": ("s", "M6.5 6.5l11 11M17.5 6.5l-11 11"),
    "res": ("s", "M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM12 9.5a1.8 1.8 0 1 1 0 3.6 1.8 1.8 0 0 1 0-3.6zM9 17c.5-1.6 1.6-2.4 3-2.4s2.5.8 3 2.4"),
    "mail": ("s", "M3.5 6h17v12h-17zM4 6.5l8 6 8-6"),
    "q": ("s", "M9 9a3 3 0 1 1 4.5 2.6c-1 .6-1.5 1.2-1.5 2.4M12 17.5h.01"),
    "queue": ("s", "M4 6h11M4 11h11M4 16h6M14 16.5l2.2 2.2 4-4.4"),
    "cal": ("s", "M4.5 6h15v13.5h-15zM4.5 10h15M8.5 3.5v4M15.5 3.5v4"),
    "alert": ("s", "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zM12 8v5M12 16.2h.01"),
    "chart": ("s", "M4 20h16M7 16v-4M12 16V8M17 16v-6"),
    "inbox": ("s", "M3.5 6h17v12h-17zM4 6.5l8 6 8-6"),
    "reply": ("s", "M3.5 6h17v12h-17zM4 6.5l8 6 8-6"),
    "clock": ("s", "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zM12 7.5V12l3 2"),
    "net": ("s", "M18 4.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM6 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM18 14.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6"),
    "out": ("s", "M8 16 16 8M9.5 8H16v6.5"),
    "list": ("s", "M5 7h14M5 12h14M5 17h9"),
}


def jb_icon(n, cls="jb-i"):
    kind, d = JB_ICONS[n]
    extra = ('<circle cx="7.5" cy="12" r="1.4" class="jb-hole"/><circle cx="12" cy="12" r="1.4" class="jb-hole"/><circle cx="16.5" cy="12" r="1.4" class="jb-hole"/>'
             if n == "more" else "")
    return f'<svg class="{cls} is-{kind}" viewBox="0 0 24 24" aria-hidden="true"><path d="{d}"/>{extra}</svg>'


def jb_mac(inner, title="Job Search AI"):
    """A Mac window around the app, on a desktop; cropped by the card at the bottom."""
    return (f'<div class="jb-desk"></div><div class="jb-win"><p class="jb-tb"><span class="jb-lights"><i></i><i></i><i></i></span><b>{esc(title)}</b></p>'
            f'<div class="jb-app">{inner}</div></div>')


def jb_nav(on):
    """The app's tab bar: a glass pill at the top center on a Mac, along the bottom on a phone."""
    items = (("home", "Home"), ("build", "Build"), ("track", "Track"), ("roles", "Roles"), ("map", "Map"), ("more", "More"))
    return '<nav class="jb-nav">' + "".join(f'<span{" class=is-on" if k == on else ""}>{jb_icon(k)}<b>{t}</b></span>' for k, t in items) + "</nav>"


def jb_iphone(inner, tab):
    """An iPhone, as Budget AI's walkthrough draws it: 393 by 852 points at .79, cropped by the card, panning up when asked."""
    return (f'<div class="jb-stage"></div><div class="jb-phone"><div class="jb-scr">{inner}{jb_nav(tab)}'
            '<div class="jb-island"></div><p class="jb-status"><b>9:41</b><span class="jb-sig"><i></i><i></i><i></i><i></i></span><span class="jb-bat"></span></p>'
            '<i class="jb-touch"></i></div></div>')


JB_CURSOR = '<svg class="jb-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L10 19z"/></svg>'


def demo_jobs(j):
    """Job Search AI, Christian's job search kit, in five short walkthroughs that switch from a Mac to an iPhone and back
    (after the app's own pages, kit.css colors, light or dark with the page). Each is drawn at 720 by 450 and scaled to
    the card; the dots under them pick one. Every person, company, role and number is made up, most of it from the
    app's own demo data (Alex Rivera's sample search)."""
    h, bd, tr, mp = j["home"], j["build"], j["tracker"], j["map"]
    ini, day = esc(j["initials"]), esc(j["day"])
    av = f'<span class="jb-av">{ini}</span>'
    head = lambda t, dek, right="": (f'<header class="jb-head"><p class="jb-eye">{day}</p><h4>{t}</h4><p class="jb-dek">{dek}</p></header>'
                                     f'<p class="jb-hr">{right}{av}</p>')

    # 1. Get Started: who's searching, then the home screen
    people = "".join(f'<span class="jb-pf{" is-me" if i == 0 else ""}"><i class="jb-pav is-{i}">{esc(a)}</i><b>{esc(n)}</b></span>'
                     for i, (a, n) in enumerate(j["profiles"]))

    def tile(t):
        lab, big, sub = t
        if lab == "Replies":
            mid = f'<i class="jb-ring" style="--p:{big.rstrip("%")}"></i><b class="jb-tbig">{esc(big)}</b>'
        elif big.isdigit():
            mid = f'<b class="jb-tbig">{esc(big)}</b>'
        else:
            mid = f'<b>{esc(big)}</b>'
        return f'<span class="jb-tile"><small>{esc(lab)}</small>{mid}<em>{esc(sub)}</em></span>'
    tiles = "".join(tile(t) for t in j["tiles"])
    welcome = (f'<div class="jb-wel"><h3>Job Search AI</h3><p class="jb-who">Who’s searching today?</p><p class="jb-tipk">Tip of the Day</p>'
               f'<p class="jb-tip">{esc(j["tip"])}</p><p class="jb-pfs">{people}</p><p class="jb-again">Run Setup Again</p>'
               f'<div class="jb-tiles"><div class="jb-belt">{tiles}{tiles}</div></div></div>')
    q = h["queue"]
    qcells = "".join(f'<span class="jb-qc{c}"><b data-n="{n}">{n}</b>{t}</span>' for n, t, c in
                     zip(q, ("Queued", "Building", "Built", "Filling", "Needs You"), ("", "", " is-g", "", " is-a")))
    apps_n, bars = h["apps"]
    top = max(bars)
    bars_h = "".join(f'<i style="--h:{b / top:.2f}"{" class=is-now" if k == len(bars) - 1 else ""}></i>' for k, b in enumerate(bars))
    stand_n = sum(s[1] for s in h["stand"])
    stand = "".join(f'<i class="is-{c}" style="--w:{n}"></i>' for _, n, c in h["stand"])
    keys = "".join(f'<span><i class="is-{c}"></i>{esc(t)}<b>{n}</b></span>' for t, n, c in h["stand"])

    def w(cls, icon, title, body, right=""):
        return f'<section class="jb-w {cls}"><p class="jb-wh">{jb_icon(icon)}<b>{title}</b><span>{right}</span></p>{body}</section>'
    widgets = (
        w("is-queue is-amber", "queue", "Queue", f'<p class="jb-qrow">{qcells}</p><p class="jb-needs">Needs you: {esc(h["needs"])}</p>',
          f'2 in the queue {jb_icon("plus")}')
        + w("is-next is-green", "cal", "Up Next", f'<p class="jb-wl"><b>{esc(h["next"][0])}</b><span>{esc(h["next"][1])}</span><span>{esc(h["next"][2])}</span></p>')
        + w("is-apps is-blue", "list", "Applications", f'<b class="jb-big" data-n="2">2</b><p class="jb-ws">this week · {apps_n} in all</p><p class="jb-bars">{bars_h}</p>')
        + w("is-owed is-amber", "alert", "Owed by You", f'<b class="jb-big is-amber" data-n="2">2</b><p class="jb-wl"><b>{esc(h["owed"][0])}</b><span>{esc(h["owed"][1])}</span></p>')
        + w("is-stand is-blue", "chart", "Where Things Stand", f'<p class="jb-stack">{stand}</p><p class="jb-keys">{keys}</p>', f"{stand_n} sent")
        + w("is-replies is-green", "reply", "Replies", f'<p class="jb-rep"><i class="jb-ring" style="--p:{h["replies"][0]}"></i><b class="jb-big" data-n="{h["replies"][0]}">{h["replies"][0]}%</b>'
            f'<span>{esc(h["replies"][1])}</span></p>')
        + w("is-sweep is-teal", "search", "Role Sweep", f'<b class="jb-big" data-n="{h["sweep"][0]}">{h["sweep"][0]}</b><p class="jb-ws">open leads</p>'
            f'<p class="jb-wl"><b>{esc(h["sweep"][1])}</b><span>{esc(h["sweep"][2])}</span></p>', "2 queued")
        + w("is-cmap is-purple", "net", "Company Map", f'<b class="jb-big" data-n="{h["map"][0]}">{h["map"][0]}</b><p class="jb-ws">companies mapped</p>'
            f'<p class="jb-wl"><b>{esc(h["map"][1])}</b><span>{esc(h["map"][2])}</span></p>')
        + w("is-res is-green", "build", "Resumes", f'<b class="jb-big" data-n="{h["resumes"][0]}">{h["resumes"][0]}</b><p class="jb-ws">builds · 2 passed</p>'
            f'<p class="jb-wl"><b>{esc(h["resumes"][1])}</b><span><em>Passed</em> · {esc(h["resumes"][2])}</span></p>', f'2 of 4 passed {jb_icon("plus")}'))
    find = f'<span class="jb-find">{jb_icon("search")}Search</span>'
    home = (f'<div class="jb-home"><div class="jb-scroll">{head("Job Search AI", "Good morning, " + esc(j["name"]) + ".", find)}'
            f'{jb_nav("home")}<div class="jb-grid">{widgets}</div></div></div>')
    s1 = f'<div class="jb-sc is-mac is-1" data-k="0">{jb_mac(welcome + home)}{JB_CURSOR}</div>'

    # 2. the resume builder, on the phone: New Build from a role the sweep found, the rounds of writing and checking, the build
    rows = "".join(f'<p class="jb-brow"><i class="jb-st is-{"ok" if s == "Passed" else "fix"}">{jb_icon("check") if s == "Passed" else "!"}</i>'
                   f'<span><b>{esc(c)}</b><span>{esc(r)}</span><em class="is-{"ok" if s == "Passed" else "fix"}">{esc(s)}</em></span><small>{esc(d)}</small></p>'
                   for c, r, s, d in bd["list"])
    new_row = (f'<p class="jb-brow is-new"><i class="jb-st is-run"><i class="jb-spin"></i>{jb_icon("check")}</i><span><b>{esc(bd["company"])}</b><span>{esc(bd["role"])}</span>'
               f'<em class="jb-bst">Building</em></span><small>Oct 30</small></p>')
    steps = [("posting", "Reading the Posting", ""), ("planned", "Planned", f'{bd["company"]}, {bd["role"]}'),
             ("w1", "Writing", "Claude is writing from your facts"), ("c1", "Checked", "2 problems to fix"),
             ("w2", "Writing, Round 2", f'{bd["chars"]} characters so far'), ("c2", "Checked, Round 2", "Passed every rule that is on"),
             ("done", "Saved", "In its Applications folder")]
    stp = "".join(f'<p class="jb-stp" data-s="{k}"><i class="jb-si"><i></i>{jb_icon("check")}</i><span><b>{esc(t)}</b><small>{esc(s)}</small></span></p>' for k, t, s in steps)
    sheet = (f'<div class="jb-sheet"><i class="jb-grab"></i><p class="jb-sht"><span class="is-new">New Build</span><span class="is-run">Building</span></p>'
             f'<div class="jb-form"><p class="jb-gl">Posting</p><div class="jb-grp"><p class="jb-fr"><span>From</span><span class="jb-seg"><i class="is-on">Role Sweep</i><i>A Link</i></span></p>'
             f'<p class="jb-fr"><span>Role</span><span class="jb-pop">{esc(bd["company"])}, {esc(bd["role"])}</span></p></div>'
             f'<p class="jb-gl">Layout</p><div class="jb-grp"><p class="jb-fr"><span>Template</span><span class="jb-pop">Classic (Suggested)</span></p>'
             f'<p class="jb-fr"><span>Cover Letter</span><i class="jb-sw is-on"></i></p></div>'
             '<p class="jb-note">Claude reads the posting, writes from your facts, checks the pages against your writing rules and fixes what it can, up to 3 rounds.</p></div>'
             f'<div class="jb-run"><p class="jb-rolel">{esc(bd["company"])}, {esc(bd["role"])}</p>{stp}</div>'
             '<p class="jb-shf"><span class="jb-b is-x">Cancel</span><span class="jb-b is-go"><span class="is-new">Build</span><span class="is-run">Open Build</span></span></p></div>')
    sc = bd["score"]
    detail = (f'<div class="jb-detail"><p class="jb-backl">{jb_icon("back")}Builds</p><h5>{esc(bd["company"])}</h5><p class="jb-dek">{esc(bd["role"])}</p>'
              f'<div class="jb-score"><i class="jb-ring is-big" style="--p:{sc}"><b>{sc}%</b></i><p class="jb-kv"><span><small>Status</small><b class="is-ok">{jb_icon("check")}Passed</b></span>'
              f'<span><small>Keywords</small><b>{esc(bd["keywords"])}</b></span><span><small>Pages</small><b>{esc(bd["pages"])}</b></span>'
              f'<span><small>Round</small><b>{esc(bd["round"])}</b></span></p></div><p class="jb-why">{esc(bd["why"])}</p>'
              '<p class="jb-lab3">What QA Caught</p><p class="jb-why is-m">Nothing. Every writing rule that is on passed.</p>'
              '<p class="jb-lab3">The Page</p><p class="jb-seg is-sm"><i class="is-on">Resume</i><i>Cover Letter</i></p>'
              f'<div class="jb-paper"><b>{esc(j["name"])} Rivera</b>' + '<i></i>' * 9 + '</div></div>')
    resumes = (f'<div class="jb-pg jb-res"><p class="jb-ptop"><span class="jb-circ">{jb_icon("plus")}</span>{av}</p><p class="jb-eye">{day}</p><h4>Resumes</h4>'
               f'<p class="jb-dek">5 builds · 3 passed · Classic template</p><p class="jb-gl is-list">Builds</p><div class="jb-blist">{new_row}{rows}</div></div>')
    s2 = f'<div class="jb-sc is-ios is-2" data-k="1">{jb_iphone(resumes + detail + sheet, "build")}</div>'

    # 3. the application tracker: a thing owed gets done, then the live pipeline, booked and waiting
    stats = "".join(f'<span><b>{esc(v)}</b>{esc(t)}</span>' for v, t in tr["stats"])
    brief = "".join(f'<p class="jb-bc{" is-fu" if k == "Follow Up" else ""}{" is-gone" if i == 0 else ""}"><small>{jb_icon("clock" if k == "Follow Up" else "alert")}{esc(k)}</small>'
                    f'<b>{esc(c)}</b><span>{esc(t)}</span></p>' for i, (k, c, t) in enumerate(tr["brief"]))
    owed = "".join(f'<p class="jb-or{" is-first" if i == 0 else ""}"><i class="jb-tick">{jb_icon("check")}</i><span><b>{esc(t)}</b><small>{esc(s)}</small></span><em>{esc(d)}</em></p>'
                   for i, (t, s, d) in enumerate(tr["owed"]))
    pipe = lambda rs, cls: "".join(f'<p class="jb-pr {cls}"><i></i><span><b>{esc(c)}</b><small>{esc(r)}</small></span><span class="jb-prn">{esc(n)}</span><em>{esc(d)}</em></p>' for c, r, n, d in rs)
    tracker = (f'{head("Application Tracker", "Day 71 · Updated today at 9:05am", "<span class=jb-circ>" + jb_icon("plus") + "</span>")}{jb_nav("track")}'
               f'<div class="jb-scroll"><p class="jb-tabs"><span class="jb-seg"><i class="is-on">Briefing</i><i>Log</i><i>Analysis</i><i>Prep</i></span></p>'
               f'<p class="jb-subs"><i class="is-on">Right Now</i><i>Owed</i><i class="jb-pipe">Pipeline</i></p><p class="jb-stats">{stats}</p>'
               f'<h5>Briefing</h5><div class="jb-brief">{brief}</div>'
               f'<h5 class="jb-sh">Owed by You<b class="jb-oc" data-n="2">2</b></h5><p class="jb-cap">Asks someone is waiting on.</p><div class="jb-owed">{owed}</div>'
               f'<h5 class="jb-sh">Live Pipeline<b>8</b></h5><p class="jb-cap">Roles past the application stage.</p>'
               f'<p class="jb-seg is-sm jb-pseg"><i class="is-on" data-p="booked">Booked</i><i data-p="waiting">Waiting</i><i>Quiet</i></p>'
               f'<div class="jb-pipeL">{pipe(tr["booked"], "is-booked")}{pipe(tr["waiting"], "is-waiting")}</div></div>')
    s3 = f'<div class="jb-sc is-mac is-3" data-k="2">{jb_mac(tracker)}{JB_CURSOR}</div>'

    # 4. the role sweeper, on the phone: the morning sweep lands, one role goes in the queue, one is passed
    def role(i, r):
        t, c, pay, lane, call, star = r
        return (f'<div class="jb-role{" is-first" if i == 0 else ""}{" is-second" if i == 1 else ""}" style="--i:{i}">{jb_icon("star", "jb-i jb-star") if star else ""}'
                f'<p class="jb-rt"><b>{esc(t)}</b><small>Fri, 10/30</small></p><p class="jb-rc">{esc(c)} · {esc(pay)} · {esc(lane)}</p>'
                f'<p class="jb-call"><span class="jb-tag">New</span><span class="jb-tag is-q">Queue</span>{esc(call)}</p>'
                f'<p class="jb-bsw"><i class="is-x">{jb_icon("x")}</i><i class="is-r">{jb_icon("res")}</i><i class="is-cl">{jb_icon("plus")}{jb_icon("mail")}</i><i class="is-qq">{jb_icon("q")}</i></p></div>')
    roles = "".join(role(i, r) for i, r in enumerate(j["roles"]))
    sweep = (f'<div class="jb-pg jb-sweep"><p class="jb-ptop">{av}</p><p class="jb-eye">{day}</p><h4>Role Sweep</h4><p class="jb-dek">Last sweep today at 9am · <span class="jb-nnew" data-n="{len(j["roles"])}">{len(j["roles"])}</span> new</p>'
             f'<p class="jb-chips"><span><b class="jb-found" data-n="{len(j["roles"])}">{len(j["roles"])}</b>Found in the Last 24 Hours</span><span><b class="jb-queued" data-n="3">3</b>Queued for Claude</span></p>'
             f'<p class="jb-srch"><span class="jb-find">{jb_icon("search")}Search</span></p>'
             f'<p class="jb-seg is-full"><i class="is-on">Open</i><i>Queue</i><i>Applied</i><i>All</i></p><div class="jb-roles">{roles}</div></div>')
    s4 = f'<div class="jb-sc is-ios is-4" data-k="3">{jb_iphone(sweep, "roles")}</div>'

    # 5. the company mapper: the morning's finds, a map of lookalikes around a company, one with a role found
    finds = "".join(f'<p class="jb-fc" style="--i:{i}"><b><i class="is-{col}"></i>{esc(n)}{jb_icon("out")}</b><span>{esc(d)}</span><small>{esc(s)}<em>{esc(o)}</em></small></p>'
                    for i, (n, d, s, o, col) in enumerate(mp["finds"]))
    nodes = "".join(f'<i class="jb-node is-{c}" style="--a:{a}deg;--i:{i}">{t}</i>' for i, (a, c, t) in enumerate(
        ((-90, "green", "Q"), (-36, "green is-hit", ""), (18, "green", ""), (72, "slate", ""), (126, "sky", ""), (180, "purple", ""), (234, "ring", ""))))
    pk = mp["pick"]
    cmap = (f'{head("Company Map", "<span class=jb-mapn data-n=90>90</span> companies mapped · Updated today at 7:02am", "<span class=jb-circ>" + jb_icon("plus") + "</span>")}{jb_nav("map")}'
            f'<div class="jb-scroll"><h5 class="jb-sh">Latest Finds<span>4 companies</span></h5><p class="jb-cap">Added today by the Company Mapper. Click one to open its job board.</p>'
            f'<div class="jb-finds">{finds}</div><p class="jb-led"><span>Led By</span><span class="jb-pop">{esc(mp["center"])} (7)</span></p>'
            f'<div class="jb-orbit"><i class="jb-glow"></i><i class="jb-ringd"></i>{nodes}<span class="jb-hub"><b>{esc(mp["center"][0])}</b></span>'
            f'<p class="jb-hubn"><b>{esc(mp["center"])}</b><span>7 companies</span></p>'
            f'<div class="jb-tipc"><b>{esc(pk[0])}</b><span>{esc(pk[1])}</span><small>{esc(pk[2])}</small><em><i></i>1 Role Found</em>'
            f'<p><span>Open Board</span><span class="jb-ors">Open Role Sweep</span></p></div></div></div>')
    s5 = f'<div class="jb-sc is-mac is-5" data-k="4">{jb_mac(cmap)}{JB_CURSOR}</div>'

    dots = "".join(f'<button type="button" class="jb-dot{" is-on" if k == 0 else ""}" data-k="{k}" aria-label="Demo {k + 1} of 5: {esc(n)}"'
                   f'{" aria-current=true" if k == 0 else ""}><i></i></button>' for k, n in enumerate(j["scenes"]))
    return (f'<div class="jb-view"><div class="jb" lang="en" aria-hidden="true">{s1}{s2}{s3}{s4}{s5}</div></div>'
            f'<div class="jb-dots" role="group" aria-label="Job Search AI demos">{dots}</div>')


def demo_tools(b, root):
    cards = []
    for t in b["tools"]:
        v = lambda f: f'{root}assets/ai/{f}?v={asset_version("assets/ai/" + f)}'
        tag = f'<span class="tl-tag">{esc(t["tag"])}</span>' if t.get("tag") else ""   # the name is not final
        if t.get("phone"):
            cta = (f'<a class="tl-cta" href="{esc(t["href"])}" target="_blank" rel="noopener">{esc(t["cta"])}</a>' if t.get("href")
                   else '<span class="tl-cta is-soon">Coming soon</span>')
            cards.append(f'<li class="tl-card"><div class="tl-screen bg-screen">{demo_budget(t["phone"])}{AI_PAUSE}</div>'
                         f'<div class="tl-body"><h3>{esc(t["name"])}{tag}</h3><p>{esc(t["line"])}</p>{cta}</div></li>')
            continue
        if t.get("jobs"):
            cta = (f'<a class="tl-cta" href="{esc(t["href"])}" target="_blank" rel="noopener">{esc(t["cta"])}</a>' if t.get("href")
                   else '<span class="tl-cta is-soon">Coming soon</span>')
            cards.append(f'<li class="tl-card"><div class="tl-screen jb-screen">{demo_jobs(t["jobs"])}{AI_PAUSE}</div>'
                         f'<div class="tl-body"><h3>{esc(t["name"])}{tag}</h3><p>{esc(t["line"])}</p>{cta}</div></li>')
            continue
        if t.get("markup"):
            cta = (f'<a class="tl-cta" href="{esc(t["href"])}" target="_blank" rel="noopener">{esc(t["cta"])}</a>' if t.get("href")
                   else '<span class="tl-cta is-soon">Coming soon</span>')
            cards.append(f'<li class="tl-card"><div class="tl-screen mk-screen">{demo_markup(t["markup"])}{AI_PAUSE}</div>'
                         f'<div class="tl-body"><h3>{esc(t["name"])}{tag}</h3><p>{esc(t["line"])}</p>{cta}</div></li>')
            continue
        if t.get("walk"):
            cards.append(f'<li class="tl-card"><div class="tl-screen hh-screen">{demo_heardhum(t["walk"], root)}{AI_PAUSE}</div>'
                         f'<div class="tl-body"><h3>{esc(t["name"])}</h3><p>{esc(t["line"])}</p>'
                         f'<a class="tl-cta" href="{esc(t["href"])}" target="_blank" rel="noopener">{esc(t["cta"])}</a></div></li>')
            continue
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
                     f'<div class="tl-body"><h3>{esc(t["name"])}{tag}</h3><p>{esc(t["line"])}</p>{cta}</div></li>')
    return f'<div class="wrap ai-demo ai-tools" data-demo="tools"><ul class="tl-grid">{"".join(cards)}</ul></div>'


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
    if b.get("step"):   # which step of the loop at the top this section shows: a pill in its section's color, back to the loop
        n, name = [x.strip() for x in b["step"].split("\u00b7")]
        words = words.replace("<h2>", f'<a class="ai-step" href="#machine" aria-label="Step {esc(n)} of the loop, {esc(name)}: back to the loop">'
                                       f'<span>{esc(n)}</span><span>{esc(name)}</span></a><h2>', 1)
    kind = b.get("demo")
    if not kind:
        return words
    fig = {"geo": demo_geo}.get(kind)
    if kind in ("localize", "board", "cut", "fan", "tools", "machine"):
        return words + {"machine": demo_machine, "localize": demo_localize, "board": demo_board, "cut": demo_cut, "fan": demo_fan, "tools": demo_tools}[kind](b, root)
    return words + fig(b)


def render_ai(page, site, media):
    """The hidden AI page (content/ai.json): a case study's frame (banner, hero, lede, sections, the way on),
    with a demo under most sections. In the switcher as AI Workflows."""
    root = "../"
    hero = page["hero"]
    # it opens as a category page does (title, tools, description, a paragraph), and the content machine's loop
    # comes straight after as the first thing shown
    opening = next(b for b in page["blocks"] if b["demo"] == "machine")
    parts = [f'''<script src="{root}assets/js/ai-page.js?v={asset_version("assets/js/ai-page.js")}" defer></script>
<section class="wrap cat-text is-lead is-first ai-head">
  <h1>{esc(hero["title"])}</h1>
  <p class="tools">{esc(page["tools"])}</p>
  <p class="kicker-italic">{esc(page["lede"])}</p>
  {paragraphs(opening["p"])}
</section>''']
    parts += [ai_block(b, root) for b in page["blocks"]]
    # the way back sits in the footer, beside Back to Top
    page = {**page, "type": "case", "nav_active": "ai", "body_class": "case-v2 cat-v2 ai-page",
            "footer_back": {"href": "", "label": "Back to Case Studies"}}
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
