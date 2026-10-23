// Gallery sliders (set up like the Wix galleries they replace) and the lightbox.
(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // pieces with a dark-mode copy (a social video with its app in dark mode): dark-mode visitors get that copy
  if (document.documentElement.classList.contains("can-dark") && matchMedia("(prefers-color-scheme: dark)").matches) {
    document.querySelectorAll("video[data-src-dark]").forEach((v) => { v.dataset.src = v.dataset.srcDark; v.poster = v.dataset.posterDark; });
  }
  // In-app browsers (LinkedIn, Instagram) and mobile Safari change the window height as their toolbars slide,
  // many times per scroll. Layout that reacts to every resize then fights the scroll and the page shudders.
  // So: the viewport height is the small, stable one (100svh), refreshed only when the width changes, and
  // the layout code listens for width changes only.
  const probe = document.createElement("div");
  probe.style.cssText = "position:fixed;top:0;left:0;width:0;height:100vh;height:100svh;visibility:hidden;pointer-events:none";
  document.documentElement.appendChild(probe);
  let vhCache = probe.offsetHeight || window.innerHeight;
  const viewH = () => vhCache;
  let lastW = window.innerWidth;
  const widthWatchers = [];
  const onWidthResize = (fn) => widthWatchers.push(fn);
  window.addEventListener("resize", () => {
    if (window.innerWidth === lastW) return;
    lastW = window.innerWidth;
    vhCache = probe.offsetHeight || window.innerHeight;
    widthWatchers.forEach((fn) => fn());
  });
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
    onWidthResize(reserve);
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

  // ---------- intro: keep the wrapped portrait standing on the bottom edge ----------
  // The spacer above the floated portrait pushes it down when the text runs longer than the portrait, so it
  // still reaches the bottom edge. Lowering it lets the text wrap wider higher up, which shortens the text,
  // so search for the smallest push that puts the portrait's bottom at or below the end of the text.
  const heroText = document.querySelector(".home-hero-text");
  const spacer = heroText && heroText.querySelector(".hero-spacer");
  const shaped = heroText && heroText.querySelector(".home-portrait-float");
  function standPortrait() {
    if (!spacer || !shaped) return;
    spacer.style.height = "0px";
    shaped.style.marginBottom = "";
    shaped.style.marginTop = "";
    if (getComputedStyle(spacer).display === "none" || !shaped.offsetHeight) return;
    const last = heroText.querySelector("p:last-child");
    const top = () => heroText.getBoundingClientRect().top + parseFloat(getComputedStyle(heroText).paddingTop);
    const textEnd = () => last.getBoundingClientRect().bottom - top();
    const fits = (s) => { spacer.style.height = s + "px"; return s + shaped.offsetHeight >= textEnd() - 0.5; };
    const settle = () => {
      let lo = 0, hi = Math.ceil(textEnd());
      if (fits(0)) return void (spacer.style.height = "0px");
      while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (fits(mid)) hi = mid; else lo = mid; }
      spacer.style.height = hi + "px";
    };
    // with short text the portrait stays near the top and the band ends with the text, cropping the portrait:
    // a negative bottom margin stops the photo's lower part from stretching the band
    shaped.style.marginBottom = "";
    shaped.style.marginTop = "";
    settle();
    // near the top, line the top of the head up with the top of "Hi, Christian Sanchez here." (the head
    // starts 3.85% down the photo; the greeting's letters start half its leading below its box)
    if (parseFloat(spacer.style.height) === 0) {
      const hi = heroText.querySelector(".hero-hi");
      const hiBox = hi.getBoundingClientRect();
      const cs = getComputedStyle(hi);
      const lead = (parseFloat(cs.lineHeight) || hiBox.height) - parseFloat(cs.fontSize);
      const letters = hiBox.top + lead / 2 + parseFloat(cs.fontSize) * 0.12;
      const head = shaped.getBoundingClientRect().top + shaped.offsetHeight * 0.0385;
      const nudge = Math.round(letters - head);
      if (nudge) {
        shaped.style.marginTop = parseFloat(getComputedStyle(shaped).marginTop) + nudge + "px";
        settle();
      }
    }
    const end = Math.max(last.getBoundingClientRect().bottom,
      heroText.getBoundingClientRect().top + parseFloat(getComputedStyle(heroText).minHeight || 0));
    const over = shaped.getBoundingClientRect().bottom - end;
    if (over > 1) shaped.style.marginBottom = -Math.round(over) + "px";
  }
  if (shaped) {
    if (shaped.complete) standPortrait(); else shaped.addEventListener("load", standPortrait);
    onWidthResize(standPortrait);
    if (document.fonts) document.fonts.ready.then(standPortrait);
  }

  // ---------- Read More shine: lights up as each case row scrolls into view ----------

  // the other buttons (like Open PDF) and the notes' expand mark wear the same shine through their glass,
  // lit while on screen; the arrows stay plain
  const shines = document.querySelectorAll(".shine, .btn:not(.shine .btn), .strip-notes .tile, .tile.is-note");
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
      el, viewport, track, speed: reduceMotion ? 0 : Number(el.dataset.speed || 0), v: 0, hover: false,
      loops: el.hasAttribute("data-loop"), restart: el.hasAttribute("data-restart"), loop: 0, pos: 0, lastSet: -1,
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
      el.style.removeProperty("--centre");
      track.style.transform = "";
      prev.hidden = next.hidden = false;
      s.loop = 0;
      // a short strip whose pieces fit between the page margins sits centred and still, with no arrows
      const cs = getComputedStyle(track);
      const pieces = track.scrollWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const gutter = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--gutter")) || 24;
      if (track.scrollWidth <= viewport.clientWidth + 2 || pieces <= viewport.clientWidth - 2 * gutter) {
        // it starts on the same left edge as the other strips, then glides once to the centre and rests there
        el.classList.add("is-static");
        viewport.scrollLeft = 0; s.pos = 0;
        const shift = (viewport.clientWidth - pieces) / 2 - parseFloat(cs.paddingLeft);
        el.style.setProperty("--centre", `${shift.toFixed(1)}px`);
        if (reduceMotion || el.classList.contains("is-centred")) el.classList.add("is-centred");
        else if ("IntersectionObserver" in window) {
          const io = new IntersectionObserver(([e]) => {
            if (e.isIntersecting) { setTimeout(() => el.classList.add("is-centred"), 600); io.disconnect(); }
          }, { threshold: 0.5 });
          io.observe(el);
        } else el.classList.add("is-centred");
        return;
      }
      if (s.loops) {
        for (const li of originals) {
          const c = li.cloneNode(true);
          c.dataset.clone = "";
          c.setAttribute("aria-hidden", "true");
          c.querySelectorAll("button").forEach((b) => (b.tabIndex = -1));
          c.querySelectorAll("[id]").forEach((n) => n.removeAttribute("id"));   // the captions' ids stay unique
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

    // as on Apple's galleries, the pointer passing over doesn't change the pace; the pause button does
    el.addEventListener("focusin", (e) => { if (e.target.matches(":focus-visible")) hold("focus"); });   // keyboard focus only; a tapped button shouldn't stop it
    el.addEventListener("focusout", () => s.pause.delete("focus"));
    // a touch that turns out to be the page scrolling up or down lets the strip carry straight on; only a
    // sideways swipe (or a tap) holds it for a few seconds
    let tx = 0, ty = 0;
    viewport.addEventListener("touchstart", (e) => { tx = e.touches[0].clientX; ty = e.touches[0].clientY; hold("touch"); }, { passive: true });
    viewport.addEventListener("touchend", (e) => {
      const t = e.changedTouches[0];
      const dx = Math.abs(t.clientX - tx), dy = Math.abs(t.clientY - ty);
      if (dy > 12 && dy > dx) s.pause.delete("touch"); else hold("touch", 3500);
    }, { passive: true });
    viewport.addEventListener("touchcancel", () => s.pause.delete("touch"), { passive: true });
    // a pause / play button with the arrows, for strips that move on their own
    const nextBtn = el.querySelector(".strip-next");
    if (s.speed && nextBtn && el.closest(".cat-v2")) {
      const pb = document.createElement("button");
      pb.type = "button";
      pb.className = "strip-arrow strip-pause";
      pb.setAttribute("aria-label", "Pause gallery");
      pb.innerHTML = '<svg viewBox="0 0 24 24"><path class="i-pause" d="M9 6v12M15 6v12"/><path class="i-play" d="M8 5.5v13l11-6.5z"/></svg>';
      pb.addEventListener("click", () => {
        const paused = s.pause.has("user");
        if (paused) s.pause.delete("user"); else s.pause.add("user");
        pb.classList.toggle("is-paused", !paused);
        pb.setAttribute("aria-label", paused ? "Pause gallery" : "Play gallery");
      });
      nextBtn.after(pb);
    }
    viewport.addEventListener("wheel", (e) => { if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) hold("wheel", 2500); }, { passive: true });

    viewport.addEventListener("scroll", () => {
      arrows();
      const x = viewport.scrollLeft;
      if (s.anim || Math.abs(x - s.lastSet) <= 1) return; // our own movement
      track.style.transform = "";   // a person took over: drop the sub-pixel nudge
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
      // measured from the track's left padding, so a step lands each piece on the text column's edge
      const pad = parseFloat(getComputedStyle(track).paddingLeft) || 0;
      const lefts = items.map((li) => li.offsetLeft - track.offsetLeft - pad);
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
    // the expand button opens the piece most in view, as a tap on it would
    const openBtn = el.querySelector(".strip-open");
    if (openBtn) openBtn.addEventListener("click", () => {
      const v = viewport.getBoundingClientRect();
      let best = null, most = 0;
      track.querySelectorAll(".tile-wrap:not([data-clone]) .tile, .tile-wrap .tile").forEach((t) => {
        const r = t.getBoundingClientRect();
        const seen = Math.min(r.right, v.right) - Math.max(r.left, v.left);
        if (seen > most) { most = seen; best = t; }
      });
      if (best) best.click();
    });
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
    onWidthResize(() => {
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
      const target = s.speed;
      s.v = s.v ? s.v + (target - s.v) * Math.min(1, dt * 4) : target;  // ease between paces over about half a second
      s.pos += s.v * dt;
      if (s.loop && s.pos >= s.loop) s.pos -= s.loop;
      const end = s.viewport.scrollWidth - s.viewport.clientWidth;
      if (!s.loop && s.pos >= end) {
        s.pos = end;   // non-looping Wix sliders stop at the end
        if (s.restart && !s.restarting) {   // ...unless they restart: a pause, a fade out, back to the start, a fade in
          s.restarting = true;
          s.pause.add("restart");
          setTimeout(() => {
            s.el.classList.add("is-fading");
            setTimeout(() => {
              s.pos = 0; s.viewport.scrollLeft = 0; s.lastSet = 0; s.v = 0; s.track.style.transform = "";
              s.el.classList.remove("is-fading");
              setTimeout(() => { s.pause.delete("restart"); s.restarting = false; }, 600);
            }, 500);
          }, 1500);
        }
      }
      // scrollLeft only moves in whole pixels (Safari rounds it), which judders at slow speeds; the whole
      // pixels go to scrollLeft and the fraction rides on the track as a transform, so the motion stays smooth
      const whole = Math.floor(s.pos);
      s.viewport.scrollLeft = whole;
      s.lastSet = s.viewport.scrollLeft;
      s.track.style.transform = `translate3d(${(whole - s.pos).toFixed(3)}px, 0, 0)`;
    }
    requestAnimationFrame(tick);
  }

  // ---------- videos inside sliders ----------

  function previewUrl(kind, id) { // muted, chrome-free autoplay for hover previews
    return kind === "vimeo"
      ? `https://player.vimeo.com/video/${id}?background=1&dnt=1`
      : `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&mute=1&controls=0&loop=1&playlist=${id}&modestbranding=1&rel=0&cc_load_policy=0&iv_load_policy=3`;   // no captions or annotations over a silent preview
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
    // the player paints white while it starts up; keep it hidden over the poster until the video is running
    frame.addEventListener("load", () => setTimeout(() => frame.classList.add("is-ready"), 700), { once: true });
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

  // stacked layout (tablets, foldables, squarish windows): give the visual whatever height is left once the words
  // under it are laid out, so the whole stack fits without scrolling (within sensible limits)
  // stacked (visual on top, words under it) when that gives the visual more room: any piece wider than tall, or
  // a window that isn't much wider than tall; tall pieces and documents sit beside their words on wide windows
  function chooseLayout(item) {
    const vr = item.vw ? item.vw / item.vh : (item.w && item.h ? item.w / item.h : 1);
    const wide = innerWidth / innerHeight >= 1.5;
    const doc = item.type === "image" && isPdf(item);
    dialog.classList.toggle("is-stack", innerWidth > 900 && innerHeight >= 640 && (!wide || (vr >= 1.1 && !doc)));
  }

  function fitStacked() {
    const inner = dialog.querySelector(".lb-inner");
    if (!inner) return;
    dialog.style.removeProperty("--lb-fit");
    if (asPage || getComputedStyle(inner).flexDirection !== "column") return;
    const cs = getComputedStyle(inner);
    const room = inner.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
      - lbCaption.offsetHeight - parseFloat(cs.rowGap || cs.gap || 0);
    // the visual keeps at least half the height even when the words are long; they then scroll beneath it
    const half = (inner.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)) * 0.5;
    dialog.style.setProperty("--lb-fit", `${Math.floor(Math.max(half, room))}px`);
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

  const darkPage = () => document.documentElement.classList.contains("can-dark") && matchMedia("(prefers-color-scheme: dark)").matches;
  function render() {
    let item = current.items[current.index];
    if (item.full_dark && darkPage()) item = { ...item, full: item.full_dark, thumb: item.thumb_dark || item.thumb };
    if (item.src_dark && darkPage()) item = { ...item, src: item.src_dark, thumb: item.thumb_dark || item.thumb };
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
    dialog.classList.toggle("is-quick", !!item.quick);
    dialog.classList.toggle("is-glass", !!item.quick);
    chooseLayout(item);   // the home quick view floats on its glass pane; the rest are solid dark
    if (item.quick) {
      // a home case's quick view: what the case is, its figures and opening lines, the sample on screen, and
      // the way into the full case study
      const q = item.quick;
      lbCaption.append(el("p", { class: "lb-kicker" }, q.kicker));
      lbCaption.append(el("h2", {}, q.title));
      if (q.figures && q.figures.length) {
        const dl = el("dl", { class: "lb-figs" });
        q.figures.forEach(([v, d]) => { const box = el("div", {}); box.append(el("dt", {}, d), el("dd", {}, v)); dl.append(box); });
        lbCaption.append(dl);
      }
      if (q.lede) lbCaption.append(el("p", {}, q.lede));
      if (item.title) lbCaption.append(el("p", { class: "lb-sample" }, `On screen: ${item.title}`));
      lbCaption.append(el("a", { class: "btn btn-rust is-lit", href: item.link.href, style: q.shine || null }, item.link.label));   // the colours of its Read More
    } else if (hasCaption) {
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
          class: "btn btn-rust is-lit", href: item.link.href, download: pdf ? "" : null,
          target: page || pdf ? null : "_blank", rel: page || pdf ? null : "noopener",
        }, pdf ? "Download (PDF)" : item.link.label));
      }
    }
    dialog.setAttribute("aria-label", label ? `Enlarged view: ${label}` : "Enlarged view");
    requestAnimationFrame(fitStacked);
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

  // Phones open a piece as a full page instead of a pinned pop-up: the rest of the page steps aside and the
  // piece scrolls with the window, so it runs on under Safari's see-through toolbar like any page (a pinned
  // layer can't). The phone's back gesture closes it, and closing returns to the same spot on the page.
  const phoneView = () => matchMedia("(max-width: 900px)").matches;
  let asPage = false;
  let pageScroll = 0;

  // a tap or click just before opening counts as a pointer open even when it reached us through a button that
  // opens the piece for it (the expand buttons), so phones never get the keyboard focus ring on Close
  let lastPointer = -Infinity;
  document.addEventListener("pointerdown", () => { lastPointer = performance.now(); }, true);

  function open(items, index, byPointer) {
    byPointer = byPointer || performance.now() - lastPointer < 1500;
    openedByPointer = byPointer;
    current = { items, index };
    dialog.classList.toggle("single", items.length < 2);
    asPage = phoneView();
    if (asPage) pageScroll = window.scrollY;
    render();
    lightboxOpen = true;
    tintBars(true);
    if (asPage) {
      document.documentElement.classList.add("lb-page");
      dialog.show();
      window.scrollTo({ top: 0, behavior: "instant" });
      history.pushState({ lightbox: true }, "");
    } else {
      document.body.classList.add("lb-open");
      dialog.showModal();
    }
    // Keyboard users land on Close; after a click, focus the dialog itself so
    // browsers that ring programmatic focus (Safari) don't outline the button.
    if (byPointer) dialog.focus({ preventScroll: true });
    else dialog.querySelector(".lb-close").focus();
  }

  function go(delta) {
    const n = current.items.length;
    current.index = (current.index + delta + n) % n;
    render();
    if (asPage) window.scrollTo({ top: 0, behavior: "instant" });
  }

  // closing a full-page piece steps back through history, so the back gesture and the X behave the same
  function closeBox() {
    if (asPage && history.state && history.state.lightbox) history.back();
    else dialog.close();
  }
  window.addEventListener("popstate", () => { if (lightboxOpen && asPage) dialog.close(); });

  if (dialog) {
    dialog.querySelector(".lb-close").addEventListener("click", closeBox);
    dialog.querySelector(".lb-prev").addEventListener("click", () => go(-1));
    dialog.querySelector(".lb-next").addEventListener("click", () => go(1));
    function closed() {
      if (dialog.open || !lightboxOpen) return; // reopened in the meantime, or already tidied up
      lbMedia.replaceChildren(); // stops any playing video
      lightboxOpen = false;
      document.body.classList.remove("lb-open");
      tintBars(false);
      if (asPage) {
        document.documentElement.classList.remove("lb-page");
        window.scrollTo({ top: pageScroll, behavior: "instant" });  // the page scrolls smoothly elsewhere; jumps here
        asPage = false;
      }
      // The browser hands focus back to the gallery; after a click that would
      // draw a focus ring around it, so let it go.
      if (openedByPointer && document.activeElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
    }
    dialog.addEventListener("close", closed);
    // some browsers skip the close event; watching the open attribute catches every way the box shuts
    new MutationObserver(closed).observe(dialog, { attributes: true, attributeFilter: ["open"] });
    // Clicking away closes: on a desktop an image closes on any click on it or the space around it (zoom-out
    // cursor); a PDF or video only on the empty space, since clicks on it scroll or play; the caption, buttons
    // and arrows never do. The home quick view is a card, so only clicks outside the card close it.
    dialog.addEventListener("click", (e) => {
      const t = e.target;
      const quick = dialog.classList.contains("is-quick") && !asPage;
      if (t === dialog) return closeBox();
      if (quick) return;
      if (t.classList.contains("lb-inner") || t === lbMedia) return closeBox();
      if (!asPage && t.tagName === "IMG" && t.parentElement === lbMedia) closeBox();
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    });
    window.addEventListener("resize", () => { if (lightboxOpen) { chooseLayout(current.items[current.index]); sizeFrame(); fitStacked(); } });

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

  const SLIDE_MS = 2500; // every 2.5s: the sample fades out, then the next fades in (CSS)

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
        if (i === index && !pause.has("offscreen") && !pause.has("scene")) {
          if (!v.src) v.src = v.dataset.src;
          if (!reduceMotion) v.play().catch(() => {});
        } else if (!v.paused) {
          v.pause();
        }
      });
    }

    // the controls under the samples, as on Apple's carousels: a pill of dots where the current one stretches
    // into a bar that fills while its sample is up, and a pause / play button
    let ctl = null, dots = [], toggle = null;
    if (slides.length > 1) {
      ctl = document.createElement("div");
      ctl.className = "ss-ctl";
      ctl.style.setProperty("--ss-ms", `${SLIDE_MS}ms`);
      const pill = document.createElement("div");
      pill.className = "ss-dots";
      dots = slides.map((_, i) => {
        const d = document.createElement("button");
        d.type = "button";
        d.setAttribute("aria-label", `Show sample ${i + 1} of ${slides.length}`);
        d.addEventListener("click", () => { show(i); schedule(); });
        pill.appendChild(d);
        return d;
      });
      ctl.appendChild(pill);
      if (!reduceMotion) {
        toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "ss-toggle";
        toggle.setAttribute("aria-label", "Pause slideshow");
        toggle.addEventListener("click", () => {
          const paused = pause.has("user");
          if (paused) release("user"); else hold("user");
          toggle.classList.toggle("is-paused", !paused);
          toggle.setAttribute("aria-label", paused ? "Pause slideshow" : "Play slideshow");
        });
        ctl.appendChild(toggle);
      }
      if (root.closest(".wk-box")) {
        const ex = document.createElement("button");
        ex.type = "button";
        ex.className = "ss-toggle ss-open";
        ex.setAttribute("aria-label", "Open quick view");
        ex.innerHTML = '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>';
        ex.addEventListener("click", () => root.click());
        ctl.appendChild(ex);
      }
      root.after(ctl);
    }

    function show(i) {
      index = (i + slides.length) % slides.length;
      slides.forEach((li, k) => {
        li.classList.toggle("is-current", k === index);
        li.toggleAttribute("aria-hidden", k !== index);
      });
      dots.forEach((d, k) => { d.classList.toggle("is-on", k === index); d.setAttribute("aria-current", k === index ? "true" : "false"); });
      syncMedia();
    }

    function schedule() {
      clearTimeout(timer);
      const running = !(reduceMotion || pause.size || slides.length < 2);
      if (ctl) {
        // the bar refills from empty each time a sample's time starts; it holds still while paused
        ctl.classList.toggle("is-held", !running);
        if (running) { ctl.classList.remove("is-timing"); void ctl.offsetWidth; ctl.classList.add("is-timing"); }
      }
      if (!running) return;
      timer = setTimeout(() => { show(index + 1); schedule(); }, SLIDE_MS);
    }
    const hold = (r) => { pause.add(r); schedule(); };
    const release = (r) => { pause.delete(r); schedule(); };
    // the home scene holds the slideshows of the cases not in view (all of its boxes stay on screen)
    root.addEventListener("scene-hold", () => { hold("scene"); syncMedia(); });
    root.addEventListener("scene-release", () => { pause.delete("scene"); syncMedia(); schedule(); });

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

  // A bar too long for the screen runs edge to edge and scrolls (CSS .is-scrolling). Measured in the
  // centred, rounded form first, since the full-width form always has the room it needs.
  function markScrolling() {
    if (!seg) return;
    seg.classList.remove("is-scrolling");
    seg.classList.toggle("is-scrolling", seg.scrollWidth > seg.clientWidth + 1);
    markEnd();
  }
  // the fade at the bar's right edge (CSS) clears once it is scrolled to the end
  function markEnd() {
    if (seg) seg.classList.toggle("at-end", seg.scrollLeft + seg.clientWidth >= seg.scrollWidth - 1);
  }
  if (seg) seg.addEventListener("scroll", markEnd, { passive: true });
  markScrolling();
  onWidthResize(markScrolling);
  if (document.fonts) document.fonts.ready.then(markScrolling);

  if (segOn && seg.scrollWidth > seg.clientWidth) {
    seg.scrollLeft = segOn.offsetLeft - seg.offsetLeft - (seg.clientWidth - segOn.offsetWidth) / 2;
  }

  // The section bar sticks just under the pinned header; give CSS the header's real height.
  const head = document.querySelector(".site-header");
  if (head) {
    const setHead = () => document.documentElement.style.setProperty("--head-h", `${head.offsetHeight}px`);
    setHead();
    onWidthResize(setHead);
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


  // ---------- home case boxes: a click on the samples opens that case's quick view, at the sample on screen ----------
  document.querySelectorAll(".wk-case").forEach((c) => {
    const data = c.querySelector(".wk-quick");
    const show = c.querySelector(".slideshow");
    if (!data || !show || !dialog) return;
    const items = JSON.parse(data.textContent);
    const title = c.querySelector("h2").textContent;
    show.setAttribute("role", "button");
    show.tabIndex = 0;
    show.setAttribute("aria-label", `Quick view: ${title}`);
    const go = (byPointer) => {
      const at = [...show.querySelectorAll(".slide")].findIndex((li) => li.classList.contains("is-current"));
      open(items, Math.max(0, at), byPointer);
    };
    show.addEventListener("click", (e) => go(e.detail > 0));
    show.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(false); } });
  });

  // ---------- category strips held in 3D: on a desktop each tile leans toward the pointer and lifts on its
  // shadow, the nearest most (the long-form notes also drift a little toward it). Phones stay flat. ----------
  function tiltStrip(strip) {
    if (!canHover || reduceMotion || !strip.closest(".cat-v2")) return;
    const notes = strip.classList.contains("strip-notes");
    let px = 0, py = 0, inside = false, frame = 0;
    const tiles = () => [...strip.querySelectorAll(".tile")];
    const step = () => {
      frame = 0;
      if (!inside) return;
      const vw = innerWidth;
      tiles().forEach((t) => {
        const r = t.getBoundingClientRect();
        if (r.right < 0 || r.left > vw) return;
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const dx = Math.max(-1, Math.min(1, (px - cx) / Math.max(r.width, 300)));
        const dy = Math.max(-1, Math.min(1, (py - cy) / Math.max(r.height, 200)));
        const near = Math.exp(-Math.hypot(px - cx, py - cy) / 520);
        t.style.setProperty("--ry", `${(dx * 9 * near).toFixed(2)}deg`);
        t.style.setProperty("--rx", `${(-dy * 7 * near).toFixed(2)}deg`);
        t.style.setProperty("--rz", `${(near * 22).toFixed(1)}px`);
        t.style.setProperty("--lift", near.toFixed(3));
        if (notes) {
          t.style.setProperty("--tx", `${(dx * 8 * near).toFixed(1)}px`);
          t.style.setProperty("--ty", `${(dy * 6 * near).toFixed(1)}px`);
        }
      });
      frame = requestAnimationFrame(step);   // the strip keeps gliding under a still pointer
    };
    strip.addEventListener("pointermove", (e) => {
      // phone widths stay flat even with a mouse (a narrow window): the pieces fill the screen there
      if (e.pointerType !== "mouse" || innerWidth <= 720) return;
      px = e.clientX; py = e.clientY; inside = true;
      if (!frame) frame = requestAnimationFrame(step);
    });
    strip.addEventListener("pointerleave", () => {
      inside = false;
      tiles().forEach((t) => ["--rx", "--ry", "--rz", "--lift", "--tx", "--ty"].forEach((v) => t.style.removeProperty(v)));
    });
  }
  document.querySelectorAll("[data-gallery]").forEach(tiltStrip);

  // ---------- password-locked pages (Ghostwriting) ----------
  // The gallery and text are stored encrypted (tools/lock_ghostwriting.py): PBKDF2-SHA256 turns the password
  // into an AES-GCM key, and only the right password decrypts them. Unlocked once, the page stays open for
  // the rest of the browser session.

  // ---------- the unlocked ghostwriting posts as a reading scene (desktop): the stage holds under the tab bar
  // while each post takes its turn, large on the right with its words on the left, then the next slides up
  // over it. Phones, short windows and reduced motion keep the strip. ----------
  function readingScene(content) {
    const data = content.querySelector(".gallery-data");
    const strip = content.querySelector(".strip");
    if (!data || !strip || content.querySelector(".ex-scene")) return;
    const items = JSON.parse(data.textContent);
    const n = items.length;
    const HAND = 0.3, HOLD = 0.5;   // the home page's pacing: about 0.8 of a screen of scroll per post
    const total = n * (HAND + HOLD) - HAND;
    const scene = document.createElement("section");
    scene.className = "ex-scene";
    scene.setAttribute("aria-label", "Ghostwriting posts");
    scene.style.setProperty("--units", total.toFixed(2));
    const stage = document.createElement("div");
    stage.className = "ex-stage";
    const inner = document.createElement("div");
    inner.className = "ex-inner";
    // where you are: a bar per post, the current one long and filling as you read on (a click jumps to that post),
    // and, on the first post only, a cue that scrolling brings the next
    const rail = el("div", { class: "ex-rail", role: "group", "aria-label": "Posts" });
    const bars = items.map((it, k) => {
      const bar = el("button", { type: "button", "aria-label": `Post ${k + 1} of ${n}` });
      bar.append(el("i", {}));
      bar.addEventListener("click", () => {
        const pin = pillsH();
        const run = scene.offsetHeight - (viewH() - pin);
        const top = scene.getBoundingClientRect().top + window.scrollY - pin;
        window.scrollTo({ top: top + run * (k * (HAND + HOLD) + 0.05) / total, behavior: "smooth" });
      });
      rail.append(bar);
      return bar;
    });
    const cue = el("p", { class: "ex-cue", "aria-hidden": "true" }, "Scroll for the next post");
    rail.append(cue);
    let cueGone = false;
    const cases = items.map((it, k) => {
      const art = el("article", { class: "ex-case", style: `--k:${k}` });
      const text = el("div", { class: "ex-text" });
      text.append(el("h3", {}, it.title || ""));
      (it.desc || "").split("\n").filter((t) => t.trim()).forEach((t) => text.append(el("p", {}, t)));
      const fig = el("figure", { class: "ex-box" });
      // the tile-sized copy (about twice the height it shows at) decodes far faster than the full one, which the
      // pop-up still uses
      const img = el("img", { src: it.thumb || it.full, alt: it.title || "", width: it.w, height: it.h, decoding: "async" });
      img.addEventListener("click", () => open(items, k, true));
      fig.append(img);
      art.append(text, fig);
      inner.append(art);
      return art;
    });
    inner.append(rail);
    stage.append(inner);
    scene.append(stage);
    strip.after(scene);
    const pillsH = () => { const p = document.querySelector(".pills"); return p ? p.offsetHeight : 0; };
    const clamp = (v) => Math.min(1, Math.max(0, v));
    const live = () => {
      const pin = pillsH();
      document.documentElement.style.setProperty("--pills-h", `${pin}px`);
      const on = !reduceMotion && innerWidth > 900 && viewH() - pin >= 620;
      scene.classList.toggle("is-live", on);
      content.classList.toggle("ex-on", on);
    };
    const move = () => {
      if (!scene.classList.contains("is-live")) return;
      const pin = pillsH();
      const r = scene.getBoundingClientRect();
      const run = r.height - (viewH() - pin);
      const u = run > 0 ? Math.max(0, (pin - r.top) / run) * total : 0;
      let at = 0;
      const STEP = HAND + HOLD;
      cases.forEach((c, k) => {
        const st = k * STEP;
        if (u >= st - HAND / 2) at = k;
        const e = k === 0 ? 1 : clamp((u - (st - HAND)) / HAND);
        const l = k === n - 1 ? 0 : clamp((u - (st + HOLD)) / HAND);
        // the peeks ease in and out with the scroll itself (no timed transitions to fall behind it): a post rises
        // into the bottom peek while the one before it arrives, and keeps its top-edge peek until the one after
        // next takes over
        const pk = 48 * clamp((u - (st - STEP - HAND)) / HAND);
        const pt = 30 * (1 - clamp((u - (st + 2 * STEP - HAND)) / HAND));
        const box = c._box || (c._box = c.querySelector(".ex-box"));
        const text = c._text || (c._text = c.querySelector(".ex-text"));
        const y = (1 - e) * (c._drop - pk) - l * (c._rise - pt);
        box.style.transform = `translate3d(0, ${y.toFixed(1)}px, 0)`;
        const te = k === 0 ? 1 : clamp(e * 2 - 1), tl = clamp(l * 2);
        text.style.opacity = (te * (1 - tl)).toFixed(3);
        text.style.transform = `translate3d(0, ${((1 - te) * 24 - tl * 24).toFixed(1)}px, 0)`;
        c.classList.toggle("is-shown", e > 0 && l < 1);
      });
      const within = clamp((u - at * (HAND + HOLD)) / (HOLD + HAND));
      bars.forEach((bar, k) => {
        bar.classList.toggle("is-on", k === at);
        bar.classList.toggle("is-done", k < at);
        bar.style.setProperty("--fill", k < at ? "1" : k === at ? (at === n - 1 ? 1 : within).toFixed(3) : "0");
        if (k === at) bar.setAttribute("aria-current", "step"); else bar.removeAttribute("aria-current");
      });
      if (!cueGone && u > 0.12) { cueGone = true; rail.classList.add("cue-gone"); }
    };
    // how far each post must drop to sit just below the screen, from where it rests (measured untransformed)
    const measure = () => {
      const h = stage.clientHeight;
      cases.forEach((c) => {
        const img = c.querySelector(".ex-box img");
        const top = c.offsetTop + (img ? img.offsetTop : 0);
        const bottom = top + (img ? img.offsetHeight : 0);
        c._drop = Math.max(0, h - top) + 8;
        c._rise = bottom + 8;   // how far up it goes to clear the top of the screen
      });
    };
    live(); measure();
    // the posts replace the taller locked panes, which can leave the reader partway into the scene; start them at
    // the first post
    if (scene.classList.contains("is-live")) {
      const top = scene.getBoundingClientRect().top + window.scrollY - pillsH();
      if (window.scrollY > top) window.scrollTo({ top, behavior: "instant" });
    }
    move();
    cases.forEach((c) => { const img = c.querySelector(".ex-box img"); if (img && !img.complete) img.addEventListener("load", () => { measure(); move(); }, { once: true }); });
    onWidthResize(() => { live(); measure(); move(); });
    let queued = false;   // one update per frame, however many scroll events arrive in it
    window.addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; move(); }); } }, { passive: true });
  }

  // The locked file was made with the site's older strip markup; once open, the posts are brought in line with
  // the other strips: the band and spacing, a title and short snippet under each, and the arrows with the expand
  // button below on the right.
  function modernize(content) {
    const st = content.querySelector(".strip");
    if (!st) return;
    let items = [];
    try { items = JSON.parse(st.querySelector(".gallery-data").textContent); } catch (e) {}
    st.classList.add("strip-ground");
    st.style.setProperty("--gap", "40px");
    const gid = "gw";
    st.querySelectorAll(".tile-wrap").forEach((li, i) => {
      const b = li.querySelector(".tile");
      const r = b && b.style.getPropertyValue("--r");
      if (r) { li.style.setProperty("--r", r); b.style.removeProperty("--r"); }
      const it = items[i] || {};
      if (!li.querySelector(".tile-cap") && it.title) {
        const first = (it.desc || "").split("\n")[0].split(/(?<=[.!?])\s+/)[0] || "";
        const cap = el("p", { class: "tile-cap", id: `cap-${gid}-${i}` });
        cap.append(el("strong", {}, it.title));
        if (first) cap.append(el("span", {}, first.length > 120 ? first.slice(0, 117).replace(/\s+\S*$/, "") + "…" : first));
        li.append(cap);
        if (b) b.setAttribute("aria-describedby", `cap-${gid}-${i}`);
      }
    });
    const next = st.querySelector(".strip-next");
    if (next && !st.querySelector(".strip-open")) {
      const ob = document.createElement("button");
      ob.type = "button"; ob.className = "strip-arrow strip-open"; ob.setAttribute("aria-label", "View the piece in view larger");
      ob.innerHTML = '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>';
      next.after(ob);
    }
  }

  // The passcode is four glass dots that fill as the digits go in; the fourth digit tries it. On the right code
  // the empty bubbles pop one after another and the posts rise in where they were. The same lock sits on the
  // Ghostwriting page and on Social & Writing, and opening either opens both for the session.
  const KEY = "lock:ghostwriting";
  const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  document.querySelectorAll("[data-lock]").forEach((lock) => {
    // the encrypted posts are a separate file, downloaded only once a code is tried (or the page was unlocked
    // earlier this session)
    let data = null;
    const getData = async () => data || (data = await (await fetch(lock.dataset.src)).json());
    const form = lock.querySelector(".lock-form");
    const input = lock.querySelector(".lock-input");
    const error = lock.querySelector(".lock-error");
    const dots = [...lock.querySelectorAll(".gw-dot")];
    const bubbles = [...lock.querySelectorAll(".gw-bubble")];
    let content = lock.nextElementSibling;
    const host = lock.closest(".wrap");
    if (host && content && host.contains(content)) host.after(content);   // the posts run the page's full width
    let busy = false;

    // filled dots for the digits so far, and a blinking cursor in the next empty one, so it reads as a field
    const paint = () => dots.forEach((d, i) => {
      d.classList.toggle("is-on", i < input.value.length);
      d.classList.toggle("is-next", i === input.value.length);
    });
    paint();

    async function decrypt(password) {
      await getData();
      const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
      const key = await crypto.subtle.deriveKey(
        { name: "PBKDF2", hash: "SHA-256", salt: bytes(data.salt), iterations: data.iter },
        base, { name: "AES-GCM", length: 256 }, false, ["decrypt"],
      );
      return new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(data.iv) }, key, bytes(data.ct)));
    }

    function show(html, instant) {
      content.innerHTML = html;
      // under a section's own heading, the posts' heading would say the same thing twice
      if (lock.closest(".gw-wrap")) content.querySelectorAll(".cat-text h2").forEach((h) => h.remove());
      modernize(content);
      const open = () => {
        lock.hidden = true;
        content.hidden = false;
        content.classList.add("gw-reveal", "gw-full");
      // the posts take the panes' height, which follows the screen width (CSS reads these from the lock)
      ["--gg", "--gn", "--rsum"].forEach((v) => content.style.setProperty(v, lock.style.getPropertyValue(v)));
        content.querySelectorAll("[data-gallery]").forEach((g) => { setupGallery(g); tiltStrip(g); });
        startTicking();
        if (lock.closest(".gw-wrap")) readingScene(content);
      };
      if (instant || reduceMotion) { open(); return; }
      lock.classList.add("is-open");   // the bubbles pop in turn (CSS), then the posts take their place
      setTimeout(open, 420 + bubbles.length * 110);
    }

    async function unlock(password, instant) {
      const html = await decrypt(password);
      try { sessionStorage.setItem(KEY, password); } catch (e) {}
      show(html, instant);
    }

    async function attempt() {
      if (busy) return;
      busy = true;
      error.hidden = true;
      try { await unlock(input.value); input.blur(); }
      catch (err) {
        error.hidden = false;
        lock.classList.remove("is-wrong"); void lock.offsetWidth; lock.classList.add("is-wrong");
        setTimeout(() => { input.value = ""; paint(); }, 450);
      }
      busy = false;
    }

    input.addEventListener("input", () => {
      input.value = input.value.replace(/\D/g, "").slice(0, 4);
      paint();
      if (input.value.length === 4) attempt();
    });
    form.addEventListener("submit", (e) => { e.preventDefault(); attempt(); });
    // a click anywhere on the dots puts the cursor in the hidden field (and brings up the number pad)
    lock.querySelector(".gw-pin").addEventListener("click", () => input.focus());

    let saved = null;
    try { saved = sessionStorage.getItem(KEY); } catch (e) {}
    if (saved) unlock(saved, true).catch(() => {});
  });

  // ---------- case study scenes (Nike): a stage that holds still while its section scrolls past ----------
  // Each scene section is several screens tall and its stage is sticky; the scroll through the section is
  // the scene's progress, 0 to 1. Nothing captures the wheel. With reduced motion (or no script) the
  // sections stay laid out still.

  const pinTop = () => {
    const pills = document.querySelector(".page-case .pills, .page-home .pills");
    const h = pills ? pills.offsetHeight : 0;
    document.documentElement.style.setProperty("--pills-h", `${h}px`);
    return h;
  };
  const progress = (el, pin) => {
    const r = el.getBoundingClientRect();
    const run = r.height - (viewH() - pin);
    return run > 0 ? Math.min(1, Math.max(0, (pin - r.top) / run)) : 0;
  };
  const scenes = [];

  document.querySelectorAll('[data-scene="flow"]').forEach((scene) => {
    const panels = [...scene.querySelectorAll(".sc-panel")];
    const names = [...scene.querySelectorAll(".sc-names button")];
    const ph = scene.querySelector(".ph");
    const count = scene.querySelector(".sc-count strong");
    const text = scene.querySelector(".sc-text");
    const panelsBox = scene.querySelector(".sc-panels");
    const n = panels.length;
    const phone = matchMedia("(max-width: 720px)");
    let stage = -1;
    let tooTall = false;   // a window too short for the text column gets the still layout instead of a cropped pin
    const fmt = new Intl.NumberFormat("en-US");
    const isLive = () => scene.classList.contains("is-live");
    // the frame's radii, island and keys are sized from the phone's width
    if (ph) {
      const sizePhone = () => ph.style.setProperty("--phw", `${ph.getBoundingClientRect().width}px`);
      sizePhone();
      if ("ResizeObserver" in window) new ResizeObserver(sizePhone).observe(ph); else window.addEventListener("resize", sizePhone);
    }
    names.forEach((b) => b.addEventListener("click", () => {
      if (!isLive()) { panels[+b.dataset.go].scrollIntoView({ block: "start" }); return; }
      // scroll to the middle of that stage's stretch of the section
      const top = scene.getBoundingClientRect().top + window.scrollY;
      const run = scene.offsetHeight - (viewH() - pinTop());
      window.scrollTo({ top: top - pinTop() + run * ((+b.dataset.go + 0.5) / n), behavior: "smooth" });
    }));
    // the switcher under the phone swaps which placement goes through the stages
    const sw = scene.querySelector(".sc-switch");
    if (sw && ph) {
      const sets = JSON.parse(scene.querySelector(".sc-sets").textContent);
      sw.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        const set = sets[+b.dataset.set];
        ph.querySelectorAll(".ph-layer img").forEach((img) => { img.src = set.src; });
        const nx = ph.querySelector(".ph-next"); if (nx) nx.src = set.next;
        sw.querySelectorAll("button").forEach((x) => x.classList.toggle("is-on", x === b));
      }));
    }
    if (reduceMotion) return;
    const live = () => {
      scene.classList.toggle("is-live", !!ph && !phone.matches && !tooTall);   // a still walkthrough (a photo, no phone) never pins
      stage = -1;
      if (!isLive()) {   // back to the still layout: whole phone, every panel, the full figure
        scene.removeAttribute("data-stage");
        if (ph) ["--apart", "--scan"].forEach((v) => ph.style.removeProperty(v));
        panels.forEach((el) => el.classList.remove("is-on"));
        names.forEach((el) => { el.classList.remove("is-on", "is-done"); el.removeAttribute("aria-current"); });
        if (count) count.textContent = fmt.format(+count.dataset.to) + "+";
      }
    };
    const fits = () => {
      if (tooTall || phone.matches || !isLive()) return;
      const need = text.offsetHeight - panelsBox.offsetHeight + Math.max(panelsBox.offsetHeight, ...panels.map((p) => p.offsetHeight));
      if (need > viewH() - pinTop()) { tooTall = true; live(); }
    };
    live();
    fits();
    phone.addEventListener("change", () => { live(); fits(); });
    onWidthResize(fits);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fits);
    scenes.push((pin) => {
      if (!isLive()) return;
      const p = progress(scene, pin);
      const at = Math.min(n - 1, Math.floor(p * n));
      const local = p * n - at;
      if (at !== stage) {
        stage = at;
        scene.dataset.stage = String(at);
        panels.forEach((el, i) => el.classList.toggle("is-on", i === at));
        names.forEach((el, i) => {
          el.classList.toggle("is-on", i === at);
          el.classList.toggle("is-done", i < at);
          if (i === at) el.setAttribute("aria-current", "step"); else el.removeAttribute("aria-current");
        });
      }
      // the layers come together over the first two stages; the scan runs down during the device check
      if (ph) {
        // the slices are back together by 60% of the Build stage, and from then on the screen clips like a real one
        const apart = Math.max(0, 1 - p * n / 1.6);
        ph.style.setProperty("--apart", (apart * apart).toFixed(3));   // eased: they settle gently rather than sliding in at full pace
        scene.classList.toggle("is-whole", apart === 0);

        ph.style.setProperty("--scan", at === 2 ? Math.min(1, local * 1.15).toFixed(3) : "0");
      }
      if (count) {
        const to = +count.dataset.to;
        const v = at === n - 1 ? Math.round(to * Math.min(1, local * 1.6) / 10000) * 10000 : 0;
        count.textContent = fmt.format(v) + (v >= to ? "+" : "");   // "as many as": the plus lands with the last figure
      }
    });
  });

  // home: the case studies as one scene. The scroll walks through each case: its box slides up over the last,
  // the words hand over and the figures count up, then the case holds briefly while its slideshow runs on its
  // own timer. Lengths are in screens.
  document.querySelectorAll('[data-scene="work"]').forEach((scene) => {
    const cases = [...scene.querySelectorAll(".wk-case")];
    const names = [...scene.querySelectorAll(".wk-names button")];
    const shows = cases.map((c) => c.querySelector("[data-slideshow]"));
    const counts = shows.map((sh) => (sh ? sh.querySelectorAll(".slide").length : 1));
    const n = cases.length;
    const phone = matchMedia("(max-width: 720px)");
    const HAND = 0.3;   // the box hand-over
    const HOLD = 0.5;   // how long each case stays put (the original pacing: about 0.8 of a screen per case)
    const widths = counts.map(() => HAND + HOLD);
    const starts = widths.map((_, k) => widths.slice(0, k).reduce((a, b) => a + b, 0));
    const total = starts[n - 1] + widths[n - 1] - HAND;
    scene.style.setProperty("--units", total.toFixed(2));
    const clamp = (v) => Math.min(1, Math.max(0, v));
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const figs = cases.map((c) => [...c.querySelectorAll("[data-count]")].map((dd) => {
      const m = dd.dataset.count.match(/^([\d,]+)(.*)$/);
      return m ? { dd, to: +m[1].replace(/,/g, ""), rest: m[2], comma: m[1].includes(",") } : null;
    }).filter(Boolean));
    const fmt = new Intl.NumberFormat("en-US");
    const countTo = (k, t) => figs[k].forEach((f) => {
      const v = Math.round(f.to * t);
      f.dd.textContent = (f.comma ? fmt.format(v) : String(v)) + (t >= 1 ? f.rest : f.rest.replace(/\+$/, ""));   // the plus lands with the last figure, as on Nike
    });
    // the first case is on screen from the start, so its figures run once, over a second, when they're first seen
    let firstRun = 0;
    const runFirst = () => {
      if (firstRun) return;
      firstRun = performance.now();
      const tick = (now) => {
        const t = clamp((now - firstRun) / 1100);
        if (isLive()) countTo(0, ease(t));
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };
    let on = -1;
    let held = [];
    const isLive = () => scene.classList.contains("is-live");
    const setHeld = (want) => {
      shows.forEach((sh, i) => {
        if (!sh || held[i] === want[i]) return;
        sh.dispatchEvent(new Event(want[i] ? "scene-hold" : "scene-release"));
      });
      held = want;
    };
    const live = () => {
      const roomy = viewH() - pinTop() >= 600 && innerWidth > 720;
      scene.classList.toggle("is-live", !reduceMotion && !phone.matches && roomy);
      on = -1;
      if (!isLive()) {
        cases.forEach((c) => { c.classList.remove("is-on", "is-shown"); ["--e", "--l", "--te", "--tl"].forEach((v) => c.style.removeProperty(v)); });
        names.forEach((b) => { b.classList.remove("is-on", "is-done"); b.removeAttribute("aria-current"); });
        figs.flat().forEach((f) => { f.dd.textContent = f.dd.dataset.count; });
        setHeld(cases.map(() => false));
      }
    };
    const unitPx = () => {
      const run = scene.offsetHeight - (viewH() - pinTop());
      return run / total;
    };
    names.forEach((b) => b.addEventListener("click", () => {
      const top = scene.getBoundingClientRect().top + window.scrollY;
      window.scrollTo({ top: top - pinTop() + starts[+b.dataset.go] * unitPx(), behavior: "smooth" });
    }));
    live();
    onWidthResize(live);
    phone.addEventListener("change", live);
    if (isLive() && figs[0].length) {
      countTo(0, 0);
      const first = new IntersectionObserver(([en]) => { if (en.isIntersecting) { runFirst(); first.disconnect(); } }, { threshold: 0.6 });
      first.observe(cases[0].querySelector(".wk-figs"));
    }
    scenes.push((pin) => {
      if (!isLive()) return;
      const r = scene.getBoundingClientRect();
      const run = r.height - (viewH() - pin);
      // screens of scroll into the scene: 0 as it pins, below 0 while it is still coming up the screen
      const u = run > 0 ? ((pin - r.top) / run) * total : 0;
      let at = 0;
      starts.forEach((st, k) => { if (u >= st - HAND / 2) at = k; });
      cases.forEach((c, k) => {
        const st = starts[k];
        const e = k === 0 ? 1 : clamp((u - (st - HAND)) / HAND);
        const l = k === n - 1 ? 0 : clamp((u - (st + widths[k] - HAND)) / HAND);
        c.style.setProperty("--e", e.toFixed(3));
        c.style.setProperty("--l", l.toFixed(3));
        // the words hand over in turn (out, then in) so two sets never overlap
        c.style.setProperty("--te", (k === 0 ? 1 : clamp(e * 2 - 1)).toFixed(3));
        c.style.setProperty("--tl", clamp(l * 2).toFixed(3));
        c.classList.toggle("is-shown", e > 0 && l < 1);
        c.classList.toggle("is-on", k === at);
        // the first case's figures count on their own as they come into view (below)
        if (k > 0) countTo(k, ease(clamp(e * 2 - 1)));
      });
      if (at !== on) {
        on = at;
        names.forEach((b, i) => {
          b.classList.toggle("is-on", i === at);
          b.classList.toggle("is-done", i < at);
          if (i === at) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
        });
        setHeld(cases.map((_, i) => i !== at));
      }
    });
  });

  document.querySelectorAll('[data-scene="timeline"]').forEach((scene) => {
    if (reduceMotion) return;
    const lanes = [...scene.querySelectorAll(".tl-lane")];
    const date = scene.querySelector(".tl-date");
    const live = scene.querySelector(".tl-live");
    const months = scene.querySelector(".tl-months");
    const board = scene.querySelector(".tl-board");
    const start = new Date(scene.dataset.start + "T12:00:00");
    const days = +scene.dataset.days;
    const fmt = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric" });
    scene.classList.add("is-live");
    scenes.push((pin) => {
      // the date moves through the middle 80% of the hold, so it rests on the first and last day
      let p;
      if (matchMedia("(max-width: 720px)").matches) {
        // phones: the board doesn't pin, so the date runs while the board crosses the screen
        const r = board.getBoundingClientRect();
        p = Math.min(1, Math.max(0, (viewH() * 0.75 - r.top) / (r.height + viewH() * 0.2)));
      } else {
        p = Math.min(1, Math.max(0, (progress(scene, pin) - 0.1) / 0.8));
      }
      const pct = p * 100;
      months.style.setProperty("--now", `${pct}%`);
      months.style.setProperty("--board-h", `${board.offsetHeight - 22}px`);
      date.textContent = fmt.format(new Date(start.getTime() + Math.round(p * days) * 864e5));
      let on = 0, always = false;
      lanes.forEach((l) => {
        const s = +l.dataset.start, e = +l.dataset.end;
        const fill = Math.min(1, Math.max(0, (pct - s) / (e - s)));
        l.querySelector(".tl-bar i").style.setProperty("--fill", fill.toFixed(3));
        const isOn = pct >= s && pct <= e;
        l.classList.toggle("is-on", isOn);
        if (!isOn) return;
        if ("always" in l.dataset) always = true; else on++;   // the smaller promotions ran throughout and are not counted
      });
      const big = on === 0 ? "Between campaigns" : on === 1 ? "1 campaign live" : `${on} campaigns live`;
      live.textContent = always ? `${big}, plus smaller promotions` : big;
    });
  });

  // the reference page tilts a little toward the pointer, like a sheet held up to read
  document.querySelectorAll(".ref-band").forEach((band) => {
    const page = band.querySelector(".ref-page");
    if (!page || reduceMotion) return;
    if (!canHover) {
      // phones and tablets: the sheet tilts with the device instead, relative to how it was first held.
      // Only where motion data needs no permission prompt (iOS asks, so iPhones and iPads get the flat sheet).
      if (!("DeviceOrientationEvent" in window) || typeof DeviceOrientationEvent.requestPermission === "function") return;
      let base = null;
      const onTilt = (e) => {
        if (e.beta == null || e.gamma == null) return;
        if (!base) base = { b: e.beta, g: e.gamma };
        const dx = Math.max(-1, Math.min(1, (e.gamma - base.g) / 25)), dy = Math.max(-1, Math.min(1, (e.beta - base.b) / 25));
        page.style.setProperty("--ry", `${(dx * 8).toFixed(2)}deg`);
        page.style.setProperty("--rx", `${(-dy * 6).toFixed(2)}deg`);
      };
      const start = () => window.addEventListener("deviceorientation", onTilt);
      start();
      return;
    }
    band.addEventListener("pointermove", (e) => {
      const r = band.getBoundingClientRect();
      const dx = (e.clientX - r.left) / r.width - 0.5, dy = (e.clientY - r.top) / r.height - 0.5;
      page.style.setProperty("--ry", `${(dx * 10).toFixed(2)}deg`);
      page.style.setProperty("--rx", `${(-dy * 7).toFixed(2)}deg`);
      page.style.setProperty("--rz", "14px");
      band.classList.add("is-near");
    });
    band.addEventListener("pointerleave", () => {
      ["--rx", "--ry", "--rz"].forEach((v) => page.style.removeProperty(v));
      band.classList.remove("is-near");
    });
  });

  // a video figure in a still walkthrough: a silent preview in place, the lightbox player on click
  document.querySelectorAll(".sc-video").forEach((btn) => {
    const item = JSON.parse(btn.parentElement.querySelector(".sc-video-data").textContent);
    if (autoObserver && !reduceMotion) autoObserver.observe(btn);
    btn.addEventListener("click", (e) => open([item], 0, e.detail > 0));
  });

  // a still walkthrough with one picture per stage: the picture changes as each stage reaches the middle of the window
  document.querySelectorAll(".scene.sc-still .sc-figs").forEach((figs) => {
    const scene = figs.closest(".scene");
    const panels = [...scene.querySelectorAll(".sc-panel")];
    const pics = [...figs.querySelectorAll("figure")];
    figs.classList.add("is-js");
    let on = -1;
    scenes.push(() => {
      const line = viewH() * 0.5;
      let at = 0;
      panels.forEach((p, i) => { if (p.getBoundingClientRect().top < line) at = i; });
      at = Math.min(at, pics.length - 1);
      if (at !== on) { on = at; pics.forEach((f, i) => f.classList.toggle("is-on", i === at)); }
    });
  });

  // learn-then-teach as a scene: the stage holds and each phase lights up in turn (desktop only; phones and
  // short windows get the free-scrolling version below)
  document.querySelectorAll('[data-scene="phases"]').forEach((scene) => {
    if (reduceMotion) return;
    const items = [...scene.querySelectorAll(".phases li")];
    const inner = scene.querySelector(".ph-stage > .prose");
    const n = items.length;
    const phone = matchMedia("(max-width: 720px)");
    let tooTall = false;
    const isLive = () => scene.classList.contains("is-live");
    const live = () => {
      scene.classList.toggle("is-live", !phone.matches && !tooTall);
      if (!isLive()) {
        scene.classList.remove("is-done");
        items.forEach((li) => { li.classList.remove("is-on"); li.style.removeProperty("--fill"); });
      }
    };
    const fits = () => {
      if (tooTall || phone.matches || !isLive()) return;
      if (inner.offsetHeight + 40 > viewH() - pinTop()) { tooTall = true; live(); }
    };
    live();
    fits();
    phone.addEventListener("change", () => { live(); fits(); });
    onWidthResize(fits);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fits);
    scenes.push((pin) => {
      if (!isLive()) return;
      const p = progress(scene, pin);
      const at = Math.min(n - 1, Math.floor(p * n));
      const local = p * n - at;
      items.forEach((li, i) => {
        li.style.setProperty("--fill", i < at ? "1" : i === at ? Math.min(1, local * 1.6).toFixed(3) : "0");
        li.classList.toggle("is-on", i <= at);
      });
      scene.classList.toggle("is-done", at === n - 1 && local > 0.45);
    });
  });

  // the phase words fill from grey to ink as they reach the middle of the screen (when the section is not a live scene)
  const fills = reduceMotion ? [] : [...document.querySelectorAll("[data-fill] li")];
  if (fills.length) {
    scenes.push(() => {
      const vh = viewH();
      fills.forEach((li) => {
        if (li.closest(".scene.is-live")) return;
        const r = li.getBoundingClientRect();
        const f = Math.min(1, Math.max(0, (vh * 0.85 - r.top) / (vh * 0.35)));
        li.style.setProperty("--fill", f.toFixed(3));
      });
    });
  }

  // the scene pages: each block rises in once as it arrives
  if (!reduceMotion && "IntersectionObserver" in window) {
    const blocks = [...document.querySelectorAll(".case-v2 .glance-wrap, .case-v2 .prose:not(.lede-wrap), .case-v2 .strip, .case-v2 .case-nav, .work .wk-case")];
    if (blocks.length) {
      document.documentElement.classList.add("js-reveal");
      const arrive = new IntersectionObserver((entries) => {
        for (const e of entries) {
          // in view, or already scrolled past (a jump down the page): shown, and no longer watched
          if (e.isIntersecting || e.boundingClientRect.bottom < 0) { e.target.classList.add("is-in"); arrive.unobserve(e.target); }
        }
      }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
      blocks.forEach((b) => { b.dataset.reveal = ""; arrive.observe(b); });
      // a jump down the page (a link to a section) skips blocks without ever showing them: on each scroll,
      // anything left above the window is simply shown, so scrolling back up never meets hidden text
      scenes.push(() => {
        blocks.forEach((b) => {
          if (!b.classList.contains("is-in") && b.getBoundingClientRect().bottom < 0) { b.classList.add("is-in"); arrive.unobserve(b); }
        });
      });
    }
  }

  if (scenes.length) {
    let queued = false;
    const run = () => { queued = false; const pin = pinTop(); scenes.forEach((f) => f(pin)); };
    const queue = () => { if (!queued) { queued = true; requestAnimationFrame(run); } };
    window.addEventListener("scroll", queue, { passive: true });
    onWidthResize(queue);
    run();
  }

  // ---------- visit alerts: a phone notification (ntfy app, subscribed to this topic) when someone opens the site ----------
  // One alert per visit: a page opened within 30 minutes of the last one counts as the same visit.
  // Opening the site once with ?me marks that device as Christian's (no alerts, and Umami stops counting it too);
  // ?me=off undoes it.

  (() => {
    const TOPIC = "cs-portfolio-n0iBxagSHhbI0lKZ";
    const VISIT_GAP = 30 * 60 * 1000;
    const store = (() => { try { return localStorage; } catch (e) { return null; } })();
    if (!store) return;
    const params = new URLSearchParams(location.search);
    if (params.has("me")) {
      const off = params.get("me") === "off";
      try {
        if (off) store.removeItem("umami.disabled"); else store.setItem("umami.disabled", "1");
      } catch (e) {}
      params.delete("me");
      history.replaceState(history.state, "", location.pathname + (params.toString() ? "?" + params : "") + location.hash);
      alert(off ? "Visit alerts and Umami are back on for this device."
                : "This device is marked as yours: no visit alerts, and Umami won't count it.");
      return;
    }
    if (location.hostname !== "csworkportfolio.github.io" || store.getItem("umami.disabled")) return;
    if (navigator.webdriver || /bot|crawl|spider|preview|headless/i.test(navigator.userAgent)) return;
    const now = Date.now();
    const last = Number(store.getItem("cs-visit-last")) || 0;
    try { store.setItem("cs-visit-last", String(now)); } catch (e) {}
    if (now - last < VISIT_GAP) return;

    // where they came from, by name for the usual places; no referrer means a typed link, a bookmark, or an app
    // (the LinkedIn and mail apps often hide where a link was opened from)
    const SOURCES = [
      [/(^|\.)(linkedin\.com|lnkd\.in)$/, "LinkedIn"], [/(^|\.)google\./, "Google"], [/(^|\.)bing\.com$/, "Bing"],
      [/(^|\.)duckduckgo\.com$/, "DuckDuckGo"], [/(^|\.)indeed\./, "Indeed"], [/(^|\.)glassdoor\./, "Glassdoor"],
      [/(^|\.)(facebook\.com|fb\.me)$/, "Facebook"], [/(^|\.)instagram\.com$/, "Instagram"],
      [/(^|\.)(x\.com|t\.co|twitter\.com)$/, "X"], [/(^|\.)github\.com$/, "GitHub"],
      [/(^|\.)(chatgpt\.com|openai\.com)$/, "ChatGPT"], [/(^|\.)(claude\.ai|perplexity\.ai)$/, "AI search"],
      [/mail\./, "Email"],
    ];
    let from = "Direct link or bookmark";
    try {
      const ref = document.referrer && new URL(document.referrer).hostname;
      if (ref && ref !== location.hostname) {
        from = (SOURCES.find(([re]) => re.test(ref)) || [, ref.replace(/^www\./, "")])[1];
      }
    } catch (e) {}
    const page = document.title.split(/\s+[|–—-]\s+/)[0] || location.pathname;

    // City, State, Country from the visitor's IP (GeoJS, free and keyless); if that's blocked, the time zone city
    const zone = (Intl.DateTimeFormat().resolvedOptions().timeZone || "").split("/").pop().replace(/_/g, " ");
    const place = fetch("https://get.geojs.io/v1/ip/geo.json")
      .then((r) => r.json())
      .then((g) => [g.city, g.region, g.country].filter(Boolean).join(", ") || Promise.reject())
      .catch(() => (zone ? `Near ${zone} (time zone)` : "Location unknown"));

    place.then((where) => {
      // A plain-text body keeps this a "simple" request (no CORS preflight); ntfy reads the JSON from it.
      fetch("https://ntfy.sh/", {
        method: "POST",
        keepalive: true,
        body: JSON.stringify({
          topic: TOPIC, title: "Website Visitor", message: [where, page, from].join("\n"),
          click: location.href,
        }),
      }).catch(() => {});
    });
  })();
})();
