// Gallery sliders (set up like the Wix galleries they replace) and the lightbox.
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const canHover = window.matchMedia("(hover: hover)").matches;
  const strips = [];
  let lightboxOpen = false;

  // ---------- looping GIF-videos: load and play only when on screen ----------

  const loopObserver = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
        for (const e of entries) {
          const v = e.target;
          if (e.isIntersecting) {
            if (!v.src && v.dataset.src) v.src = v.dataset.src;
            if (!reduceMotion) v.play().catch(() => {});
          } else if (!v.paused) {
            v.pause();
          }
        }
      }, { rootMargin: "200px" })
    : null;

  // ---------- category header: the underlined field changes every 5 seconds ----------

  document.querySelectorAll(".rotator").forEach((rot) => {
    const words = [...rot.querySelectorAll(".rot-word")];
    if (words.length < 2) return;
    let i = 0;
    // The header keeps one height whichever phrase is showing: measure the sentence with each phrase in place
    // and reserve room for the tallest, so a longer phrase rewraps the line without the band growing.
    const sub = rot.closest(".cat-hero-sub");
    function reserve() {
      if (!sub) return;
      sub.style.minHeight = "";
      rot.style.transition = "none";
      // phones: "<phrase> built to perform," stays on one line, so the type shrinks just enough for the
      // longest phrase to fit (down to 12px; past that the line may wrap rather than run off the screen)
      const first = sub.querySelector(".sub-a");
      sub.style.fontSize = "";
      if (first) first.style.whiteSpace = "";
      // where the whole sentence fits on one line with every phrase (wider phones, small tablets), keep it on one
      sub.classList.remove("is-one-line");
      if (first && getComputedStyle(first).display === "block") {
        sub.classList.add("is-one-line");
        for (const w of words) {
          rot.style.width = w.offsetWidth + "px";
          if (sub.scrollWidth > sub.clientWidth + 1) { sub.classList.remove("is-one-line"); break; }
        }
      }
      if (first && getComputedStyle(first).display === "block") {
        const base = parseFloat(getComputedStyle(sub).fontSize);
        let need = 0;
        for (const w of words) {
          rot.style.width = w.offsetWidth + "px";
          need = Math.max(need, first.scrollWidth);
        }
        const room = sub.clientWidth;
        if (need > room) {
          const size = Math.floor(base * room / need * 0.97 * 10) / 10;  // a little slack for rounding
          sub.style.fontSize = Math.max(12, size) + "px";
          if (size < 12) first.style.whiteSpace = "normal";
        }
      }
      let tallest = 0;
      for (const w of words) {
        rot.style.width = w.offsetWidth + "px";
        tallest = Math.max(tallest, sub.offsetHeight);
      }
      rot.style.width = words[i].offsetWidth + "px";
      void rot.offsetWidth;
      rot.style.transition = "";
      sub.style.minHeight = tallest + "px";
    }
    reserve();
    window.addEventListener("resize", reserve);
    if (document.fonts) document.fonts.ready.then(reserve);
    setInterval(() => {
      if (document.hidden) return;
      const cur = words[i];
      i = (i + 1) % words.length;
      rot.style.width = cur.offsetWidth + "px";  // pin the old width, then ease to the new one
      void rot.offsetWidth;
      rot.style.width = words[i].offsetWidth + "px";
      cur.classList.remove("is-on");
      cur.classList.add("is-off");
      words[i].classList.remove("is-off");
      words[i].classList.add("is-on");
      setTimeout(() => cur.classList.remove("is-off"), 500);
    }, 5000);
  });

  // ---------- Read More shine: lights up as each case row scrolls into view ----------

  const shines = document.querySelectorAll(".shine");
  if (shines.length) {
    if ("IntersectionObserver" in window) {
      const shineObserver = new IntersectionObserver((entries) => {
        for (const e of entries) e.target.classList.toggle("is-lit", e.isIntersecting);
      }, { rootMargin: "0px 0px -15% 0px" });
      shines.forEach((s) => shineObserver.observe(s));
    } else {
      shines.forEach((s) => s.classList.add("is-lit"));
    }
  }

  function watchLoops(root) {
    root.querySelectorAll("video[data-src]").forEach((v) => {
      if (loopObserver) loopObserver.observe(v);
      else v.src = v.dataset.src;
    });
  }

  // ---------- slider ----------
  // Each slider reads its Wix settings from data attributes: data-speed is the
  // continuous auto-scroll speed in px/s (0 = still) and data-loop makes it wrap.
  // Arrows step one item at a time with Wix's slide easing.

  const ease = (t) => { // cubic-bezier(.46,.1,.25,1), solved numerically
    let lo = 0, hi = 1, x = t;
    for (let i = 0; i < 20; i++) {
      x = (lo + hi) / 2;
      const bx = 3 * x * (1 - x) * (1 - x) * 0.46 + 3 * x * x * (1 - x) * 0.25 + x * x * x;
      if (bx < t) lo = x; else hi = x;
    }
    return 3 * x * (1 - x) * (1 - x) * 0.1 + 3 * x * x * (1 - x) + x * x * x;
  };

  function initStrip(el) {
    const viewport = el.querySelector(".strip-viewport");
    const track = el.querySelector(".strip-track");
    const prev = el.querySelector(".strip-prev");
    const next = el.querySelector(".strip-next");
    const originals = [...track.children];
    const s = {
      el, viewport, speed: reduceMotion ? 0 : Number(el.dataset.speed || 0), v: 0, hover: false,
      loops: el.hasAttribute("data-loop"), loop: 0, pos: 0, lastSet: -1,
      pause: new Set(), resumeTimer: 0, visible: true, anim: 0,
    };

    const maxScroll = () => viewport.scrollWidth - viewport.clientWidth;

    function arrows() {
      if (el.classList.contains("is-static")) return;
      const x = viewport.scrollLeft;
      prev.hidden = !s.loop && x <= 1;
      next.hidden = !s.loop && x >= maxScroll() - 1;
    }

    function measure() {
      track.querySelectorAll("[data-clone]").forEach((n) => {
        if (autoObserver) n.querySelectorAll(".tile[data-video]").forEach((v) => autoObserver.unobserve(v));
        n.remove();
      });
      el.classList.remove("is-static");
      prev.hidden = next.hidden = false;
      s.loop = 0;
      if (track.scrollWidth <= viewport.clientWidth + 2) {
        el.classList.add("is-static");
        return;
      }
      if (s.loops) {
        for (const li of originals) {
          const c = li.cloneNode(true);
          c.dataset.clone = "";
          c.setAttribute("aria-hidden", "true");
          c.querySelectorAll("button").forEach((b) => (b.tabIndex = -1));
          c.querySelectorAll(".tile-preview").forEach((f) => f.remove());
          // the copies' videos autoplay too, so the loop doesn't turn them into still posters
          if (autoObserver && el.dataset.play === "auto" && !reduceMotion) c.querySelectorAll(".tile[data-video]").forEach((v) => autoObserver.observe(v));
          track.appendChild(c);
        }
        watchLoops(track);
        s.loop = track.querySelector("[data-clone]").offsetLeft - originals[0].offsetLeft;
      }
      s.pos = viewport.scrollLeft;
      arrows();
    }

    function hold(reason, ms) {
      s.pause.add(reason);
      if (ms) {
        clearTimeout(s.resumeTimer);
        s.resumeTimer = setTimeout(() => s.pause.delete(reason), ms);
      }
    }

    // hovering slows the slider to HOVER_SPEED instead of stopping it
    el.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") s.hover = true; });
    el.addEventListener("pointerleave", () => { s.hover = false; });
    el.addEventListener("focusin", () => hold("focus"));
    el.addEventListener("focusout", () => s.pause.delete("focus"));
    viewport.addEventListener("touchstart", () => hold("touch"), { passive: true });
    viewport.addEventListener("touchend", () => hold("touch", 3500), { passive: true });
    viewport.addEventListener("wheel", (e) => { if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) hold("wheel", 2500); }, { passive: true });

    viewport.addEventListener("scroll", () => {
      arrows();
      const x = viewport.scrollLeft;
      if (s.anim || Math.abs(x - s.lastSet) <= 1) return; // our own movement
      if (s.loop) { // keep a looping slider seamless when a person scrolls it
        if (x >= s.loop) viewport.scrollLeft = x - s.loop;
        else if (x <= 0) viewport.scrollLeft = x + s.loop;
      }
      s.pos = viewport.scrollLeft;
    }, { passive: true });

    function glide(to) {
      cancelAnimationFrame(s.anim);
      const from = viewport.scrollLeft;
      const dur = reduceMotion ? 0 : 600;
      const t0 = performance.now();
      const frame = (t) => {
        const k = dur ? Math.min((t - t0) / dur, 1) : 1;
        viewport.scrollLeft = from + (to - from) * ease(k);
        s.lastSet = viewport.scrollLeft;
        if (k < 1) s.anim = requestAnimationFrame(frame);
        else { s.anim = 0; s.pos = viewport.scrollLeft; arrows(); }
      };
      s.anim = requestAnimationFrame(frame);
    }

    function step(dir) {
      hold("arrow", 4000);
      const items = [...track.children];
      const x = viewport.scrollLeft;
      const lefts = items.map((li) => li.offsetLeft - track.offsetLeft);
      let to;
      if (dir > 0) to = lefts.find((l) => l > x + 2);
      else to = [...lefts].reverse().find((l) => l < x - 2);
      if (to == null) to = dir > 0 ? maxScroll() : 0;
      if (s.loop) { // wrap smoothly through the cloned copy
        if (dir < 0 && x <= 2) { viewport.scrollLeft = x + s.loop; return step(dir); }
        if (dir > 0 && to >= s.loop) { viewport.scrollLeft = x - s.loop; return step(dir); }
      }
      glide(Math.max(0, Math.min(to, maxScroll())));
    }
    prev.addEventListener("click", () => step(-1));
    next.addEventListener("click", () => step(1));

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([e]) => (s.visible = e.isIntersecting)).observe(el);
      // Fetch every tile once the slider is close to the screen, so tiles never
      // arrive blank as they glide in (lazy loading inside a scrolled box is unreliable).
      const near = new IntersectionObserver(([e]) => {
        if (!e.isIntersecting) return;
        track.querySelectorAll('img[loading="lazy"]').forEach((img) => (img.loading = "eager"));
        near.disconnect();
      }, { rootMargin: "600px 0px" });
      near.observe(el);
    }

    measure();
    let w = viewport.clientWidth;
    window.addEventListener("resize", () => {
      if (viewport.clientWidth !== w) { w = viewport.clientWidth; measure(); }
    });
    // Images without known sizes could change the width once loaded.
    window.addEventListener("load", measure, { once: true });
    strips.push(s);
  }

  const HOVER_SPEED = 25;  // px/s while the pointer rests on a slider
  let last = 0;
  function tick(t) {
    const dt = last ? Math.min((t - last) / 1000, 0.1) : 0;
    last = t;
    for (const s of strips) {
      if (!s.speed || s.anim || !s.visible || s.pause.size || lightboxOpen) continue;
      if (s.el.classList.contains("is-static")) continue;
      const target = s.hover ? Math.min(s.speed, HOVER_SPEED) : s.speed;
      s.v = s.v ? s.v + (target - s.v) * Math.min(1, dt * 4) : target;  // ease between paces over about half a second
      s.pos += s.v * dt;
      if (s.loop && s.pos >= s.loop) s.pos -= s.loop;
      const end = s.viewport.scrollWidth - s.viewport.clientWidth;
      if (!s.loop && s.pos >= end) { s.pos = end; } // non-looping Wix sliders stop at the end
      s.viewport.scrollLeft = s.pos;
      s.lastSet = s.viewport.scrollLeft;
    }
    requestAnimationFrame(tick);
  }

  // ---------- videos inside sliders ----------

  function previewUrl(kind, id) { // muted, chrome-free autoplay for hover previews
    return kind === "vimeo"
      ? `https://player.vimeo.com/video/${id}?background=1&dnt=1`
      : `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&mute=1&controls=0&loop=1&playlist=${id}&modestbranding=1&rel=0`;
  }

  // A silent preview player sized to the video's own shape and centered in the
  // tile, the way Wix fits vertical and square videos into its 16:9 tiles.
  function addPreview(tileEl) {
    if (tileEl.querySelector(".tile-preview")) return null;
    const [kind, id] = tileEl.dataset.video.split(":");
    const vw = Number(tileEl.dataset.vw), vh = Number(tileEl.dataset.vh);
    const tw = tileEl.clientWidth, th = tileEl.clientHeight;
    const k = Math.min(tw / vw, th / vh);
    const frame = Object.assign(document.createElement("iframe"), { src: previewUrl(kind, id), title: "", tabIndex: -1 });
    frame.className = "tile-preview";
    frame.setAttribute("allow", "autoplay; encrypted-media");
    frame.setAttribute("aria-hidden", "true");
    Object.assign(frame.style, {
      width: `${Math.round(vw * k)}px`, height: `${Math.round(vh * k)}px`,
      left: `${Math.round((tw - vw * k) / 2)}px`, top: `${Math.round((th - vh * k) / 2)}px`,
    });
    tileEl.appendChild(frame);
    return frame;
  }
  const removePreview = (tileEl) => tileEl.querySelector(".tile-preview")?.remove();

  // Wix "play on hover": the video runs silently while the pointer rests on it.
  function hoverPreview(tileEl) {
    tileEl.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") addPreview(tileEl); });
    tileEl.addEventListener("pointerleave", () => removePreview(tileEl));
  }

  // Wix "autoplay": the video runs silently whenever it is on screen.
  const autoObserver = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
        for (const e of entries) {
          if (e.isIntersecting) addPreview(e.target);
          else removePreview(e.target);
        }
      }, { threshold: 0.3 })
    : null;

  // The video rows play in place, with controls, when clicked.
  function playInline(tileEl, item) {
    if (tileEl.querySelector(".tile-player")) return;
    if (autoObserver) autoObserver.unobserve(tileEl);
    removePreview(tileEl);
    const f = document.createElement("iframe");
    f.className = "tile-player";
    f.src = embedUrl(item);
    f.title = item.title || "Video player";
    f.setAttribute("allow", "autoplay; fullscreen; picture-in-picture; encrypted-media");
    f.setAttribute("allowfullscreen", "");
    tileEl.appendChild(f);
    tileEl.classList.add("is-playing");
  }

  // ---------- lightbox ----------

  const dialog = document.querySelector(".lightbox");
  const lbMedia = dialog && dialog.querySelector(".lb-media");
  const lbCaption = dialog && dialog.querySelector(".lb-caption");
  let current = { items: [], index: 0 };

  function el(tag, attrs = {}, text) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === true) n.setAttribute(k, "");
      else if (v !== false && v != null) n.setAttribute(k, v);
    }
    if (text) n.textContent = text;
    return n;
  }

  function embedUrl(item) {
    if (item.type === "vimeo") {
      return `https://player.vimeo.com/video/${item.id}?autoplay=1&title=0&byline=0&portrait=0&dnt=1`;
    }
    return `https://www.youtube-nocookie.com/embed/${item.id}?autoplay=1&rel=0&modestbranding=1`;
  }

  function sizeFrame() {
    const f = lbMedia.querySelector("iframe");
    if (!f) return;
    const item = current.items[current.index];
    // desktop: the media column sizes to its content, so measure the room it may take (--lb-room) instead
    const boxW = matchMedia("(max-width: 900px)").matches ? lbMedia.clientWidth : window.innerWidth - 176 - 360 - 56;
    // on phones the media box grows with its content, so cap videos at 72% of the screen height instead
    const stacked = matchMedia("(max-width: 900px)").matches;
    const boxH = stacked ? window.innerHeight * 0.72 : window.innerHeight - 110;
    const ar = item.vw / item.vh;
    let w = boxW, h = boxW / ar;
    if (h > boxH) { h = boxH; w = h * ar; }
    f.style.width = `${Math.floor(w)}px`;
    f.style.height = `${Math.floor(h)}px`;
  }

  // ---------- PDFs in the lightbox ----------
  // A card that links to a PDF (case studies, articles, class projects) opens the document itself in the
  // lightbox: every page rendered by PDF.js into one scrolling column, pages drawn as they come into view.

  const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/";
  let pdfjs = null;
  const isPdf = (item) => item.link && /\.pdf$/i.test(item.link.href);

  function loadPdfJs() {
    if (!pdfjs) {
      pdfjs = new Promise((resolve, reject) => {
        const s = el("script", { src: PDFJS + "pdf.min.js" });
        s.onload = () => {
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.js";
          resolve(window.pdfjsLib);
        };
        s.onerror = () => { pdfjs = null; reject(new Error("PDF.js failed to load")); };
        document.head.append(s);
      });
    }
    return pdfjs;
  }

  // Click a page to zoom to 150% around the pointer; the zoom follows the mouse, and a second click (or
  // leaving the page) zooms back out. On touch, a tap zooms in at that spot and the next tap zooms out.
  const ZOOM = 1.5;
  function zoomable(slot) {
    const aim = (e) => {
      const r = slot.getBoundingClientRect();
      slot.style.setProperty("--zx", `${((e.clientX - r.left) / r.width) * 100}%`);
      slot.style.setProperty("--zy", `${((e.clientY - r.top) / r.height) * 100}%`);
    };
    slot.addEventListener("click", (e) => {
      aim(e);
      slot.classList.toggle("is-zoomed");
    });
    slot.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" && slot.classList.contains("is-zoomed")) aim(e); });
    slot.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") slot.classList.remove("is-zoomed"); });
  }

  async function showPdf(item, box) {
    const lib = await loadPdfJs();
    const doc = await lib.getDocument(new URL(item.link.href, location.href).href).promise;
    if (current.items[current.index] !== item || !box.isConnected) return;
    const first = await doc.getPage(1);
    const base = first.getViewport({ scale: 1 });
    const pages = [];
    for (let n = 1; n <= doc.numPages; n++) {
      const slot = el("div", { class: "lb-pdf-page", "aria-label": `Page ${n} of ${doc.numPages}`, role: "img" });
      slot.style.aspectRatio = `${base.width} / ${base.height}`;
      slot.dataset.page = n;
      zoomable(slot);
      pages.push(slot);
    }
    box.replaceChildren(...pages);
    box.classList.add("is-ready");
    const draw = async (slot) => {
      if (slot.dataset.drawn) return;
      slot.dataset.drawn = "1";
      const page = await doc.getPage(Number(slot.dataset.page));
      const vp1 = page.getViewport({ scale: 1 });
      // sharp at the screen's pixel density, but under ~12 MP so tall one-page PDFs stay within iOS canvas limits
      // drawn at 1.5x so the zoom stays crisp
      const scale = Math.min((slot.clientWidth * (window.devicePixelRatio || 1) * ZOOM) / vp1.width,
        Math.sqrt(12e6 / (vp1.width * vp1.height)));
      const vp = page.getViewport({ scale });
      const canvas = el("canvas", { width: Math.floor(vp.width), height: Math.floor(vp.height) });
      slot.style.aspectRatio = `${vp1.width} / ${vp1.height}`;
      slot.append(canvas);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
    };
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { io.unobserve(e.target); draw(e.target); }
    }, { root: box, rootMargin: "600px 0px" });
    pages.forEach((p) => io.observe(p));
  }

  function render() {
    const item = current.items[current.index];
    const inner = dialog.querySelector(".lb-inner");
    if (inner) inner.scrollTop = 0;  // each piece starts at its top when the phone layout scrolls
    lbMedia.replaceChildren();
    lbCaption.replaceChildren();
    const label = item.title || "";

    if (item.type === "image" && isPdf(item)) {
      // the cover shows while the document loads; if the PDF can't be shown, the cover stays
      const box = el("div", { class: "lb-pdf", tabindex: "0", "aria-label": `${label || "Document"}: scroll to read` });
      box.append(el("img", { src: item.full, alt: label, width: item.w, height: item.h }));
      lbMedia.append(box);
      showPdf(item, box).catch(() => {});
    } else if (item.type === "image") {
      lbMedia.append(el("img", { src: item.full, alt: label, width: item.w, height: item.h }));
    } else if (item.type === "loop") {
      const v = el("video", { src: item.src, poster: item.thumb, muted: true, loop: true, playsinline: true, autoplay: !reduceMotion, controls: reduceMotion });
      v.muted = true;
      lbMedia.append(v);
    } else if (item.type === "video") {
      lbMedia.append(el("video", { src: item.src, poster: item.thumb, controls: true, autoplay: true, playsinline: true }));
    } else {
      lbMedia.append(el("iframe", {
        src: embedUrl(item), title: label || "Video player",
        allow: "autoplay; fullscreen; picture-in-picture; encrypted-media", allowfullscreen: true,
      }));
      requestAnimationFrame(sizeFrame);
    }

    const hasCaption = item.title || item.desc || item.link;
    dialog.classList.toggle("no-caption", !hasCaption);
    if (hasCaption) {
      if (item.title) {
        lbCaption.append(el("h2", {}, item.title));
        lbCaption.append(el("p", { class: "lb-by" }, "by Christian Sanchez"));
      }
      if (item.tools) lbCaption.append(el("p", { class: "lb-tools" }, `Tools: ${item.tools}`));
      if (item.desc) {
        for (const para of item.desc.split("\n").filter((p) => p.trim())) {
          lbCaption.append(el("p", {}, para));
        }
      }
      if (item.link) {
        const page = item.link.href.endsWith("/");  // a page of this site (Ghostwriting) opens in place; files open in a new tab
        // the PDF already reads in the lightbox, so its button is for keeping a copy
        const pdf = isPdf(item);
        lbCaption.append(el("a", {
          class: "btn btn-rust", href: item.link.href, download: pdf ? "" : null,
          target: page || pdf ? null : "_blank", rel: page || pdf ? null : "noopener",
        }, pdf ? "Download (PDF)" : item.link.label));
      }
    }
    dialog.setAttribute("aria-label", label ? `Enlarged view: ${label}` : "Enlarged view");
  }

  // Safari colours its status bar and floating toolbar from the page behind them. While the pop-up is open
  // the page and theme colour turn the pop-up's dark, so both bars match it instead of showing white or a band.
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const themeColor = themeMeta && themeMeta.content;
  function tintBars(on) {
    document.documentElement.classList.toggle("lb-tint", on);
    if (themeMeta) themeMeta.content = on ? "#0e0e0e" : themeColor;
  }

  let openedByPointer = false;

  function open(items, index, byPointer) {
    openedByPointer = byPointer;
    current = { items, index };
    dialog.classList.toggle("single", items.length < 2);
    render();
    lightboxOpen = true;
    document.body.classList.add("lb-open");
    tintBars(true);
    dialog.showModal();
    // Keyboard users land on Close; after a click, focus the dialog itself so
    // browsers that ring programmatic focus (Safari) don't outline the button.
    if (byPointer) dialog.focus({ preventScroll: true });
    else dialog.querySelector(".lb-close").focus();
  }

  function go(delta) {
    const n = current.items.length;
    current.index = (current.index + delta + n) % n;
    render();
  }

  if (dialog) {
    dialog.querySelector(".lb-close").addEventListener("click", () => dialog.close());
    dialog.querySelector(".lb-prev").addEventListener("click", () => go(-1));
    dialog.querySelector(".lb-next").addEventListener("click", () => go(1));
    function closed() {
      if (dialog.open || !lightboxOpen) return; // reopened in the meantime, or already tidied up
      lbMedia.replaceChildren(); // stops any playing video
      lightboxOpen = false;
      document.body.classList.remove("lb-open");
      tintBars(false);
      // The browser hands focus back to the gallery; after a click that would
      // draw a focus ring around it, so let it go.
      if (openedByPointer && document.activeElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
    }
    dialog.addEventListener("close", closed);
    // some browsers skip the close event; watching the open attribute catches every way the box shuts
    new MutationObserver(closed).observe(dialog, { attributes: true, attributeFilter: ["open"] });
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog || e.target.classList.contains("lb-inner") || e.target === lbMedia) dialog.close();
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    });
    window.addEventListener("resize", () => { if (lightboxOpen) sizeFrame(); });

    // Swipe left/right inside the lightbox on touch screens.
    let sx = null;
    dialog.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
    dialog.addEventListener("touchend", (e) => {
      if (sx == null) return;
      const dx = e.changedTouches[0].clientX - sx;
      if (Math.abs(dx) > 60 && current.items.length > 1) go(dx < 0 ? 1 : -1);
      sx = null;
    }, { passive: true });
  }

  // ---------- home-page slideshows ----------

  const SLIDE_MS = 3500; // Wix: autoplay every 3.5s, 0.5s cross-fade (in CSS)

  function initSlideshow(root, order) {
    const track = root.querySelector(".slides");
    const slides = [...track.children];
    const pause = new Set();
    let index = 0;
    let timer = 0;

    function syncMedia() {
      slides.forEach((li, i) => {
        const v = li.querySelector("video");
        if (!v) return;
        if (i === index && !pause.has("offscreen")) {
          if (!v.src) v.src = v.dataset.src;
          if (!reduceMotion) v.play().catch(() => {});
        } else if (!v.paused) {
          v.pause();
        }
      });
    }

    function show(i) {
      index = (i + slides.length) % slides.length;
      slides.forEach((li, k) => {
        li.classList.toggle("is-current", k === index);
        li.toggleAttribute("aria-hidden", k !== index);
      });
      syncMedia();
    }

    function schedule() {
      clearTimeout(timer);
      if (reduceMotion || pause.size || slides.length < 2) return;
      timer = setTimeout(() => { show(index + 1); schedule(); }, SLIDE_MS);
    }
    const hold = (r) => { pause.add(r); schedule(); };
    const release = (r) => { pause.delete(r); schedule(); };

    root.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") hold("hover"); });
    root.addEventListener("pointerleave", () => release("hover"));
    root.addEventListener("focusin", () => hold("focus"));
    root.addEventListener("focusout", () => release("focus"));

    let sx = null;
    root.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; hold("touch"); }, { passive: true });
    root.addEventListener("touchend", (e) => {
      if (sx != null) {
        const dx = e.changedTouches[0].clientX - sx;
        if (Math.abs(dx) > 40) show(index + (dx < 0 ? 1 : -1));
      }
      sx = null;
      release("touch");
    }, { passive: true });

    if ("IntersectionObserver" in window) {
      pause.add("offscreen");
      new IntersectionObserver(([e]) => {
        if (e.isIntersecting) {
          // Fetch every slide once the row is close, so slides never appear blank.
          root.querySelectorAll('img[loading="lazy"]').forEach((img) => (img.loading = "eager"));
          pause.delete("offscreen");
        } else {
          pause.add("offscreen");
        }
        syncMedia();
        schedule();
      }, { rootMargin: "300px 0px" }).observe(root);
    }
    document.addEventListener("visibilitychange", () => (document.hidden ? hold("tab") : release("tab")));

    // Stagger the rows so they don't all change at the same moment.
    pause.add("start");
    setTimeout(() => release("start"), (order % 4) * 900);
    show(0);
  }

  document.querySelectorAll("[data-slideshow]").forEach((s, i) => initSlideshow(s, i));

  // ---------- wire up ----------

  // On a narrow screen the switcher scrolls sideways; open it with the current section centered.
  const seg = document.querySelector(".seg");
  const segOn = seg && seg.querySelector(".is-active");
  if (segOn && seg.scrollWidth > seg.clientWidth) {
    seg.scrollLeft = segOn.offsetLeft - seg.offsetLeft - (seg.clientWidth - segOn.offsetWidth) / 2;
  }

  // The section bar sticks just under the pinned header; give CSS the header's real height.
  const head = document.querySelector(".site-header");
  if (head) {
    const setHead = () => document.documentElement.style.setProperty("--head-h", `${head.offsetHeight}px`);
    setHead();
    window.addEventListener("resize", setHead);
    document.fonts && document.fonts.ready.then(setHead);
  }

  function setupGallery(g) {
    const items = JSON.parse(g.querySelector(".gallery-data").textContent);
    const inline = g.classList.contains("strip-videos");
    g.addEventListener("click", (e) => {
      const b = e.target.closest("[data-index]");
      if (!b) return;
      if (inline) playInline(b, items[Number(b.dataset.index)]);
      else if (dialog) open(items, Number(b.dataset.index), e.detail > 0);
    });
    const play = g.dataset.play;
    if (!reduceMotion) {
      if (play === "hover" && canHover && !inline) g.querySelectorAll(".tile[data-video]").forEach(hoverPreview);
      if (play === "auto" && autoObserver) g.querySelectorAll(".tile[data-video]").forEach((t) => autoObserver.observe(t));
    }
    if (g.classList.contains("strip")) initStrip(g);
    watchLoops(g);
  }

  let ticking = false;
  function startTicking() {
    if (ticking || !strips.length || reduceMotion) return;
    ticking = true;
    requestAnimationFrame(tick);
  }

  document.querySelectorAll("[data-gallery]").forEach(setupGallery);
  startTicking();

  // ---------- password-locked pages (Ghostwriting) ----------
  // The gallery and text are stored encrypted (tools/lock_ghostwriting.py): PBKDF2-SHA256 turns the password
  // into an AES-GCM key, and only the right password decrypts them. Unlocked once, the page stays open for
  // the rest of the browser session.

  const lock = document.querySelector("[data-lock]");
  if (lock) {
    const data = JSON.parse(lock.querySelector(".lock-data").textContent);
    const form = lock.querySelector(".lock-form");
    const input = lock.querySelector(".lock-input");
    const error = lock.querySelector(".lock-error");
    const content = document.querySelector(".lock-content");
    const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const KEY = "lock:" + location.pathname;

    async function unlock(password) {
      const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
      const key = await crypto.subtle.deriveKey(
        { name: "PBKDF2", hash: "SHA-256", salt: bytes(data.salt), iterations: data.iter },
        base, { name: "AES-GCM", length: 256 }, false, ["decrypt"],
      );
      const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(data.iv) }, key, bytes(data.ct));
      content.innerHTML = new TextDecoder().decode(plain);
      content.hidden = false;
      lock.hidden = true;
      content.querySelectorAll("[data-gallery]").forEach(setupGallery);
      startTicking();
      try { sessionStorage.setItem(KEY, password); } catch (e) {}
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      error.hidden = true;
      form.querySelector("button").disabled = true;
      try { await unlock(input.value); } catch (err) { error.hidden = false; input.select(); }
      form.querySelector("button").disabled = false;
    });
    let saved = null;
    try { saved = sessionStorage.getItem(KEY); } catch (e) {}
    if (saved) unlock(saved).catch(() => {});
  }
})();
