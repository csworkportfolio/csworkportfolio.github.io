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
      el, viewport, speed: reduceMotion ? 0 : Number(el.dataset.speed || 0),
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
      track.querySelectorAll("[data-clone]").forEach((n) => n.remove());
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

    el.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") hold("hover"); });
    el.addEventListener("pointerleave", () => s.pause.delete("hover"));
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

  let last = 0;
  function tick(t) {
    const dt = last ? Math.min((t - last) / 1000, 0.1) : 0;
    last = t;
    for (const s of strips) {
      if (!s.speed || s.anim || !s.visible || s.pause.size || lightboxOpen) continue;
      if (s.el.classList.contains("is-static")) continue;
      s.pos += s.speed * dt;
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
    const boxW = lbMedia.clientWidth;
    const boxH = lbMedia.clientHeight;
    const ar = item.vw / item.vh;
    let w = boxW, h = boxW / ar;
    if (h > boxH) { h = boxH; w = h * ar; }
    f.style.width = `${Math.floor(w)}px`;
    f.style.height = `${Math.floor(h)}px`;
  }

  function render() {
    const item = current.items[current.index];
    lbMedia.replaceChildren();
    lbCaption.replaceChildren();
    const label = item.title || "";

    if (item.type === "image") {
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
        lbCaption.append(el("a", { class: "btn btn-rust", href: item.link.href, target: "_blank", rel: "noopener" }, item.link.label));
      }
    }
    dialog.setAttribute("aria-label", label ? `Enlarged view: ${label}` : "Enlarged view");
  }

  let openedByPointer = false;

  function open(items, index, byPointer) {
    openedByPointer = byPointer;
    current = { items, index };
    dialog.classList.toggle("single", items.length < 2);
    render();
    lightboxOpen = true;
    document.body.classList.add("lb-open");
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
    dialog.addEventListener("close", () => {
      if (dialog.open) return; // reopened before this queued event fired
      lbMedia.replaceChildren(); // stops any playing video
      lightboxOpen = false;
      document.body.classList.remove("lb-open");
      // The browser hands focus back to the gallery; after a click that would
      // draw a focus ring around it, so let it go.
      if (openedByPointer && document.activeElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
    });
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
    const counter = root.querySelector(".ss-n");
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
      counter.textContent = index + 1;
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

  // On narrow screens the section pills scroll sideways; show the current one.
  const activePill = document.querySelector(".pill.is-active");
  if (activePill) {
    const row = activePill.parentElement;
    if (row.scrollWidth > row.clientWidth) {
      row.scrollLeft = activePill.offsetLeft - (row.clientWidth - activePill.offsetWidth) / 2;
    }
  }

  document.querySelectorAll("[data-gallery]").forEach((g) => {
    const items = JSON.parse(g.querySelector(".gallery-data").textContent);
    const inline = g.classList.contains("strip-videos");
    g.addEventListener("click", (e) => {
      const b = e.target.closest("[data-index]");
      if (!b) return;
      if (inline) playInline(b, items[Number(b.dataset.index)]);
      else if (dialog) open(items, Number(b.dataset.index), e.detail > 0);
    });
    const play = g.dataset.play;
    if (!inline && !reduceMotion) {
      if (play === "hover" && canHover) g.querySelectorAll(".tile[data-video]").forEach(hoverPreview);
      if (play === "auto" && autoObserver) g.querySelectorAll(".tile[data-video]").forEach((t) => autoObserver.observe(t));
    }
    if (g.classList.contains("strip")) initStrip(g);
    watchLoops(g);
  });

  if (strips.length && !reduceMotion) requestAnimationFrame(tick);
})();
