// The AI page's demos (tools/build.py draws each one finished; this plays them). A demo plays only while it
// is on screen and stops where it is when it leaves or its pause button is pressed. With Reduce Motion on,
// every demo stays in its finished state and no video starts by itself.
(() => {
  "use strict";
  // the page inside itself (the last demo) loads with ?frame=1 or 2; those copies hold still
  const depth = +new URLSearchParams(location.search).get("frame") || 0;
  const still = depth > 0 || matchMedia("(prefers-reduced-motion: reduce)").matches;

  // one clock for every demo: a demo's waits only count down while it is playing
  const waiters = new Set();
  let last = performance.now();
  (function tick(now) {
    const dt = Math.min(now - last, 100);
    last = now;
    for (const w of waiters) {
      if (!w.demo.running) continue;
      w.left -= dt;
      if (w.left <= 0) { waiters.delete(w); w.done(); }
    }
    requestAnimationFrame(tick);
  })(last);

  function demo(fig) {
    const d = { fig, running: false, paused: false, seen: false };
    d.wait = (ms) => new Promise((done) => waiters.add({ demo: d, left: ms, done }));
    // type text into an element a few characters at a time (wider characters type a little slower)
    d.type = async (el, text, speed = 26) => {
      el.textContent = "";
      for (const ch of text) { el.textContent += ch; await d.wait(ch.charCodeAt(0) > 0x2e80 ? speed * 2.2 : speed); }
    };
    return d;
  }

  function wire(d, loop, hooks = {}) {
    const btn = d.fig.querySelector(".ai-toggle");
    const set = () => {
      d.running = d.visible && !d.paused;
      d.fig.classList.toggle("is-paused", d.paused);
      if (btn) btn.setAttribute("aria-label", d.paused ? "Play animation" : "Pause animation");
      hooks.change && hooks.change(d.running);
      if (d.running && !d.seen) { d.seen = true; loop(); }
    };
    btn && btn.addEventListener("click", () => { d.paused = !d.paused; set(); });
    new IntersectionObserver(([e]) => { d.visible = e.isIntersecting; set(); }, { threshold: 0.3 }).observe(d.fig);
  }

  const parse = (fig) => JSON.parse(fig.querySelector(".ai-data").textContent);

  // ---------- 1. the localization agent, in a copy of the Champions Hub ----------
  function localize(fig) {
    const data = parse(fig), d = demo(fig);
    const $ = (s) => fig.querySelector(s);
    const view = $(".hb-view"), hub = $(".hb"), cursor = $(".hb-cursor"), text = $(".hb-t");
    const items = [...fig.querySelectorAll(".hb-menu li[data-code]")];
    const cards = [...fig.querySelectorAll(".hb-card")];
    const set = (cls, on) => hub.classList.toggle(cls, on);
    // the Hub is drawn at 1280 by 708 and filmed like a camera: scaled to the window, leaning in on the Share
    // window when it opens; on a narrow screen it is shown larger and framed on the part in use
    const FOCUS = { feed: [335, 354], modal: [640, 290], top: [830, 354] };
    let focus = "feed";
    const frame = (f = focus) => {
      focus = f;
      const w = view.clientWidth, narrow = w < 640;
      const s = narrow ? w / 470 : w / 1280, h = 708 * (narrow ? w / 470 : s);
      const k = s * (!narrow && f === "modal" ? 1.22 : 1);
      const [cx, cy] = FOCUS[f];
      const clamp = (v, lo) => Math.min(0, Math.max(lo, v));
      view.style.setProperty("--hb-s", narrow ? w / 470 : s);
      view.style.setProperty("--hb-k", k);
      view.style.setProperty("--hb-tx", clamp(w / 2 - cx * k, w - 1280 * k));
      view.style.setProperty("--hb-ty", narrow ? 0 : clamp(h / 2 - cy * k, h - 708 * k));
    };
    new ResizeObserver(() => frame()).observe(view);
    frame(hub.classList.contains("is-open") ? "modal" : "feed");
    // the cursor's point, in the Hub's own 1280 by 708 pixels
    const point = (el, dx = 0.5, dy = 0.5) => {
      let x = 0, y = 0;
      for (let e = el; e && e !== hub; e = e.offsetParent) { x += e.offsetLeft; y += e.offsetTop; }
      cursor.style.left = x + el.offsetWidth * dx - 4 + "px";
      cursor.style.top = y + el.offsetHeight * dy - 2 + "px";
    };
    const art = (el, lines) => el.querySelectorAll("b, .hb-guide-btn").forEach((n, i) => { n.textContent = lines[i]; });
    // each card's English, to come back to
    const english = cards.map((c) => ({ h: c.querySelector("h4").textContent, p: c.querySelector(".hb-body")?.textContent,
      src: c.querySelector(".hb-src-v").textContent, when: c.querySelector(".hb-when").textContent }));
    const word = (c, en, auto) => {
      const q = (s) => c.querySelector(s), t = auto ? data.auto.cards[+c.dataset.i] : null;
      q("h4").textContent = t ? t.title : en.h;
      if (q(".hb-body")) q(".hb-body").textContent = t && t.body ? t.body : en.p;
      q(".hb-src-v").textContent = auto ? data.auto.src[en.src] || en.src : en.src;
      q(".hb-when").textContent = auto ? data.auto.when[en.when] || en.when : en.when;
      c.lang = auto ? "ja" : "en";
      const g = c.querySelector(".hb-guide");
      if (g) art(g, auto ? data.regions.find((r) => r.code === data.auto.code).art : data.art);
    };
    // the line under the demo says what is happening
    const note = fig.querySelector(".ai-note");
    const say = async (t) => {
      if (!note || note.textContent === t) return;
      note.classList.add("is-fading");
      await d.wait(250);
      note.textContent = t;
      note.classList.remove("is-fading");
    };
    let fixes = 1;
    const count = () => { $(".hb-count-v").textContent = fixes; $(".hb-unit").textContent = fixes === 1 ? "fix" : "fixes"; };
    if (still) return;
    async function loop() {
      for (;;) {
        // the feed in English, then the share window on the post
        ["is-open", "is-lang", "is-review", "is-menu", "is-sent", "is-press", "is-busy", "is-auto", "is-preview"].forEach((c) => set(c, false));
        cards.forEach((c, i) => word(c, english[i], false));
        fixes = 0; count(); frame("feed");
        text.lang = "en"; text.textContent = data.post; art($(".hb-photo"), data.art);
        cursor.style.left = "560px"; cursor.style.top = "560px";
        await say("The Champions Hub's Trending Posts, recreated from a screen recording. The post is a generic example.");
        await d.wait(1400);
        set("is-pointing", true);
        point($(".is-post .hb-share"));
        await d.wait(1100);
        say("An employee shares a post to LinkedIn.");
        set("is-press", true); await d.wait(250); set("is-press", false);
        set("is-open", true); frame("modal");
        await d.wait(1500);
        for (const [i, r] of data.regions.entries()) {
          // Translate opens the brand agent's regions; pick the next one
          point($(".hb-tr"));
          if (!i) say("Translate opens the brand agent, loaded with the style guide and brand guidelines.");
          await d.wait(i ? 700 : 1600);
          set("is-menu", true);
          await d.wait(400);
          point(items[i], 0.35);
          await d.wait(650);
          items.forEach((li, k) => li.classList.toggle("is-hover", k === i));
          await d.wait(300);
          set("is-menu", false); items[i].classList.remove("is-hover");
          $(".hb-lang-v").textContent = r.name; $(".hb-tone").textContent = r.tone; text.lang = r.code.toLowerCase();
          set("is-lang", true); set("is-review", false); set("is-busy", true);
          say(`The agent rewrites the post for ${r.name} readers. Tone: ${r.tone.toLowerCase()}.`);
          point($(".hb-text"), 0.85, 0.3);
          const m = r.text.match(/^(.*)\[(.*)\|(.*)\](.*)$/);
          await d.type(text, m ? m[1] + m[2] + m[4] : r.text, 22);
          art($(".hb-photo"), r.art);   // the graphic is localized too
          set("is-busy", false);
          // open the photo to show its words changed with the post
          art($(".hb-preview .hb-guide"), r.art);
          $(".hb-preview-v").textContent = r.name;
          point($(".hb-photo"));
          await d.wait(800);
          set("is-preview", true);
          say(`The graphic is localized into ${r.name} too.`);
          await d.wait(2000);
          set("is-preview", false);
          await d.wait(300);
          if (m) {
            // a Champion's fix, sent back so the agent learns it
            await d.wait(700);
            $(".hb-review-v").textContent = r.review;
            set("is-review", true);
            say("A Champion Advocate asks for a softer ask. The fix goes back to the agent, so it learns.");
            await d.wait(1500);
            text.innerHTML = "";
            const del = document.createElement("del"), ins = document.createElement("ins");
            del.textContent = m[2]; ins.textContent = m[3];
            text.append(m[1], del, " ", ins, m[4]);
            fixes += 1; count();
            await d.wait(2400);
            set("is-review", false);
          }
          await d.wait(m ? 600 : 1400);
        }
        // share it
        point($(".hb-b.is-blue"));
        await d.wait(1000);
        set("is-send", true); await d.wait(200); set("is-send", false);
        set("is-sent", true); set("is-open", false); frame("feed");
        say("Shared on LinkedIn, ready for its region.");
        await d.wait(2000);
        set("is-sent", false);
        // or switch the whole feed into one's own language and region, graphics included
        frame("top");
        say("Or an employee switches on Localize Every Post.");
        point($(".hb-auto"), 0.8);
        await d.wait(1300);
        set("is-auto", true);
        await d.wait(500);
        frame("feed");
        say(`The whole feed turns ${data.auto.name}, graphics included.`);
        for (const [i, c] of cards.entries()) {
          c.classList.add("is-sweep");
          await d.wait(260);
          word(c, english[i], true);
          await d.wait(140);
          c.classList.remove("is-sweep");
        }
        set("is-pointing", false);
        await d.wait(4200);
      }
    }
    wire(d, loop);
  }

  // ---------- 2. the editorial board ----------
  function board(fig) {
    const data = parse(fig), d = demo(fig);
    const rows = [...fig.querySelectorAll(".bd-table tbody tr")];
    const top = data.statuses.length - 1;
    const pill = (row, s) => {
      const el = row.querySelector(".bd-status");
      el.className = "bd-status s" + s; el.textContent = data.statuses[s];
    };
    const rules = [...fig.querySelectorAll(".bd-rules li")];
    async function loop() {
      for (;;) {
        rows.forEach((r) => { pill(r, 0); r.querySelector(".bd-ai").classList.remove("is-on"); });
        rules.forEach((li) => li.classList.remove("is-on"));
        await d.wait(700);
        for (const li of rules) { li.classList.add("is-on"); await d.wait(160); }
        for (let step = 1; step <= top; step++) {
          for (const [i, r] of rows.entries()) {
            if (Math.min(i + 1, top) < step) continue;
            pill(r, step);
            if (step === 1) r.querySelector(".bd-ai").classList.add("is-on");
            await d.wait(420);
          }
          await d.wait(500);
        }
        await d.wait(4200);
      }
    }
    wire(d, loop);
  }

  // ---------- 3. the Mars Men cut ----------
  function cut(fig) {
    const d = demo(fig);
    const video = fig.querySelector(".ct-video");
    const head = fig.querySelector(".ct-head"), script = fig.querySelector(".ct-script");
    const keep = [...fig.querySelectorAll(".ct-line[data-at]")];
    const clips = [...fig.querySelectorAll(".ct-final .ct-clip")];
    const data = parse(fig);
    // the transcript and the cut build once, the first time the demo comes into view
    fig.classList.add("is-fresh");
    async function loop() {
      fig.classList.add("is-reading");
      await d.wait(900);
      for (const el of fig.querySelectorAll(".ct-line.is-cut")) { el.classList.add("is-struck"); await d.wait(420); }
      fig.classList.add("is-picked");
      await d.wait(600);
      fig.classList.add("is-cutdone");
      for (const c of clips) { c.classList.add("is-on"); await d.wait(260); }
      fig.classList.remove("is-fresh");
    }
    function follow() {
      const t = video.currentTime;
      head.style.left = (t / data.duration) * 100 + "%";
      keep.forEach((el) => {
        const now = t >= +el.dataset.at && t < +el.dataset.to;
        if (now && !el.classList.contains("is-now")) {
          // keep the spoken line in view inside the transcript's own scroll, never moving the page
          const box = script.getBoundingClientRect(), r = el.getBoundingClientRect();
          if (r.top < box.top || r.bottom > box.bottom) script.scrollTo({ top: script.scrollTop + r.top - box.top - 12, behavior: "smooth" });
        }
        el.classList.toggle("is-now", now);
      });
      data.final.forEach((s, i) => clips[i].classList.toggle("is-now", t >= s.from && t < s.to));
      if (!video.paused) requestAnimationFrame(follow);
    }
    video.addEventListener("play", () => requestAnimationFrame(follow));
    video.addEventListener("seeked", follow);
    if (still) { fig.classList.remove("is-fresh"); video.controls = true; return; }
    wire(d, loop, {
      change(on) {
        if (on) { const p = video.play(); p && p.catch(() => {}); } else video.pause();
      },
    });
  }

  // ---------- 4. one episode, five pieces ----------
  function fan(fig) {
    const data = parse(fig), d = demo(fig);
    const canvas = fig.querySelector(".fn-canvas"), bar = fig.querySelector(".fn-wavebar");
    const marks = [...fig.querySelectorAll(".fn-mark")], cards = [...fig.querySelectorAll(".fn-card")];
    const N = 140, amp = [];
    let seed = 7;
    for (let i = 0; i < N; i++) { seed = (seed * 16807) % 2147483647; amp.push(0.25 + 0.75 * Math.abs(Math.sin(i * 0.37) * 0.6 + (seed / 2147483647 - 0.5))); }
    let progress = still ? 1 : 0;
    function draw() {
      const r = bar.getBoundingClientRect(), dpr = devicePixelRatio || 1;
      if (!r.width) return;
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      const g = canvas.getContext("2d"), cs = getComputedStyle(fig);
      g.scale(dpr, dpr);
      const w = r.width / N;
      for (let i = 0; i < N; i++) {
        const h = Math.max(3, amp[i] * r.height * 0.9);
        g.fillStyle = i / N < progress ? cs.getPropertyValue("--fn-on") : cs.getPropertyValue("--fn-off");
        g.beginPath(); g.roundRect(i * w + w * 0.2, (r.height - h) / 2, w * 0.6, h, w * 0.3); g.fill();
      }
    }
    new ResizeObserver(draw).observe(bar);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
    new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    async function loop() {
      for (;;) {
        progress = 0; draw();
        cards.forEach((c) => c.classList.remove("is-on")); marks.forEach((m) => m.classList.remove("is-on"));
        await d.wait(500);
        const order = data.outputs.map((o, i) => ({ at: o.at / data.episode.length, i })).sort((a, b) => a.at - b.at);
        let k = 0;
        for (let step = 0; step <= 100; step++) {
          progress = step / 100; draw();
          while (k < order.length && order[k].at <= progress) {
            marks[order[k].i].classList.add("is-on"); cards[order[k].i].classList.add("is-on"); k++;
            await d.wait(700);
          }
          await d.wait(70);
        }
        await d.wait(5000);
      }
    }
    if (!still) { fig.classList.add("is-fresh"); wire(d, loop); }
  }

  // ---------- 5. GEO and AEO ----------
  function geo(fig) {
    const d = demo(fig);
    const [kw, q] = fig.querySelectorAll(".geo-typed");
    const results = [...fig.querySelectorAll(".geo-results li")], fields = [...fig.querySelectorAll(".geo-fields li")];
    const answer = fig.querySelector(".geo-answer"), cite = fig.querySelector(".geo-cite");
    async function loop() {
      for (;;) {
        kw.textContent = ""; q.textContent = "";
        [...results, ...fields, answer, cite].forEach((el) => el.classList.remove("is-on"));
        await d.wait(600);
        await d.type(kw, kw.dataset.text, 70);
        for (const r of results) { await d.wait(220); r.classList.add("is-on"); }
        await d.wait(800);
        await d.type(q, q.dataset.text, 38);
        await d.wait(500);
        answer.classList.add("is-on");
        await d.wait(900);
        cite.classList.add("is-on");
        for (const f of fields) { await d.wait(500); f.classList.add("is-on"); }
        await d.wait(5000);
      }
    }
    if (!still) { fig.classList.add("is-fresh"); wire(d, loop); }
  }

  // ---------- 6. the tools: each screen tour plays while it is on screen ----------
  function tools(fig) {
    if (still) return;
    for (const v of fig.querySelectorAll(".tl-video")) {
      new IntersectionObserver(([e]) => {
        if (e.isIntersecting) { const p = v.play(); p && p.catch(() => {}); } else v.pause();
      }, { threshold: 0.4 }).observe(v);
    }
  }

  // ---------- 7. this site, inside itself ----------
  function meta(fig) {
    const d = demo(fig);
    const frame = fig.querySelector(".mt-frame"), view = fig.querySelector(".mt-view");
    const cursor = fig.querySelector(".mt-cursor"), chips = [...fig.querySelectorAll(".mt-chip")];
    // the copy is drawn at desktop size and scaled to the window; two copies deep, the window just says so
    new ResizeObserver(() => view.style.setProperty("--mt-scale", view.clientWidth / 1280)).observe(view);
    if (depth >= 2) { frame.remove(); fig.classList.add("is-here"); return; }
    const src = frame.dataset.src.replace("frame=1", "frame=" + (depth + 1));
    if (depth > 0) { frame.src = src; fig.classList.add("is-here"); return; }
    new IntersectionObserver(([e], o) => { if (e.isIntersecting) { frame.src = src; o.disconnect(); } }, { rootMargin: "600px 0px" }).observe(fig);
    const win = () => frame.contentWindow;
    // scroll the copy smoothly, a step per frame, on the demo's own clock
    async function glide(to, ms) {
      const w = win(); if (!w) return;
      const from = w.scrollY, steps = Math.max(1, Math.round(ms / 16));
      for (let i = 1; i <= steps; i++) {
        const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        w.scrollTo({ top: from + (to - from) * e, behavior: "instant" });
        await d.wait(16);
      }
    }
    const point = (x, y) => { cursor.style.left = x + "%"; cursor.style.top = y + "%"; };
    const chip = (i) => chips.forEach((c, k) => c.classList.toggle("is-on", k === i));
    async function loop() {
      for (;;) {
        fig.classList.add("is-close"); fig.classList.remove("is-here", "is-pointing"); chip(-1);
        const doc = frame.contentDocument, site = doc && doc.getElementById("site");
        const target = site ? site.getBoundingClientRect().top + win().scrollY - 60 : 0;
        if (win()) win().scrollTo({ top: target, behavior: "instant" });
        await d.wait(500);
        fig.classList.remove("is-close");          // zoom out of the page you are reading
        chip(0);
        await d.wait(3000);
        fig.classList.add("is-pointing"); point(62, 40);
        await d.wait(900);
        chip(1); point(30, 22);
        await glide(0, 2200);                       // up to the top of the page
        await d.wait(1000);
        point(70, 70);
        const end = doc ? doc.documentElement.scrollHeight - win().innerHeight : 0;
        await glide(end * 0.55, 4200);              // down through the demos
        point(48, 55);
        await glide(target, 2600);                  // and back to this section
        fig.classList.add("is-here"); chip(2); point(54, 62);
        await d.wait(5200);
      }
    }
    frame.addEventListener("load", () => wire(d, loop), { once: true });
  }

  const kinds = { localize, board, cut, fan, geo, tools, meta };
  for (const fig of document.querySelectorAll(".ai-demo[data-demo]")) {
    const k = kinds[fig.dataset.demo];
    if (!k) continue;
    if (still && !["localize", "cut", "tools", "meta"].includes(fig.dataset.demo)) continue;
    k(fig);
  }
})();
