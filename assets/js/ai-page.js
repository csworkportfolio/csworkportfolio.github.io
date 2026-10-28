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

  // ---------- 1. the localization agent ----------
  function localize(fig) {
    const data = parse(fig), d = demo(fig);
    const $ = (s) => fig.querySelector(s);
    const text = $(".loc-text"), review = $(".loc-review"), status = $(".loc-status"), count = $(".loc-count");
    const tabs = [...fig.querySelectorAll(".loc-tab")];
    let fixes = 0;
    const setCount = () => { count.textContent = fixes; $(".loc-unit").textContent = fixes === 1 ? "fix" : "fixes"; };
    async function loop() {
      for (;;) {
        fixes = 0; setCount();
        for (const [i, r] of data.regions.entries()) {
          tabs.forEach((t, k) => t.classList.toggle("is-on", k === i));
          $(".loc-name").textContent = r.name;
          $(".loc-code").textContent = r.code;
          $(".loc-tone-v").textContent = r.tone;
          text.lang = r.code.toLowerCase();
          review.classList.remove("is-on");
          fig.classList.add("is-busy"); fig.classList.remove("is-ready");
          status.textContent = "Rewriting for " + r.name;
          const m = r.text.match(/^(.*)\[(.*)\|(.*)\](.*)$/);
          await d.type(text, m ? m[1] + m[2] + m[4] : r.text);
          fig.classList.remove("is-busy");
          if (m) {
            status.textContent = "In review";
            await d.wait(900);
            $(".loc-review-v").textContent = r.review;
            review.classList.add("is-on");
            await d.wait(1500);
            text.innerHTML = "";
            const del = document.createElement("del"), ins = document.createElement("ins");
            del.textContent = m[2]; ins.textContent = m[3];
            text.append(m[1], del, " ", ins, m[4]);
            fixes += 1; setCount();
            status.textContent = "Fix sent back to the agent";
            await d.wait(2200);
          }
          fig.classList.add("is-ready");
          status.textContent = "Ready to share";
          await d.wait(m ? 1800 : 1500);
        }
        await d.wait(1200);
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
    if (still && !["cut", "tools", "meta"].includes(fig.dataset.demo)) continue;
    k(fig);
  }
})();
