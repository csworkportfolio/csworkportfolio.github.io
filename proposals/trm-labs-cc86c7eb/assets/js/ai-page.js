// The AI page's demos (tools/build.py draws each one finished; this plays them). A demo plays only while it
// is on screen and stops where it is when it leaves or its pause button is pressed. With Reduce Motion on,
// every demo stays in its finished state and no video starts by itself.
(() => {
  "use strict";
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

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
      const chars = [...text];   // set from the text each step, so a pause can show it whole and the typing still picks up
      el.textContent = "";
      for (let i = 0; i < chars.length; i++) { el.textContent = chars.slice(0, i + 1).join(""); await d.wait(chars[i].charCodeAt(0) > 0x2e80 ? speed * 2.2 : speed); }
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
    d.resume = () => { if (d.paused) { d.paused = false; set(); } };
    new IntersectionObserver(([e]) => { d.visible = e.isIntersecting; set(); }, { threshold: 0.1 }).observe(d.fig);
  }

  const parse = (fig) => JSON.parse(fig.querySelector(".ai-data").textContent);

  // ---------- 1. the localization agent, in a copy of the Champions Hub ----------
  function localize(fig) {
    const data = parse(fig), d = demo(fig);
    const $ = (s) => fig.querySelector(s);
    const view = $(".hb-view"), hub = $(".hb"), cursor = $(".hb-cursor"), text = $(".hb-t");
    const items = [...fig.querySelectorAll(".hb-menu li[data-code]")];
    const cards = [...fig.querySelectorAll(".hb-card")], feed = $(".hb-feed");
    const set = (cls, on) => hub.classList.toggle(cls, on);
    // the Hub is drawn at 1280 by 708 and filmed like a camera: scaled to the window, leaning in on the Share
    // window when it opens; on a narrow screen it is shown larger and framed on the part in use
    const FOCUS = { feed: [335, 354], modal: [640, 290], top: [830, 354] };
    let focus = "feed";
    // on a phone the Hub switches to its mobile layout, one post wide (drawn at 390 by 760)
    let mobile = false;
    const frame = (f = focus) => {
      focus = f;
      const w = view.clientWidth;
      // a wide screen can still ask for the phone layout (the switcher above): it stands as a phone inside the same window
      const device = fig.dataset.view === "mobile" && w >= 640;
      mobile = w < 640 || device;
      hub.classList.toggle("is-mobile", mobile);
      fig.classList.toggle("is-mobile", mobile && !device);
      fig.classList.toggle("is-device", device);
      if (mobile) {
        // Mobile on a wide screen: the desktop Hub stays behind, still, and the phone screen overlaps its lower right
        // corner, like Apple's device line-ups (screens only, no device frames); the window keeps its size
        const h = device ? 708 * w / 1280 + 36 : 760 * w / 390;
        const s = device ? h * 0.9 / 760 : w / 390;
        view.style.height = h + "px";
        const tx = device ? w - 390 * s - w * 0.035 : 0, ty = device ? h - 760 * s - h * 0.02 : 0;
        for (const [k, v] of [["--hb-s", s], ["--hb-k", s], ["--hb-tx", tx], ["--hb-ty", ty]]) view.style.setProperty(k, v);
        if (device) {
          const bs = (w * 0.86) / 1280;
          view.style.setProperty("--hb-bs", bs);
          view.style.setProperty("--hb-bx", w * 0.025);
          view.style.setProperty("--hb-by", (h - 708 * bs) / 2 - h * 0.04);
        }
        return;
      }
      const s = w / 1280, h = 708 * s;
      const k = s * (f === "modal" ? 1.22 : 1);
      const [cx, cy] = FOCUS[f];
      const clamp = (v, lo) => Math.min(0, Math.max(lo, v));
      view.style.height = h + "px";
      view.style.setProperty("--hb-s", s);
      view.style.setProperty("--hb-k", k);
      view.style.setProperty("--hb-tx", clamp(w / 2 - cx * k, w - 1280 * k));
      view.style.setProperty("--hb-ty", clamp(h / 2 - cy * k, h - 708 * k));
    };
    // the still desktop Hub that stands behind the phone in the Mobile view
    const back = hub.cloneNode(true);
    back.className = "hb hb-back";
    back.querySelectorAll(".hb-cursor, .hb-modal, .hb-dim, .hb-toast, .hb-preview").forEach((el) => el.remove());
    view.insertBefore(back, hub);
    new ResizeObserver(() => frame()).observe(view);
    // a click (or Enter) opens the Hub larger, over the page; another click, Esc or the backdrop closes it
    view.tabIndex = 0;
    view.setAttribute("role", "button");
    const full = (on) => {
      fig.classList.toggle("is-full", on);
      document.documentElement.classList.toggle("ai-locked", on);
      view.setAttribute("aria-label", on ? "Close the larger view" : "Open the Champions Hub larger");
      requestAnimationFrame(() => frame());
    };
    full(false);
    view.addEventListener("click", () => full(!fig.classList.contains("is-full")));
    view.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); full(!fig.classList.contains("is-full")); } });
    fig.querySelector(".ai-stage").addEventListener("click", (e) => { if (e.target === e.currentTarget && fig.classList.contains("is-full")) full(false); });
    addEventListener("keydown", (e) => { if (e.key === "Escape" && fig.classList.contains("is-full")) full(false); });
    frame(hub.classList.contains("is-open") ? "modal" : "feed");
    // the cursor's point, in the Hub's own 1280 by 708 pixels
    // on a phone there is no pointer: each tap shows as a touch that pulses where the finger lands
    const touch = document.createElement("span");
    touch.className = "hb-touch";
    hub.append(touch);
    const tap = () => {
      if (!mobile) return;
      touch.style.left = parseFloat(cursor.style.left) + 4 + "px";
      touch.style.top = parseFloat(cursor.style.top) + 2 + "px";
      touch.classList.remove("is-tap"); void touch.offsetWidth; touch.classList.add("is-tap");
    };
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
    const bar = fig.querySelector(".hb-chapters");
    if (still) { for (const el of fig.querySelectorAll(".hb-chapters, .hb-views")) el.hidden = true; return; }
    // the demo runs in chapters; the bar under it shows where it is and jumps to any chapter
    const steps = [...bar.querySelectorAll("button")];
    const review = data.regions.find((r) => r.review);
    const plain = data.regions.filter((r) => r !== review);   // the Korean version, the one a Champion fixed, comes last
    let gen = 0;
    const STOP = Symbol("stop");
    const w = async (ms) => { const g = gen; await d.wait(ms); if (g !== gen) throw STOP; };
    const tp = async (el, s, speed = 22) => {
      el.textContent = "";
      for (const ch of s) { el.textContent += ch; await w(ch.charCodeAt(0) > 0x2e80 ? speed * 2.2 : speed); }
    };
    const mark = (n, p = 0) => steps.forEach((b, i) => {
      b.classList.toggle("is-on", i === n);
      b.classList.toggle("is-done", i < n);
      b.style.setProperty("--p", i === n ? p : i < n ? 1 : 0);
      if (i === n) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    const parts = (r) => r.text.match(/^(.*)\[(.*)\|(.*)\](.*)$/);
    const showRegion = (r, fixed) => {
      $(".hb-lang-v").textContent = r.name; $(".hb-tone").textContent = r.tone; text.lang = r.code.toLowerCase();
      $(".hb-hash").textContent = r.tags; art($(".hb-photo"), r.art);
      const m = parts(r);
      if (!m) { text.textContent = r.text; return; }
      if (!fixed) { text.textContent = m[1] + m[2] + m[4]; return; }
      text.innerHTML = "";
      const del = document.createElement("del"), ins = document.createElement("ins");
      del.textContent = m[2]; ins.textContent = m[3];
      text.append(m[1], del, " ", ins, m[4]);
    };
    const reset = () => {
      ["is-open", "is-lang", "is-review", "is-menu", "is-sent", "is-press", "is-busy", "is-auto", "is-preview", "is-send"].forEach((c) => set(c, false));
      items.forEach((li) => li.classList.remove("is-hover"));
      cards.forEach((c, i) => word(c, english[i], false));
      feed.style.transform = "";
      fixes = 0; count(); frame("feed");
      text.lang = "en"; text.textContent = data.post; $(".hb-hash").textContent = data.tags; art($(".hb-photo"), data.art);
    };
    const open = () => { set("is-open", true); set("is-pointing", true); frame("modal"); };

    // one language: pick it under Translate, watch the post and its graphic change
    async function region(r, n, p0, p1) {
      const k = data.regions.indexOf(r);
      point($(".hb-tr"));
      await w(700);
      tap(); set("is-menu", true);
      await w(400);
      point(items[k], 0.35);
      await w(650);
      tap(); items.forEach((li, j) => li.classList.toggle("is-hover", j === k));
      await w(300);
      set("is-menu", false); items[k].classList.remove("is-hover");
      $(".hb-lang-v").textContent = r.name; $(".hb-tone").textContent = r.tone; text.lang = r.code.toLowerCase();
      set("is-lang", true); set("is-review", false); set("is-busy", true);
      say(`It rewrites the post for ${r.name} readers, in a ${r.tone.toLowerCase()} tone.`);
      point($(".hb-text"), 0.85, 0.3);
      const m = parts(r);
      await tp(text, m ? m[1] + m[2] + m[4] : r.text);
      $(".hb-hash").textContent = r.tags;   // the brand tag stays; the topic tag is the one people search there
      art($(".hb-photo"), r.art);           // the graphic is localized too
      set("is-busy", false);
      mark(n, (p0 + p1) / 2);
      // open the photo to show its words changed with the post
      art($(".hb-preview .hb-guide"), r.art);
      $(".hb-preview-v").textContent = r.name;
      point($(".hb-photo"));
      await w(800);
      tap(); set("is-preview", true);
      say(`The words on the graphic change to ${r.name} too.`);
      await w(2000);
      set("is-preview", false);
      await w(600);
      mark(n, p1);
    }

    const chapters = [
      async (jumped) => {   // share a post
        reset();
        cursor.style.left = "560px"; cursor.style.top = "560px";
        await say("This is a copy of the Champions Hub, rebuilt from a screen recording. The post is a made-up example.");
        await w(jumped ? 900 : 1400);
        set("is-pointing", true);
        point($(".is-post .hb-share"));
        await w(1100);
        say("An employee clicks Share to post it on LinkedIn.");
        tap(); set("is-press", true); await w(250); set("is-press", false);
        open();
        mark(0, 1);
        await w(1500);
      },
      async (jumped) => {   // localize into each region
        if (jumped) { reset(); open(); await w(900); }
        say("Translate opens the brand agent. It knows our style guide and brand guidelines.");
        point($(".hb-tr"));
        await w(1200);
        for (const [i, r] of plain.entries()) await region(r, 1, i / plain.length, (i + 1) / plain.length);
      },
      async (jumped) => {   // the Korean version, and a Champion's fix
        if (jumped) { reset(); open(); const last = plain[plain.length - 1]; showRegion(last); set("is-lang", true); await w(900); }
        await region(review, 2, 0, 0.5);
        $(".hb-review-v").textContent = review.review;
        set("is-review", true);
        say("A Champion Advocate makes the ending a little softer. The fix goes back to the agent so it learns.");
        await w(1500);
        showRegion(review, true);
        fixes += 1; count();
        mark(2, 1);
        await w(2400);
        set("is-review", false);
        await w(600);
      },
      async (jumped) => {   // send it
        if (jumped) { reset(); open(); showRegion(review, true); set("is-lang", true); fixes = 1; count(); }
        say("With the fix in, the Korean version is ready to send.");
        await w(jumped ? 1200 : 600);
        point($(".hb-b.is-blue"));
        await w(1000);
        tap(); set("is-send", true); await w(200); set("is-send", false);
        set("is-sent", true); set("is-open", false); frame("feed");
        say("Then it goes out on LinkedIn.");
        mark(3, 1);
        await w(2000);
        set("is-sent", false);
      },
      async (jumped) => {   // or the whole feed, in one's own language and region
        if (jumped) { reset(); set("is-pointing", true); await w(600); }
        frame("top");
        say("Employees can also switch on Localize Every Post.");
        point($(".hb-auto"), 0.8);
        await w(1300);
        tap(); set("is-auto", true);
        await w(500);
        frame("feed");
        say(`Now the whole feed reads in ${data.auto.name}.`);
        for (const [i, c] of cards.entries()) {
          if (mobile) { feed.style.transform = `translateY(${-c.offsetTop}px)`; await w(700); }   // scroll the one-wide feed to each post
          c.classList.add("is-sweep");
          await w(260);
          word(c, english[i], true);
          await w(140);
          c.classList.remove("is-sweep");
          mark(4, (i + 1) / cards.length);
        }
        set("is-pointing", false);
        await w(4200);
      },
    ];
    let cur = 0;
    async function run(from) {
      const g = ++gen;
      let jumped = from > 0;
      try {
        for (let n = from; ; n = (n + 1) % chapters.length) {
          cur = n;
          mark(n, 0);
          await chapters[n](jumped);
          jumped = false;
        }
      } catch (e) { if (e !== STOP || g === gen) throw e; }
    }
    steps.forEach((b, n) => b.addEventListener("click", (e) => { e.stopPropagation(); d.resume(); run(n); }));
    // Desktop or Mobile: redraw the Hub that way and play the current chapter again
    const views = [...fig.querySelectorAll(".hb-views button")];
    views.forEach((b) => b.addEventListener("click", () => {
      fig.dataset.view = b.dataset.view;
      views.forEach((v) => v.setAttribute("aria-pressed", String(v === b)));
      reset(); frame("feed");
      if (d.seen) run(cur);
    }));
    wire(d, () => run(0));
  }

  // ---------- 2. the editorial board in Monday.com, and the Zapier workflow behind its Generate button ----------
  function board(fig) {
    const data = parse(fig), d = demo(fig);
    const $ = (s) => fig.querySelector(s);
    const view = $(".mb-view"), mb = $(".mb"), cursor = $(".mb-cursor");
    const rows = [...fig.querySelectorAll(".mb-row[data-i]")];
    const cells = [...fig.querySelectorAll(".mb-battery i")];
    const steps = [...fig.querySelectorAll(".zp-step")];
    const top = data.statuses.length - 1;
    // which app is in front: the demo's own (Zapier while the zap runs), or the one the switch, a tab or a card locks
    let zap = false, mode = "auto";
    const shown = () => {
      const on = mode === "zp" || (mode === "auto" && zap);
      mb.classList.toggle("is-zap", on);
      fig.classList.toggle("is-zap", on);
      mb.classList.toggle("is-locked", mode !== "auto");
      frame();
    };
    const set = (cls, on) => { if (cls === "is-zap") { zap = on; shown(); } else mb.classList.toggle(cls, on); };
    const front = $(".ai-front");
    const modes = { auto: ["Auto", "automatic", "keep monday.com in front", "mb"], mb: ["monday.com", "monday.com, locked", "keep Zapier in front", "zp"],
      zp: ["Zapier", "Zapier, locked", "go back to automatic", "auto"] };
    const lock = (m) => {
      mode = m;
      front.dataset.mode = m;
      front.querySelector("span").textContent = modes[m][0];
      front.setAttribute("aria-label", `Window in front: ${modes[m][1]}. Press to ${modes[m][2]}`);
      shown();
    };
    front.addEventListener("click", () => lock(modes[mode][3]));
    // a tab (or, on a phone, the card behind) locks that app in front; the same again goes back to automatic
    const pickApp = (m) => lock(mode === m ? "auto" : m);
    $(".mbt.is-mb").addEventListener("click", () => pickApp("mb"));
    $(".mbt.is-zp").addEventListener("click", () => pickApp("zp"));
    // each screen is drawn at 1200 by 640 and scaled to the window; a phone gets the mobile layouts, drawn at 420 by 700
    let mobile = false;
    // filmed like the Hub: on a wide screen the view leans in on the part in use (the Generate column, then
    // Claude's instructions) and eases back out; a phone shows the whole screen
    const FOCUS = { gen: [1060, 300, 1.3], claude: [880, 330, 1.22] };
    let focus = "all";
    const frame = (f = focus) => {
      focus = f;
      const w = view.clientWidth;
      mobile = w < 640;
      mb.classList.toggle("is-mobile", mobile);
      fig.classList.toggle("is-mobile", mobile);
      const s = w / (mobile ? 420 : 1200), h = (mobile ? 700 : 640) * s;
      view.style.setProperty("--mb-s", s);
      view.style.height = h + "px";
      const [cx, cy, z] = (!mobile && mode === "auto" && FOCUS[f]) || [0, 0, 1];   // a locked app shows whole
      const k = s * z, clamp = (v, lo) => Math.min(0, Math.max(lo, v));
      view.style.setProperty("--mb-k", k);
      view.style.setProperty("--mb-tx", z === 1 ? 0 : clamp(w / 2 - cx * k, w - 1200 * k));
      view.style.setProperty("--mb-ty", z === 1 ? 0 : clamp(h / 2 - cy * k, h - 640 * k));
    };
    new ResizeObserver(() => frame()).observe(view);
    frame();
    // a click (or Enter) opens it larger, over the page; another click, Esc or the backdrop closes it
    view.tabIndex = 0;
    view.setAttribute("role", "button");
    const full = (on) => {
      fig.classList.toggle("is-full", on);
      document.documentElement.classList.toggle("ai-locked", on);
      view.setAttribute("aria-label", on ? "Close the larger view" : "Open the Monday.com demo larger");
      requestAnimationFrame(() => frame());
    };
    full(false);
    view.addEventListener("click", (e) => {
      // on a phone, a tap on the card behind brings that app to the front instead
      const pane = mobile && e.target.closest(".mb-pane, .zp-pane");
      if (pane && pane.classList.contains("zp-pane") !== mb.classList.contains("is-zap")) { pickApp(pane.classList.contains("zp-pane") ? "zp" : "mb"); return; }
      full(!fig.classList.contains("is-full"));
    });
    view.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); full(!fig.classList.contains("is-full")); } });
    fig.querySelector(".ai-stage").addEventListener("click", (e) => { if (e.target === e.currentTarget && fig.classList.contains("is-full")) full(false); });
    addEventListener("keydown", (e) => { if (e.key === "Escape" && fig.classList.contains("is-full")) full(false); });
    if (still) { const bar = $(".hb-chapters"); if (bar) bar.hidden = true; return; }
    const touch = document.createElement("span");
    touch.className = "mb-touch";
    mb.append(touch);
    // the cursor's point in the canvas: on a wide screen the track slides, so on the zap the point moves by a screen's
    // width; on a phone the two are stacked cards, so the point is where the card sits
    const point = (el, dx = 0.5, dy = 0.5) => {
      let x = 0, y = 0;
      for (let e = el; e && e !== mb; e = e.offsetParent) { x += e.offsetLeft; y += e.offsetTop; }
      if (mb.classList.contains("is-zap") && !mobile) x -= 1200;
      x += el.offsetWidth * dx; y += el.offsetHeight * dy;
      cursor.style.left = x - 4 + "px"; cursor.style.top = y - 2 + "px";
      touch.style.left = x + "px"; touch.style.top = y + "px";
    };
    const tap = () => { if (mobile) { touch.classList.remove("is-tap"); void touch.offsetWidth; touch.classList.add("is-tap"); } };
    const status = (row, k) => { const el = row.querySelector(".mb-status"); el.className = "mb-status s" + k; el.textContent = data.statuses[k]; };
    const tally = () => {
      const n = data.statuses.map((_, k) => rows.filter((r) => r.querySelector(".mb-status").classList.contains("s" + k)).length);
      cells.forEach((c, k) => c.style.setProperty("--n", n[k] * 5 / rows.length));
    };
    // the demo runs in chapters; the bar under it shows where it is and jumps to any chapter
    const bars = [...fig.querySelectorAll(".hb-chapters button")];
    let gen = 0;
    const STOP = Symbol("stop");
    const w = async (ms) => { const g = gen; await d.wait(ms); if (g !== gen) throw STOP; };
    // the line under the demo says what is happening
    const note = fig.querySelector(".ai-note");
    const say = async (s) => {
      if (!note || note.textContent === s) return;
      note.classList.add("is-fading");
      await d.wait(250);
      note.textContent = s;
      note.classList.remove("is-fading");
    };
    const mark = (n, p = 0) => bars.forEach((b, i) => {
      b.classList.toggle("is-on", i === n);
      b.classList.toggle("is-done", i < n);
      b.style.setProperty("--p", i === n ? p : i < n ? 1 : 0);
      if (i === n) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    const press = async (r) => {
      point(r.querySelector(".mb-btn"));
      await w(800);
      tap(); r.classList.add("is-press"); await w(180); r.classList.remove("is-press");
    };
    const fill = (r) => { const ai = r.querySelector(".mb-ai"); ai.classList.remove("is-busy"); ai.classList.add("is-on"); status(r, 1); tally(); };
    const reset = () => {
      ["is-zap", "is-writing", "is-toast"].forEach((c) => set(c, false));
      rows.forEach((r) => { status(r, 0); r.querySelector(".mb-ai").classList.remove("is-on", "is-busy"); r.classList.remove("is-press"); });
      steps.forEach((s) => s.classList.remove("is-run", "is-ok"));
      $(".zp-out-v").textContent = "";
      tally();
      set("is-pointing", !mobile);
      frame("all");
    };
    const chapters = [
      async () => {   // every item starts as an idea; Generate on the first one
        reset();
        cursor.style.left = "760px"; cursor.style.top = "560px";
        say("This is a copy of Monday.com and Zapier, rebuilt for this page. The rows are made-up examples.");
        await w(1600);
        say("Each item has a Generate button. Clicking it starts a Zapier workflow.");
        frame("gen");
        await press(rows[0]);
        rows[0].querySelector(".mb-ai").classList.add("is-busy");
        mark(0, 1);
        await w(300);
      },
      async (jumped) => {   // the board slides away to the zap behind the button, which runs step by step
        if (jumped) { reset(); rows[0].querySelector(".mb-ai").classList.add("is-busy"); await w(400); }
        frame("all");
        set("is-zap", true);
        say("Behind the button is a zap with three steps.");
        await w(1300);
        point(steps[0], 0.9);
        say("First, it picks up the click in Monday.");
        steps[0].classList.add("is-run"); await w(1100);
        steps[0].classList.replace("is-run", "is-ok");
        mark(1, .2);
        point(steps[1], 0.9);
        steps[1].classList.add("is-run"); set("is-writing", true);
        say("Then it sends the item to Claude, with our knowledge base as the instructions.");
        await w(600);
        point($(".zp-files"), 0.5, 0.5);   // Claude works from the knowledge base
        frame("claude");
        await w(2000);
        set("is-writing", false); steps[1].classList.replace("is-run", "is-ok");
        $(".zp-out-v").textContent = data.rows[0].ai;
        say("Claude writes the brief.");
        mark(1, .6);
        await w(900);
        point(steps[2], 0.9);
        frame("all");
        say("Last, it puts the result back in the board.");
        steps[2].classList.add("is-run"); await w(1100);
        steps[2].classList.replace("is-run", "is-ok");
        await w(1600);
        set("is-zap", false);   // back on the board, the result is in
        await w(900);
        fill(rows[0]);
        say("Back in Monday, the brief is in the row, ready for me to edit.");
        mark(1, 1);
        await w(900);
        await w(900);
      },
      async (jumped) => {   // the same zap for the other items, each a click away
        if (jumped) { reset(); fill(rows[0]); await w(500); }
        say("Every other item works the same way, one click each.");
        for (const [i, r] of rows.slice(1).entries()) {
          await press(r);
          r.querySelector(".mb-ai").classList.add("is-busy");
          set("is-toast", true);
          await w(1100);
          fill(r);
          set("is-toast", false);
          mark(2, (i + 1) / (rows.length - 1));
          await w(250);
        }
      },
      async (jumped) => {   // then the work moves along the statuses
        if (jumped) { reset(); rows.forEach(fill); await w(500); }
        say("Then each item moves along the board until it's scheduled.");
        for (let step = 2; step <= top; step++) {
          for (const r of rows.slice(step - 1)) {
            point(r.querySelector(".mb-status"));
            await w(380);
            tap(); status(r, step); tally();
            await w(120);
          }
          mark(3, (step - 1) / (top - 1));
          await w(400);
        }
        set("is-pointing", false);
        await w(4200);
      },
    ];
    async function run(from) {
      const g = ++gen;
      let jumped = from > 0;
      try {
        for (let n = from; ; n = (n + 1) % chapters.length) {
          mark(n, 0);
          await chapters[n](jumped);
          jumped = false;
        }
      } catch (e) { if (e !== STOP || g === gen) throw e; }
    }
    bars.forEach((b, n) => b.addEventListener("click", () => { d.resume(); run(n); }));
    wire(d, () => run(0));
  }

  // ---------- 3. the Mars Men cut, in a copy of Premiere Pro ----------
  function cut(fig) {
    const d = demo(fig);
    const data = parse(fig);
    const view = fig.querySelector(".pr-view"), pr = fig.querySelector(".pr");
    const video = fig.querySelector(".ct-video");
    const head = fig.querySelector(".pr-head"), scrub = fig.querySelector(".pr-scrub-head"), script = fig.querySelector(".ct-script");
    const clocks = [...fig.querySelectorAll(".pr-tc-now")];
    const keep = [...fig.querySelectorAll(".ct-line[data-at]")];
    const clips = [...fig.querySelectorAll(".is-v1 .pr-clip")], audio = [...fig.querySelectorAll(".is-a1 .pr-clip")];
    // drawn at 1280 by 800 and scaled to the window; a phone gets the narrower layout, drawn at 420 by 726. The
    // ChatGPT window (drawn 380 wide) overlaps Premiere's right side: on a wide screen the two sit level, Premiere the
    // bigger one on the left 84%, ChatGPT smaller (28% wide, 80% of Premiere's height) and centered beside it; on a
    // phone they stack like cards in Apple Wallet, the same size, the one behind showing its top edge above the other
    const stage = fig.querySelector(".pr-stage"), cl = fig.querySelector(".cl-window");
    const frame = () => {
      const W = stage.clientWidth, mobile = W < 640;
      pr.classList.toggle("is-mobile", mobile);
      fig.classList.toggle("is-mobile", mobile);
      const pw = mobile ? W : W * 0.84, s = pw / (mobile ? 420 : 1280);
      view.style.setProperty("--pr-s", s);
      view.style.height = (mobile ? 726 : 800) * s + "px";
      const ph = view.parentElement.offsetHeight;
      const peek = 46, cw = mobile ? W : W * 0.28, cs = cw / 380, chH = (mobile ? ph : ph * 0.8) / cs;
      const cx = W - cw, cy = mobile ? 0 : ph * 0.1;
      stage.style.setProperty("--peek", peek + "px");
      stage.style.setProperty("--pw", pw + "px");
      stage.style.setProperty("--cl-s", cs);
      stage.style.setProperty("--cl-h", chH);
      stage.style.setProperty("--cx", cx + "px");
      stage.style.setProperty("--cy", cy + "px");
      stage.style.setProperty("--st-h", (mobile ? ph + peek : Math.max(ph, cy + chH * cs)) + "px");
    };
    new ResizeObserver(frame).observe(stage);
    frame();
    const tc = (sec) => {
      const f = Math.round(sec * 30), p = (n) => String(n).padStart(2, "0");
      return `00:${p(Math.floor(f / 1800) % 60)}:${p(Math.floor(f / 30) % 60)}:${p(f % 30)}`;
    };
    // the transcript and the cut build once, the first time the demo comes into view
    fig.classList.add("is-fresh");
    async function loop() {
      fig.classList.add("is-reading");
      await d.wait(900);
      for (const el of fig.querySelectorAll(".ct-line.is-cut")) { el.classList.add("is-struck"); await d.wait(420); }
      fig.classList.add("is-picked");
      await d.wait(600);
      fig.classList.add("is-cutdone");
      for (const [i, c] of clips.entries()) { c.classList.add("is-on"); audio[i].classList.add("is-on"); await d.wait(260); }
      fig.classList.remove("is-fresh");
    }
    function follow() {
      const t = video.currentTime, p = Math.min(1, t / data.duration);
      head.style.setProperty("--p", p);
      scrub.style.setProperty("--p", p);
      clocks.forEach((c) => { c.textContent = tc(t); });
      keep.forEach((el) => {
        const now = t >= +el.dataset.at && t < +el.dataset.to;
        if (now && !el.classList.contains("is-now")) {
          // keep the spoken line in view inside the transcript's own scroll, never moving the page
          const box = script.getBoundingClientRect(), r = el.getBoundingClientRect();
          if (r.top < box.top || r.bottom > box.bottom) script.scrollTo({ top: script.scrollTop + (r.top - box.top) / (box.height / script.clientHeight) - 12, behavior: "smooth" });
        }
        el.classList.toggle("is-now", now);
      });
      chapter(t);
      data.final.forEach((s, i) => { const on = t >= s.from && t < s.to; clips[i].classList.toggle("is-now", on); audio[i].classList.toggle("is-now", on); });
      if (!video.paused) requestAnimationFrame(follow);
    }
    // the chapters under the video: each fills as it plays, a tap jumps the video there, and the line under it says
    // how AI helped with that part
    const bars = [...fig.querySelectorAll(".hb-chapters button")], note = fig.querySelector(".ai-note");
    let said = -1;
    const msgs = [...fig.querySelectorAll(".cl-msg")];
    function chapter(t) {
      const n = Math.max(0, data.chapters.findIndex((c) => t >= c.from && t < c.to));
      bars.forEach((b, i) => {
        const c = data.chapters[i];
        b.classList.toggle("is-on", i === n);
        b.style.setProperty("--p", i < n ? 1 : i > n ? 0 : Math.min(1, (t - c.from) / (c.to - c.from)));
      });
      msgs.forEach((m) => m.classList.toggle("is-later", +m.dataset.ch > n));
      ahead = data.chat.some((m) => m.ch === n);
      stack();
      if (n !== said && note) {
        said = n;
        note.classList.add("is-fading");
        setTimeout(() => { note.textContent = data.chapters[n].say; note.classList.remove("is-fading"); }, 250);
      }
    }
    // which window is in front: automatic (ChatGPT in the chapters it was used in, Premiere otherwise), or locked
    // by the switch; three presses bring it back to automatic
    const front = fig.querySelector(".ai-front");
    const modes = { auto: ["Auto", "automatic", "keep ChatGPT in front", "gpt"], gpt: ["ChatGPT", "ChatGPT, locked", "keep Premiere in front", "pr"],
      pr: ["Premiere", "Premiere, locked", "go back to automatic", "auto"] };
    let ahead = true, up = null;
    function stack() {
      const mode = front ? front.dataset.mode : "auto";
      const gpt = mode === "gpt" || (mode === "auto" && ahead);
      if (gpt === up) return;
      up = gpt;
      stage.classList.toggle("is-gpt", gpt);
      cl.classList.toggle("is-up", gpt);
      view.parentElement.classList.toggle("is-up", !gpt);
    }
    function lock(mode) {
      const m = modes[mode];
      if (front) {
        front.dataset.mode = mode;
        front.querySelector("span").textContent = m[0];
        front.setAttribute("aria-label", `Window in front: ${m[1]}. Press to ${m[2]}`);
      }
      cl.setAttribute("aria-label", mode === "gpt" ? "ChatGPT, locked in front. Press to go back to automatic" : "The chat with ChatGPT about the cut. Press to keep it in front");
      stack();
    }
    front && front.addEventListener("click", () => lock(modes[front.dataset.mode][3]));
    // a click on the ChatGPT window locks it in front; another click goes back to automatic
    cl.tabIndex = 0;
    cl.setAttribute("role", "button");
    const pick = () => lock(front && front.dataset.mode === "gpt" ? "auto" : "gpt");
    cl.addEventListener("click", pick);
    cl.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    lock("auto");
    // a click on the Premiere window (or Enter) opens both windows larger, over the page; another click, Esc or the
    // backdrop closes it
    const win = view.parentElement;
    win.tabIndex = 0;
    win.setAttribute("role", "button");
    const full = (on) => {
      fig.classList.toggle("is-full", on);
      document.documentElement.classList.toggle("ai-locked", on);
      win.setAttribute("aria-label", on ? "Close the larger view" : "Open Premiere and ChatGPT larger");
      requestAnimationFrame(frame);
    };
    full(false);
    // Premiere behind ChatGPT: a click brings it to the front (and keeps it there) instead
    win.addEventListener("click", () => { if (up) lock("pr"); else full(!fig.classList.contains("is-full")); });
    win.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); full(!fig.classList.contains("is-full")); } });
    fig.querySelector(".ai-stage").addEventListener("click", (e) => { if (e.target === e.currentTarget && fig.classList.contains("is-full")) full(false); });
    addEventListener("keydown", (e) => { if (e.key === "Escape" && fig.classList.contains("is-full")) full(false); });
    bars.forEach((b, i) => b.addEventListener("click", () => {
      video.currentTime = data.chapters[i].from + 0.01;
      d.resume && d.resume();
      follow();
    }));
    video.addEventListener("play", () => { view.classList.add("is-playing"); requestAnimationFrame(follow); });
    video.addEventListener("pause", () => view.classList.remove("is-playing"));
    video.addEventListener("seeked", follow);
    // the sound button: his voice on or off (the video starts muted, as browsers ask)
    const sound = fig.querySelector(".ai-sound");
    sound && sound.addEventListener("click", () => {
      video.muted = !video.muted;
      sound.setAttribute("aria-pressed", String(!video.muted));
      sound.setAttribute("aria-label", video.muted ? "Turn sound on" : "Turn sound off");
    });
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
    // the episode's own waveform: its loudness in slices, measured from the audio (tools/ai_episode.py)
    const amp = data.episode.peaks, N = amp.length;
    // each moment sits on the middle of the bar it falls in, so its dot, the playhead and that bar share one line
    const snap = (p) => (Math.min(N - 1, Math.floor(p * N)) + 0.5) / N;
    marks.forEach((m) => { const i = +m.querySelector("button").dataset.i; m.style.left = `${snap(data.outputs[i].at / data.episode.length) * 100}%`; });
    let progress = still ? 1 : 0;
    function draw() {
      const b = bar.getBoundingClientRect(), dpr = devicePixelRatio || 1;
      if (!b.width) return;
      // the canvas is a whole number of screen pixels, shown at exactly that size, so nothing is resampled (blurred)
      canvas.width = Math.round(b.width * dpr); canvas.height = Math.round(b.height * dpr);
      canvas.style.width = `${canvas.width / dpr}px`; canvas.style.height = `${canvas.height / dpr}px`;
      const r = { width: canvas.width / dpr, height: canvas.height / dpr };
      const g = canvas.getContext("2d"), cs = getComputedStyle(fig);
      g.scale(dpr, dpr);
      const w = r.width / N;
      for (let i = 0; i < N; i++) {
        const h = Math.max(3, amp[i] * r.height * 0.78);   // the loudest bars stop short, so the playhead runs past them
        g.fillStyle = i / N < progress ? cs.getPropertyValue("--fn-on") : cs.getPropertyValue("--fn-off");
        g.beginPath(); g.roundRect(i * w + w * 0.2, (r.height - h) / 2, w * 0.6, h, w * 0.3); g.fill();
      }
      // the playhead, as in Voice Memos: a thin line through the waveform with a dot at each end, and the time under
      // it counting along
      if (progress > 0 && progress < 1) {
        // the line sits on whole screen pixels (2 points wide), so its edges stay sharp
        const lw = 2 * Math.round(dpr), xd = Math.round(progress * r.width * dpr), x = xd / dpr;
        g.fillStyle = cs.getPropertyValue("--fn-head");
        g.fillRect((xd - lw / 2) / dpr, 3, lw / dpr, r.height - 6);   // the full height, its dots at the edges
        for (const y of [3, r.height - 3]) { g.beginPath(); g.arc(x, y, 3, 0, Math.PI * 2); g.fill(); }
      }
      if (now) {
        const t = Math.round(progress * data.episode.length);
        now.textContent = `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
      }
    }
    const now = fig.querySelector(".fn-ep-now");
    // the newsletter and the blog post show on their cards as the opened piece itself, scaled down to the card's
    // width: the newsletter runs to the card's foot, the blog post (laid out narrower, so its text reads bigger) runs
    // off it, as a page does
    const fits = [...fig.querySelectorAll(".fn-fit")];
    const fit = () => fits.forEach((f) => {
      const box = f.parentElement, piece = f.firstElementChild;
      const W = piece.offsetWidth, bw = box.clientWidth, bh = box.clientHeight;
      if (!W || !bw) return;
      const k = bw / W;
      piece.style.minHeight = `${Math.ceil(bh / k)}px`;
      f.style.transform = `scale(${k})`;
    });
    fits.forEach((f) => { new ResizeObserver(fit).observe(f.parentElement); f.querySelectorAll("img").forEach((im) => im.addEventListener("load", fit)); });
    fit();
    new ResizeObserver(draw).observe(bar);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
    new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    // the line under the demo says what is happening: the moments being found, then each piece as it lands
    const note = fig.querySelector(".ai-note");
    // a piece's line ("9:45: a 48-second clip...") shows its time in blue above it: "Content Developed from 9:45"
    const say = (t) => {
      const m = /^(\d+:\d\d): (.)(.*)$/.exec(t);
      const text = m ? m[2].toUpperCase() + m[3] : t;
      if (!note || note.textContent === text) return;
      note.classList.add("is-fading");
      setTimeout(() => {
        note.textContent = text;
        if (m) note.dataset.step = `Content Developed from ${m[1]}`; else delete note.dataset.step;
        note.classList.remove("is-fading");
      }, 250);
    };
    async function loop() {
      for (;;) {
        progress = 0; draw();
        cards.forEach((c) => c.classList.remove("is-on")); marks.forEach((m) => m.classList.remove("is-on"));
        await d.wait(500);
        say(data.says.start);
        const order = data.outputs.map((o, i) => ({ at: snap(o.at / data.episode.length), i })).sort((a, b) => a.at - b.at);
        // the playhead takes the same time to reach each moment however far apart they sit in the episode, and
        // each piece holds long enough to read its caption
        const glide = async (to) => {
          const from = progress;
          for (let f = 1; f <= 20; f++) { progress = from + (to - from) * (1 - (1 - f / 20) ** 2); draw(); await d.wait(50); }
        };
        await d.wait(1400);
        for (const o of order) {
          await glide(o.at);
          marks[o.i].classList.add("is-on"); cards[o.i].classList.add("is-on"); say(data.says.each[o.i]);
          await d.wait(2600);
        }
        await glide(1);
        say(data.says.end);
        await d.wait(5000);
        await done();   // with sound on, it starts over only once the clip being heard has played to its end
      }
    }
    // the two clips play small, muted, while the demo plays; a card opens its piece full screen, sized to fit (the
    // clips with sound)
    const clips = [...fig.querySelectorAll(".fn-video")];
    const play = (on) => clips.forEach((v) => { if (on) { const p = v.play(); p && p.catch(() => {}); } else v.pause(); });
    // the sound button: one voice only, the LinkedIn clip's (his mouth on screen matches what you hear), unless a
    // number or card picked the other clip; the waveform is only a map of the episode and has no sound of its own
    const sound = fig.querySelector(".ai-sound");
    let loud = false, heard = clips[0];
    // resolves when the sound is off, or when the clip being heard reaches its end (the clips loop, so its end shows
    // as its time jumping back to the start)
    const done = () => new Promise((ok) => {
      if (!loud) return ok();
      let last = heard.currentTime;
      const tick = () => {
        const t = heard.currentTime;
        if (!loud || t < last || t >= heard.duration - 0.2) { heard.removeEventListener("timeupdate", tick); ok(); }
        last = t;
      };
      heard.addEventListener("timeupdate", tick);
    });
    const voice = () => clips.forEach((v) => { v.muted = !(loud && v === heard); });
    sound && sound.addEventListener("click", () => {
      loud = !loud;
      sound.setAttribute("aria-pressed", String(loud));
      sound.setAttribute("aria-label", loud ? "Turn sound off" : "Turn sound on");
      voice();
      if (loud) { heard.currentTime = 0; const p = heard.play(); p && p.catch(() => {}); }
    });
    const sheet = fig.querySelector(".fn-sheet"), bigs = [...fig.querySelectorAll(".fn-big")];
    let opener = null;
    const close = () => {
      if (sheet.hidden) return;
      bigs.forEach((b) => { b.hidden = true; const v = b.querySelector("video"); v && v.pause(); });
      sheet.hidden = true;
      document.documentElement.classList.remove("ai-locked");
      play(d.running);
      opener && opener.focus();
    };
    let shown = 0;
    // show piece i full size (the one before or after it from the arrows, wrapping round)
    const showBig = (i) => {
      shown = (i + bigs.length) % bigs.length;
      bigs.forEach((b) => { b.hidden = +b.dataset.i !== shown; const v = b.querySelector("video"); if (v && +b.dataset.i !== shown) v.pause(); });
      const v = bigs[shown].querySelector("video");
      if (v) { v.currentTime = 0; const p = v.play(); p && p.catch(() => {}); }
    };
    fig.querySelectorAll(".fn-open").forEach((btn, i) => btn.addEventListener("click", () => {
      opener = btn;
      const small = btn.querySelector(".fn-video");
      if (small) { heard = small; voice(); }   // a clip picked here is the one the sound button plays from now on
      sheet.hidden = false;
      document.documentElement.classList.add("ai-locked");   // full screen over the page, which stays put
      play(false);   // the small clips wait, so the opened one is the only voice
      showBig(i);
      sheet.querySelector(".fn-close").focus();
    }));
    sheet.querySelector(".fn-prev").addEventListener("click", () => showBig(shown - 1));
    sheet.querySelector(".fn-next").addEventListener("click", () => showBig(shown + 1));
    addEventListener("keydown", (e) => {
      if (sheet.hidden) return;
      if (e.key === "ArrowLeft") showBig(shown - 1);
      if (e.key === "ArrowRight") showBig(shown + 1);
    });
    // a number on the waveform opens its piece, the same as its card
    const opens = [...fig.querySelectorAll(".fn-open")];
    fig.querySelectorAll(".fn-mark button").forEach((m) => m.addEventListener("click", () => opens[+m.dataset.i].click()));
    sheet.querySelector(".fn-close").addEventListener("click", close);
    sheet.addEventListener("click", (e) => { if (e.target === sheet) close(); });
    addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    if (!still) { fig.classList.add("is-fresh"); wire(d, loop, { change: play }); }
  }

  // ---------- 5. GEO and AEO ----------
  function geo(fig) {
    const d = demo(fig), data = parse(fig);
    const cases = [...fig.querySelectorAll(".geo-case")], picks = [...fig.querySelectorAll(".geo-switch button")];
    let now = 0, gen = 0;
    const show = (k) => {
      now = k;
      cases.forEach((c, i) => { c.hidden = i !== k; });
      fig.querySelectorAll(".geo-fine").forEach((f) => { f.hidden = +f.dataset.case !== k; });
      const sec = document.getElementById("geo");   // the section's label takes the picked brand's color
      if (sec) sec.dataset.case = data.cases[k].id;
      fig.dataset.case = data.cases[k].id;   // and so does its caption's step label
      picks.forEach((p, i) => p.setAttribute("aria-pressed", String(i === k)));
    };
    // the picked example plays through once (the keywords typed and their results, the question and its answer, then
    // the page fields both of them read) and stays whole; the reset button or the switch plays it from the start
    // the caption in the box: what each step shows, with its step number above it
    const live = fig.querySelector(".geo-live");
    const say = (k, n) => {
      const all = data.cases[k].says, t = all[n];
      if (!live || live.textContent === t) return;
      live.classList.add("is-fading");
      setTimeout(() => { live.textContent = t; live.dataset.step = `Step ${n + 1} of ${all.length}`; live.classList.remove("is-fading"); }, 250);
    };
    async function play(k, g) {
      const c = cases[k];
      const [kw, q] = c.querySelectorAll(".geo-typed");
      const results = [...c.querySelectorAll(".geo-results li")], fields = [...c.querySelectorAll(".geo-fields li")];
      const answer = c.querySelector(".geo-answer"), cite = c.querySelector(".geo-cite"), sr = c.querySelector(".geo-sr");
      const ask = c.querySelector(".geo-ask"), dots = c.querySelector(".geo-dots");
      const wait = async (ms) => { await d.wait(ms); if (g !== gen) throw g; };
      // the search typed a few characters at a time; a reset stops it where it is
      const type = async (el, speed) => {
        const chars = [...el.dataset.text];
        for (let i = 0; i < chars.length; i++) { el.textContent = chars.slice(0, i + 1).join(""); await wait(speed); }
      };
      kw.textContent = ""; q.textContent = q.dataset.text;   // the question arrives whole, as a sent message does
      [...results, ...fields, ask, dots, answer, cite, sr].forEach((el) => el && el.classList.remove("is-on"));
      say(k, 0);
      await wait(600);
      await type(kw, 70);
      say(k, 1);
      for (const r of results) { await wait(220); r.classList.add("is-on"); }
      await wait(1800);
      say(k, 2);
      await wait(400);
      ask.classList.add("is-on");
      await wait(700);
      dots.classList.add("is-on");   // the AI typing
      await wait(1500);
      say(k, 3);
      dots.classList.remove("is-on");
      answer.classList.add("is-on");
      await wait(900);
      cite.classList.add("is-on");
      await wait(1400);
      say(k, 4);
      for (const f of fields) { await wait(500); f.classList.add("is-on"); }
      if (sr) { await wait(2400); say(k, 5); sr.classList.add("is-on"); }   // then where it was measured
    }
    const run = () => { const g = ++gen; play(now, g).catch(() => { /* a reset or a pick started it again */ }); };
    picks.forEach((p, k) => p.addEventListener("click", () => { show(k); if (!still) run(); }));
    const reset = fig.querySelector(".ai-reset");
    reset && reset.addEventListener("click", run);
    show(0);
    if (!still) { fig.classList.add("is-fresh"); wire(d, run); }   // it first plays when it comes into view
  }

  // ---------- 6. the tools: each screen tour plays while it is on screen ----------
  function tools(fig) {
    fig.querySelectorAll(".hh-screen").forEach(heardhum);
    if (still) return;
    for (const v of fig.querySelectorAll(".tl-video")) {
      new IntersectionObserver(([e]) => {
        if (e.isIntersecting) { const p = v.play(); p && p.catch(() => {}); } else v.pause();
      }, { threshold: 0.4 }).observe(v);
    }
  }

  // heardhum's walkthrough on its tool card: the menu bar catches a call, the recording opens, a voice gets its
  // name and the summary gets two small edits, then it starts over
  function heardhum(screen) {
    const view = screen.querySelector(".hh-view"), hh = view.querySelector(".hh"), cursor = hh.querySelector(".hh-cursor");
    const data = JSON.parse(screen.querySelector(".hh-data").textContent);
    const $ = (s) => hh.querySelector(s), $$ = (s) => [...hh.querySelectorAll(s)];
    const fit = () => view.style.setProperty("--hh-s", view.clientWidth / 720);
    new ResizeObserver(fit).observe(view);
    fit();
    if (still) return;   // stays on the finished transcript
    const d = demo(screen), w = d.wait;
    const set = (cls, on) => hh.classList.toggle(cls, on);
    const point = (el, dx = 0.5, dy = 0.5) => {
      const a = hh.getBoundingClientRect(), b = el.getBoundingClientRect(), s = a.width / 720;
      cursor.style.left = (b.left - a.left + b.width * dx) / s - 3 + "px";
      cursor.style.top = (b.top - a.top + b.height * dy) / s - 2 + "px";
    };
    const click = async () => { cursor.classList.add("is-click"); await w(140); cursor.classList.remove("is-click"); };
    // the selected stretch of transcript, a word at a time
    const sel = $(".hh-sel");
    sel.replaceChildren(...sel.textContent.match(/\S+\s*/g).map((t) => {   // each word keeps its space, so the highlight runs on
      const x = document.createElement("span");
      x.className = "hh-w";
      x.textContent = t;
      return x;
    }));
    const words = $$(".hh-w");
    const spk = $$('.hh-spk[data-s="1"]'), edit = $(".hh-edit"), add = $(".hh-add"), addV = $(".hh-add-v");
    const big = $(".hh-big-v"), line = $(".hh-line-v"), clock = $(".hh-clock"), row = $(".hh-row.is-new"), badge = $(".hh-badge-v");
    const newEdit = edit.textContent, newLine = add.dataset.text;
    const [mm, ss] = data.length.split(":").map(Number), total = mm * 60 + ss;
    const time = (t) => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;

    function reset() {
      ["is-card", "is-rec", "is-win", "is-page", "is-sum", "is-pop", "is-hover"].forEach((c) => set(c, false));
      set("is-pointing", true);
      spk.forEach((s) => (s.textContent = "Speaker 1"));
      edit.textContent = edit.dataset.old;
      edit.classList.remove("is-on", "is-typing");
      add.classList.add("is-off");
      add.classList.remove("is-typing");
      addV.textContent = "";
      words.forEach((x) => x.classList.remove("is-on"));
      row.classList.add("is-off");
      row.classList.remove("is-press");
      big.textContent = "Start Recording";
      line.textContent = "Watching for calls";
      $(".hh-field-v").textContent = "";
    }
    async function loop() {
      for (;;) {
        reset();
        cursor.style.left = "380px"; cursor.style.top = "250px";
        await w(700);
        // 1. the whale in the menu bar: its card is watching for calls, and one starts recording by itself
        point($(".hh-mbi"));
        await w(900);
        await click(); set("is-card", true);
        await w(1500);
        set("is-rec", true);
        line.textContent = "Recording";
        for (let k = 0; k <= 24; k++) {
          const t = Math.round(total * (k / 24) ** 1.6);
          clock.textContent = time(t);
          big.textContent = "Stop Recording  " + time(t);
          await w(k < 4 ? 450 : 85);
        }
        await w(500);
        point($(".hh-big"));
        await w(900);
        await click();
        set("is-rec", false);
        big.textContent = "Start Recording";
        line.textContent = "Saving and transcribing…";
        await w(1200);
        set("is-card", false);
        // 2. the window: the call lands in All Files, then its transcript opens and a stretch is selected
        set("is-win", true);
        badge.textContent = "Queued";
        badge.parentElement.classList.add("is-q");
        await w(500);
        row.classList.remove("is-off");
        await w(1100);
        badge.textContent = "Summarized";
        badge.parentElement.classList.remove("is-q");
        await w(500);
        point(row.querySelector(".hh-row-t"), 0.3);
        await w(900);
        await click(); row.classList.add("is-press");
        await w(250);
        set("is-page", true);
        await w(1100);
        point(words[0], 0);
        await w(850);
        for (const x of words) { x.classList.add("is-on"); point(x, 1); await w(110); }
        await w(1400);
        // 3. a name for Speaker 1, and every line of that voice takes it
        const first = $(".is-first .hh-spk");
        point(first);
        await w(800);
        words.forEach((x) => x.classList.remove("is-on"));
        set("is-hover", true);
        await w(500);
        await click();
        const r = first.getBoundingClientRect(), a = hh.getBoundingClientRect(), s = a.width / 720;
        const pop = $(".hh-pop");
        pop.style.left = (r.left - a.left) / s - 8 + "px";
        pop.style.top = (r.bottom - a.top) / s + 8 + "px";
        set("is-pop", true);
        await w(400);
        await d.type($(".hh-field-v"), data.name, 70);
        await w(400);
        point($(".hh-save"));
        await w(800);
        await click(); $(".hh-save").classList.add("is-press");
        await w(150);
        $(".hh-save").classList.remove("is-press");
        set("is-pop", false); set("is-hover", false);
        for (const x of spk) { x.textContent = data.name; x.classList.add("is-flash"); await w(160); }
        await w(700);
        spk.forEach((x) => x.classList.remove("is-flash"));
        await w(600);
        // 4. the summary: one word changed and a line added
        point($(".hh-seg .is-s"));
        await w(900);
        await click(); set("is-sum", true);
        await w(1200);
        point(edit);
        await w(900);
        await click(); await w(120); await click();
        edit.classList.add("is-on");
        await w(600);
        edit.classList.remove("is-on");
        edit.classList.add("is-typing");
        await d.type(edit, newEdit, 80);
        edit.classList.remove("is-typing");
        await w(700);
        const last = add.previousElementSibling;
        point(last.firstElementChild, 1);
        await w(800);
        await click();
        add.classList.remove("is-off");
        add.classList.add("is-typing");
        await d.type(addV, newLine, 45);
        await w(400);
        add.classList.remove("is-typing");
        set("is-pointing", false);
        await w(2600);
      }
    }
    wire(d, loop);
  }

  const kinds = { localize, board, cut, fan, geo, tools };
  for (const fig of document.querySelectorAll(".ai-demo[data-demo]")) {
    const k = kinds[fig.dataset.demo];
    if (!k) continue;
    if (still && !["localize", "board", "cut", "tools"].includes(fig.dataset.demo)) continue;
    k(fig);
  }
})();

// A demo told in steps names its step above its caption ("Step 2 of 4"), following the chapter bar
for (const live of document.querySelectorAll(".ai-live")) {
  const bars = [...live.parentElement.querySelectorAll(".hb-chapters button")];
  const step = () => {
    const i = bars.findIndex((b) => b.classList.contains("is-on"));
    if (i >= 0) live.dataset.step = `Step ${i + 1} of ${bars.length}`;
  };
  bars.forEach((b) => new MutationObserver(step).observe(b, { attributes: true, attributeFilter: ["class"] }));
  step();
}
