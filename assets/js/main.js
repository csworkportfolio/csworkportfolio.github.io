// Gallery strips (auto-scrolling, swipeable) and the lightbox.
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SPEED = 38; // px per second
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

  // ---------- strip ----------

  function initStrip(el) {
    const viewport = el.querySelector(".strip-viewport");
    const track = el.querySelector(".strip-track");
    const originals = [...track.children];
    const s = { el, viewport, loop: 0, pos: 0, lastSet: -1, pause: new Set(), resumeTimer: 0, visible: true };

    function measure() {
      track.querySelectorAll("[data-clone]").forEach((n) => n.remove());
      el.classList.remove("is-static");
      s.loop = 0;
      if (track.scrollWidth <= viewport.clientWidth + 2) {
        el.classList.add("is-static");
        return;
      }
      for (const li of originals) {
        const c = li.cloneNode(true);
        c.dataset.clone = "";
        c.setAttribute("aria-hidden", "true");
        c.querySelectorAll("button").forEach((b) => (b.tabIndex = -1));
        track.appendChild(c);
      }
      watchLoops(track);
      const firstClone = track.querySelector("[data-clone]");
      s.loop = firstClone.offsetLeft - originals[0].offsetLeft;
      s.pos = viewport.scrollLeft;
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
      if (!s.loop) return;
      const x = viewport.scrollLeft;
      if (Math.abs(x - s.lastSet) <= 1) return; // our own animation frame
      // A person is scrolling: keep the loop seamless in both directions.
      if (x >= s.loop) viewport.scrollLeft = x - s.loop;
      else if (x <= 0) viewport.scrollLeft = x + s.loop;
      s.pos = viewport.scrollLeft;
    }, { passive: true });

    const step = (dir) => {
      hold("arrow", 4000);
      viewport.scrollBy({ left: dir * viewport.clientWidth * 0.75, behavior: reduceMotion ? "auto" : "smooth" });
    };
    el.querySelector(".strip-prev").addEventListener("click", () => step(-1));
    el.querySelector(".strip-next").addEventListener("click", () => step(1));

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([e]) => (s.visible = e.isIntersecting)).observe(el);
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
      if (!s.loop || !s.visible || s.pause.size || lightboxOpen) continue;
      s.pos += SPEED * dt;
      if (s.pos >= s.loop) s.pos -= s.loop;
      s.viewport.scrollLeft = s.pos;
      s.lastSet = s.viewport.scrollLeft;
    }
    requestAnimationFrame(tick);
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

  function open(items, index) {
    current = { items, index };
    dialog.classList.toggle("single", items.length < 2);
    render();
    lightboxOpen = true;
    document.body.classList.add("lb-open");
    dialog.showModal();
    dialog.querySelector(".lb-close").focus();
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
    g.addEventListener("click", (e) => {
      const b = e.target.closest("[data-index]");
      if (b && dialog) open(items, Number(b.dataset.index));
    });
    if (g.classList.contains("strip")) initStrip(g);
    watchLoops(g);
  });

  if (strips.length && !reduceMotion) requestAnimationFrame(tick);
})();
