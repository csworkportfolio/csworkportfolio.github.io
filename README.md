# Christian Sanchez — Portfolio

A static site rebuilt from the Wix portfolio at csworkportfolio.wixsite.com/home.
It needs no hosting service beyond plain files and runs on GitHub Pages as-is.

## Layout

| Path | What it is |
|---|---|
| `content/*.json` | All page text, gallery order, captions and links. Edit these. |
| `tools/build.py` | Turns the content into HTML and optimizes media. |
| `assets/` | Stylesheet and the gallery/lightbox script. |
| `media/` | Optimized images and videos (generated; `manifest.json` tracks them). |
| `files/` | PDFs and slide decks linked from galleries. |
| `index.html`, `*/index.html` | The generated pages. Don't edit by hand; rebuild instead. |

Page addresses match the old Wix ones: `/nike/`, `/graphic-design/`, `/video-work/` and so on.

## Editing

1. Change text or gallery order in `content/`.
   - A gallery entry can be a file name (`"Nike 3.png"`), an object with
     `src`, `title`, `tools`, `desc` and `link`, or a video: `{ "v": "<Vimeo or YouTube id>" }`.
   - New videos also need an entry under `videos` in `content/site.json` (size and thumbnail).
2. Rebuild:

   ```bash
   python3 tools/build.py --src "/path/to/original/media"
   ```

   Only new or changed media needs the originals; everything else comes from `media/`.
   Requires Python 3 with Pillow, and `ffmpeg` for GIFs and video.
3. Preview: `python3 -m http.server 8411` and open http://localhost:8411.

## Publishing on GitHub Pages

Push the repository, then in **Settings → Pages** choose *Deploy from a branch*, branch `main`, folder `/ (root)`.
For a custom domain, add it on that same page and point the domain's DNS at GitHub.
