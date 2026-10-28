// The Cohesity post journey (three.js): one post goes into the localization agent, steps out through the
// Champions Portal in every language, fills the Champions Hub and is shared around the world.
// The scene has no background of its own, so it sits on the light and the dark page alike.
// three.js loads only when the scene nears the screen, and the scene plays only while it is on screen.
(() => {
  "use strict";
  const stage = document.querySelector(".pj-stage");
  if (!stage) return;
  const THREE_SRC = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";

  const near = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    near.disconnect();
    if (window.THREE) return start();
    const s = document.createElement("script");
    s.src = THREE_SRC; s.onload = start; s.onerror = () => stage.closest(".pj").remove();
    document.head.append(s);
  }, { rootMargin: "600px 0px" });
  near.observe(stage);

  function start() {
  // ---------- Timeline: six steps, a transition between each ----------
  // Each caption is a few short beats that fade in one after another. Holds are set to reading time:
  // about 3.5 words a second, plus a moment to take in the picture.
  const BEATS = [
    { parts: ["One piece of content.", "Written in any language, from anywhere in the world."], hold: 3.6 },
    { parts: ["The agent knows the brand, the goals, the product.", "It rewrites the post for every language and region."], hold: 6.4 },
    { parts: ["Each language steps out through the Champions Portal.", "I review every version with my team and select Champion advocates.", "Every rewrite makes the agent sharper."], hold: 7.8 },
    { parts: ["Now it's ready to share.", "Every region browses the same story, in its own language."], hold: 5.4 },
    { parts: ["Advocates hit share.", "The agent already shaped every word for their region.", "Resilience everywhere."], hold: 6.6 },
    { parts: ["Awareness. Word of mouth. Demo requests."], hold: 5 },
  ];
  const T = 1.6, TAIL = 2.8;            // the tail fades to dark and cuts back to the start, so the loop is seamless
  const TR = (i) => (i === 4 ? 0.45 : T);   // the cut from the globe to the closing caption is quick
  const starts = []; let acc = 0;
  BEATS.forEach((b, i) => { starts.push(acc); acc += b.hold + (i < BEATS.length - 1 ? TR(i) : TAIL); });
  const TOTAL = acc;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  function where(t) {
    for (let i = 0; i < BEATS.length; i++) {
      const s = starts[i], h = BEATS[i].hold;
      if (t < s + h) return { b: i, tr: false, k: (t - s) / h };
      if (i < BEATS.length - 1 && t < s + h + TR(i)) return { b: i, tr: true, k: (t - s - h) / TR(i) };
    }
    return { b: 5, tr: false, k: 1, tail: true, tk: clamp((t - starts[5] - BEATS[5].hold) / TAIL) };
  }
  const ease = (k) => (k = clamp(k), k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
  const span = (k, a, b) => clamp((k - a) / (b - a));
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  const mix = (a, b, k) => a.clone().lerp(b, k);

  // ---------- Theme: colors baked into the card textures, redrawn when the page switches ----------
  const THEMES = {
    light: { ink: "#1d1d1f", mute: "#6e6e73", line: "rgba(60,60,67,.38)", fill: "rgba(250,250,252,.92)", bar: "rgba(118,118,128,.28)", green: "#00a855", onGreen: "#ffffff", orange: "#e8590c" },
    dark:  { ink: "#f5f5f7", mute: "#a1a1a6", line: "rgba(235,235,245,.32)", fill: "rgba(28,28,30,.88)", bar: "rgba(118,118,128,.42)", green: "#00d26a", onGreen: "#0b0b0c", orange: "#ff9f0a" },
  };
  const root = document.documentElement, systemDark = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => root.classList.contains("can-dark") && (root.classList.contains("theme-dark") || (!root.classList.contains("theme-light") && systemDark.matches));
  let theme = isDark() ? THEMES.dark : THEMES.light;
  const panels = [];
  const GREEN = 0x00d26a;
  const MAGENTA = new THREE.Color(0xe3187f), NEON_GREEN = new THREE.Color(GREEN);   // Cohesity magenta, Cohesity green

  // ---------- three.js ----------
  const canvas = stage.querySelector("canvas");
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); }
  catch (e) { stage.closest(".pj").remove(); return; }   // no WebGL: leave the page as it was
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(2, devicePixelRatio));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(34, 16 / 9, 10, 20000);

  // A flat card drawn on a canvas, transparent around its shape.
  function panel(w, h, draw) {
    const S = 2, c = document.createElement("canvas"); c.width = w * S; c.height = h * S;
    const tex = new THREE.CanvasTexture(c); tex.anisotropy = 8;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
    m.userData.state = {};
    m.userData.redraw = () => { const g = c.getContext("2d"); g.setTransform(S, 0, 0, S, 0, 0); g.clearRect(0, 0, w, h); draw(g, w, h, m.userData.state); tex.needsUpdate = true; };
    m.userData.redraw();
    m.renderOrder = 5;
    panels.push(m); scene.add(m);
    return m;
  }
  function setState(m, key, val) { if (m.userData.state[key] !== val) { m.userData.state[key] = val; m.userData.redraw(); } }
  function rr(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
  function cardBase(g, w, h, r, stroke, glow) {
    if (glow) { g.save(); g.shadowColor = glow; g.shadowBlur = 18; rr(g, 6, 6, w - 12, h - 12, r); g.strokeStyle = glow; g.lineWidth = 3; g.stroke(); g.restore(); }
    rr(g, 6, 6, w - 12, h - 12, r); g.fillStyle = theme.fill; g.fill(); g.lineWidth = 2.5; g.strokeStyle = stroke || theme.line; g.stroke();
  }
  function bars(g, x, y, widths, gap, hgt) { g.fillStyle = theme.bar; widths.forEach((bw, i) => { rr(g, x, y + i * gap, bw, hgt, hgt / 2); g.fill(); }); }
  function text(g, s, x, y, size, color, weight = 600, align = "left") { g.font = `${weight} ${size}px -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif`; g.fillStyle = color; g.textAlign = align; g.fillText(s, x, y); }
  function pill(g, x, y, w, h, s, on) { rr(g, x, y, w, h, h / 2); g.fillStyle = on ? theme.green : theme.fill; g.fill(); if (!on) { g.strokeStyle = theme.line; g.lineWidth = 2; g.stroke(); } text(g, s, x + w / 2, y + h / 2 + 6, 16, on ? theme.onGreen : theme.ink, 700, "center"); }

  // ---------- Neon: a bright core with soft halos around it (normal blending, so it reads on light and dark pages) ----------
  const HALO_O = [0.95, 0.22, 0.08], HALO_R = [1, 3.2, 7];
  const haloMats = () => HALO_O.map((o) => new THREE.MeshBasicMaterial({ color: GREEN, transparent: true, opacity: o, depthWrite: false }));
  function neonTube(curve, r, segs, radial = 6) {
    const g = new THREE.Group(), mats = haloMats();
    HALO_R.forEach((k, i) => { const m = new THREE.Mesh(new THREE.TubeGeometry(curve, segs, r * k, radial, false), mats[i]); m.renderOrder = 2 + i; g.add(m); });
    g.userData.mats = mats; return g;
  }
  function neonBall(r) {
    const g = new THREE.Group(), mats = haloMats();
    [1, 2.2, 4].forEach((k, i) => g.add(new THREE.Mesh(new THREE.SphereGeometry(r * k, 20, 14), mats[i])));
    g.userData.mats = mats; scene.add(g); return g;
  }
  function setNeon(g, op) { g.userData.mats.forEach((m, i) => (m.opacity = HALO_O[i] * op)); g.visible = op > 0.01; }

  // Stations: where each step happens, stepping back and forth in depth so the camera travels through space.
  const S = [V(0, 0, 0), V(1700, 60, -500), V(3400, 0, 0), V(5100, 80, -500), V(6800, 0, -200), V(6800, 0, -200)];   // the last step stays at the globe

  // ---------- The night Earth (NASA Black Marble) ----------
  const earthTex = new THREE.TextureLoader().load(stage.dataset.earth, () => { if (!playing) render(clock); });
  // Position on a three.js sphere for a latitude and longitude (matches the sphere's map).
  function geo(lat, lon) {
    const th = (90 - lat) * Math.PI / 180, ph = (lon + 180) * Math.PI / 180;
    return V(-Math.cos(ph) * Math.sin(th), Math.cos(th), Math.sin(ph) * Math.sin(th));
  }
  const CITY = { EN: [51.5, -0.12], ES: [40.42, -3.70], FR: [48.86, 2.35], DE: [52.52, 13.40], PT: [38.72, -9.14], KO: [37.57, 126.98], JA: [35.68, 139.69], "繁中": [25.03, 121.56], "简中": [39.90, 116.40] };
  // The cities around the world the shares reach.
  const MORE = [[40.71, -74.0], [43.65, -79.38], [-23.55, -46.63], [19.43, -99.13], [37.77, -122.42], [41.9, 12.5], [52.37, 4.9], [59.33, 18.07], [52.23, 21.0], [41.01, 28.98],
                [25.2, 55.27], [19.08, 72.88], [28.61, 77.21], [31.23, 121.47], [22.32, 114.17], [1.35, 103.82], [34.69, 135.5], [35.18, 129.08], [14.6, 120.98], [13.76, 100.5], [-33.87, 151.21], [-33.92, 18.42], [6.52, 3.38], [55.75, 37.62]];
  const EARTH_R = 330;
  const earth = new THREE.Group();
  const ball = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.MeshBasicMaterial({ map: earthTex, transparent: true, opacity: 0 }));
  earth.add(ball);
  // a neon latitude/longitude cage around it
  const cageMat = new THREE.LineBasicMaterial({ color: GREEN, transparent: true, opacity: 0 });
  const ringLine = (f) => { const pts = []; for (let a = 0; a <= 96; a++) pts.push(f(a / 96).multiplyScalar(1.012)); earth.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), cageMat)); };
  for (let lat = -60; lat <= 60; lat += 30) ringLine((q) => geo(lat, q * 360 - 180));
  for (let lon = -180; lon < 180; lon += 30) ringLine((q) => geo(q * 180 - 90, lon));
  // rim glow
  const rim = new THREE.Mesh(new THREE.SphereGeometry(1.06, 48, 32), new THREE.MeshBasicMaterial({ color: GREEN, transparent: true, opacity: 0, side: THREE.BackSide, depthWrite: false }));
  earth.add(rim);
  earth.position.copy(S[4]); earth.scale.setScalar(EARTH_R);
  scene.add(earth);
  function setEarth(op) {
    earth.visible = op > 0.01;
    ball.material.opacity = op; cageMat.opacity = 0.35 * op; rim.material.opacity = 0.12 * op;
  }
  // Face a longitude/latitude toward the camera side (+z), tilted a little.
  function aimEarth(lat, lon, drift) {
    const p = geo(0, lon);
    earth.rotation.set(lat * Math.PI / 180 * 0.6, Math.atan2(-p.x, p.z) + drift, 0);
  }
  // Step 5: arcs spread from each language's nearest city to cities around the world; pins light up where they land.
  function arcCurve(a, b, lift) {
    const pts = []; for (let i = 0; i <= 40; i++) { const s = i / 40; pts.push(a.clone().lerp(b, s).normalize().multiplyScalar(1.01 + lift * Math.sin(Math.PI * s))); }
    return new THREE.CatmullRomCurve3(pts);
  }
  const ARC_SEGS = 60;
  const spray = MORE.map(([la, lo], i) => {
    const b = geo(la, lo);
    const src = Object.keys(CITY).reduce((best, k) => (geo(...CITY[k]).angleTo(b) < geo(...CITY[best]).angleTo(b) ? k : best), "EN");
    const a = geo(...CITY[src]);
    const curve = arcCurve(a, b, 0.08 + 0.35 * a.angleTo(b) / Math.PI);
    const mats = haloMats();
    const tubes = [0.004, 0.012].map((r, j) => { const m = new THREE.Mesh(new THREE.TubeGeometry(curve, ARC_SEGS, r, 6, false), mats[j]); earth.add(m); return m; });
    const pin = new THREE.Mesh(new THREE.SphereGeometry(0.014, 12, 8), mats[0]); pin.position.copy(b.clone().multiplyScalar(1.01)); earth.add(pin);
    return { tubes, mats, pin, delay: 0.12 + (i % 12) * 0.05 + Math.floor(i / 12) * 0.03 };
  });
  const regionPins = Object.keys(CITY).map((k) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.02, 14, 10), new THREE.MeshBasicMaterial({ color: GREEN, transparent: true, opacity: 0 })); m.position.copy(geo(...CITY[k]).multiplyScalar(1.012)); earth.add(m); return m; });

  // ---------- 1 · The post ----------
  let loopN = 0, langSwapped = false;
  const SOURCE_LANGS = ["EN", "JA", "ES", "DE", "KO", "FR", "PT", "繁中", "简中"];   // each loop it starts in another language
  // a soft pool of green light beneath the post
  const postGlow = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    const r = g.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, "rgba(0,210,106,.55)"); r.addColorStop(1, "rgba(0,210,106,0)");
    g.fillStyle = r; g.fillRect(0, 0, 256, 256);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(520, 170), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, opacity: 0, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; scene.add(m); return m;
  })();
  const post = panel(420, 280, (g, w, h) => {
    cardBase(g, w, h, 22, null, theme.green);
    bars(g, 34, 74, [300, 240, 270, 170], 28, 12);
    pill(g, 34, 20, 64, 30, SOURCE_LANGS[loopN % SOURCE_LANGS.length], false);
    pill(g, 34, h - 66, 116, 40, "Share", true);
  });

  // ---------- 2 · The agent: a glowing cube; the brand guidelines, goals and product orbit it, then go in ----------
  const agentAt = S[1].clone().add(V(-260, 0, 0));
  const agentGroup = new THREE.Group(); agentGroup.position.copy(agentAt); scene.add(agentGroup);
  const glass = new THREE.Mesh(new THREE.BoxGeometry(220, 220, 220), new THREE.MeshBasicMaterial({ color: 0x2a0b1c, transparent: true, opacity: 0, depthWrite: false }));
  agentGroup.add(glass);
  const agentEdges = [];
  {
    const h = 110, corners = [];
    for (const x of [-h, h]) for (const y of [-h, h]) for (const z of [-h, h]) corners.push(V(x, y, z));
    for (let i = 0; i < 8; i++) for (let j = i + 1; j < 8; j++) {
      if (Math.abs(corners[i].distanceTo(corners[j]) - 2 * h) < 1) {
        const e = neonTube(new THREE.LineCurve3(corners[i], corners[j]), 3.2, 2);
        agentGroup.add(e); agentEdges.push(e);
      }
    }
  }
  const GLASS_OFF = new THREE.Color(0x2a0b1c), GLASS_ON = new THREE.Color(0x0b2a1c);
  const pages = [["Brand", "Guidelines"], ["Company", "Goals"], ["The", "Product"]].map(([l1, l2]) => panel(120, 140, (g, w, h) => {
    rr(g, 4, 4, w - 8, h - 8, 10); g.fillStyle = theme.fill; g.fill(); g.strokeStyle = theme.green; g.lineWidth = 2; g.stroke();
    text(g, l1, 14, 32, 15, theme.green, 700); text(g, l2, 14, 52, 15, theme.green, 700);
    bars(g, 14, 70, [86, 70, 80, 56], 14, 6);
  }));

  // One copy of the post per language.
  const LANGS = ["EN", "ES", "FR", "DE", "PT", "KO", "JA", "繁中", "简中"];
  const FIX = LANGS.indexOf("KO");   // the one that comes back for a rewrite
  const copies = LANGS.map((code) => panel(190, 124, (g, w, h, st) => {
    const c = st.fix ? theme.orange : st.hot ? theme.green : null;
    cardBase(g, w, h, 14, c, c);
    text(g, code, 22, 44, 26, c || theme.ink, 700);
    if (st.fix === "rewrite") text(g, "Rewriting…", 22, 84, 17, theme.orange, 700);
    else bars(g, 22, 64, [140, 110, 124], 18, 8);
    if (st.fix === "bad") text(g, "fix", w - 22, 44, 16, theme.orange, 700, "right");
  }));

  // ---------- 3 · Review: the Champions Portal, and a manager over each language ----------
  const RING_AT = S[2].clone().add(V(-120, 0, 60));
  const portalLabel = panel(300, 64, (g, w) => { text(g, "Champions Portal", w / 2, 40, 24, theme.green, 700, "center"); });
  const managers = LANGS.map(() => panel(70, 78, (g, w) => {
    g.strokeStyle = theme.green; g.lineWidth = 3;
    g.beginPath(); g.arc(w / 2, 22, 14, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.moveTo(w / 2 - 26, 70); g.bezierCurveTo(w / 2 - 26, 40, w / 2 + 26, 40, w / 2 + 26, 70); g.stroke();
  }));
  const ringNeon = (() => {
    const g = new THREE.Group(), mats = haloMats();
    HALO_R.forEach((k, i) => g.add(new THREE.Mesh(new THREE.TorusGeometry(150, 4 * k, 10, 96), mats[i])));
    g.userData.mats = mats; scene.add(g); return g;
  })();
  ringNeon.position.copy(RING_AT); ringNeon.rotation.set(0, Math.PI / 2 - 0.35, 0);

  // ---------- 4 · Champions Hub: one tile per language's piece of content ----------
  const HUB_TILES = [["EN", "Video"], ["KO", "Blogs"], ["FR", "PR"], ["JA", "Customer Stories"], ["ES", "Video"],
                     ["DE", "Blogs"], ["PT", "PR"], ["繁中", "Customer Stories"], ["简中", "Video"], ["", "+"]];
  const HUB_W = 1120, HUB_H = 760, TILE_W = (HUB_W - 96 - 4 * 20) / 5, TILE_H = 250;
  const tileXY = (n) => [48 + (n % 5) * (TILE_W + 20), 140 + Math.floor(n / 5) * (TILE_H + 24)];
  const hub = panel(HUB_W, HUB_H, (g, w, h, st) => {
    const filled = st.filled || 0;
    cardBase(g, w, h, 28);
    text(g, "Champions Hub", 48, 66, 28, theme.ink, 700);
    text(g, "Ready to share, in your language", 48, 98, 17, theme.mute, 500);
    HUB_TILES.forEach(([lang, kind], n) => {
      const [x, y] = tileXY(n), on = st.hot === n;
      if (n >= filled) { rr(g, x, y, TILE_W, TILE_H, 16); g.strokeStyle = theme.line; g.lineWidth = 2; g.setLineDash([8, 8]); g.stroke(); g.setLineDash([]); return; }
      if (on) { g.save(); g.shadowColor = theme.green; g.shadowBlur = 16; rr(g, x, y, TILE_W, TILE_H, 16); g.strokeStyle = theme.green; g.lineWidth = 3; g.stroke(); g.restore(); }
      rr(g, x, y, TILE_W, TILE_H, 16); g.strokeStyle = on ? theme.green : theme.line; g.lineWidth = 2.5; g.stroke();
      g.strokeStyle = theme.green; g.fillStyle = theme.green; g.lineWidth = 3;
      const cx = x + TILE_W / 2, cy = y + 128;
      if (kind === "Video") { g.beginPath(); g.moveTo(cx - 16, cy - 22); g.lineTo(cx + 24, cy); g.lineTo(cx - 16, cy + 22); g.closePath(); g.fill(); }
      else if (kind === "Blogs") { for (let r = 0; r < 4; r++) { rr(g, cx - 40, cy - 30 + r * 18, r === 3 ? 50 : 80, 8, 4); g.fill(); } }
      else if (kind === "PR") { rr(g, cx - 34, cy - 30, 68, 60, 6); g.stroke(); text(g, "PR", cx, cy + 9, 24, theme.green, 800, "center"); }
      else if (kind === "Customer Stories") { g.beginPath(); g.arc(cx, cy - 12, 15, 0, Math.PI * 2); g.stroke(); g.beginPath(); g.moveTo(cx - 28, cy + 34); g.bezierCurveTo(cx - 28, cy + 6, cx + 28, cy + 6, cx + 28, cy + 34); g.stroke(); }
      else { g.lineWidth = 6; g.beginPath(); g.moveTo(cx - 30, cy + 2); g.lineTo(cx + 30, cy + 2); g.moveTo(cx, cy - 28); g.lineTo(cx, cy + 32); g.stroke(); }
      if (lang) text(g, lang, x + 22, y + 46, 26, on ? theme.green : theme.ink, 700);
      if (kind !== "+") text(g, kind, x + 22, y + TILE_H - 26, 18, theme.mute, 600);
    });
  });

  // ---------- 5 · Around the globe: the language cards ring it, tethered to their cities ----------
  const tethers = LANGS.map(() => { const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints([V(0, 0, 0), V(0, 0, 0)]), new THREE.LineBasicMaterial({ color: GREEN, transparent: true, opacity: 0 })); scene.add(l); return l; });
  // A tilted ring around the globe: cards in front are seen whole, cards behind pass behind it.
  function ringPos(i, t) {
    const a = i / 9 * Math.PI * 2 + t * 0.22, R = EARTH_R * 1.6;
    return S[4].clone().add(V(Math.cos(a) * R, 0, Math.sin(a) * R).applyAxisAngle(V(1, 0, 0), -0.38).applyAxisAngle(V(0, 0, 1), 0.12));
  }
  const onEarth = (code, lift) => earth.localToWorld(geo(...CITY[code]).multiplyScalar(lift));

  // ---------- The live thread: the post's journey, drawn as it travels ----------
  const THREAD_PTS = [S[0].clone().add(V(0, 0, -14)), agentAt.clone().add(V(0, -40, 0)), RING_AT.clone().add(V(-40, -20, 0)), S[3].clone().add(V(0, 390, 20)), S[4].clone().add(V(0, 380, 0))];
  // Station j sits exactly at t = j / 4, so the drawn length can follow the steps.
  const threadCurve = new THREE.CatmullRomCurve3(THREAD_PTS, false, "catmullrom", 0.5);
  // The tube is laid out by curve position (not by length), so its end and the head line up.
  class Uniform extends THREE.Curve { constructor(c) { super(); this.c = c; } getPoint(t, out = new THREE.Vector3()) { return out.copy(this.c.getPoint(t)); } }
  const SEGS = 600;
  const uniThread = new Uniform(threadCurve), THREAD_LEN = uniThread.getLengths(SEGS);
  const thread = neonTube(uniThread, 2.6, SEGS); scene.add(thread);
  const head = neonBall(7);
  const pulse = neonBall(6);
  function drawThread(frac) {
    const u = THREAD_LEN[Math.round(clamp(frac) * SEGS)] / THREAD_LEN[SEGS];
    const n = Math.floor(SEGS * u) * 6 * 6;
    thread.children.forEach((m) => m.geometry.setDrawRange(0, n));
  }

  // ---------- Captions ----------
  const cap = stage.querySelector(".pj-caption"), line = cap.querySelector(".pj-line"), kick = cap.querySelector(".pj-kicker");
  let shown = -1;

  // ---------- Camera ----------
  const DIST = [800, 1450, 1650, 1950, 1900, 1900];     // step 1 sits close; the rest far enough back that the captions never cover anything
  const AIM_DROP = [-55, -70, -20, -80, -30, -30];      // keeps each scene clear of the subtitles
  const SPIN = 0.32;                                    // radians each station turns through while it plays
  const orbit = (i, ang) => S[i].clone().add(V(Math.sin(ang) * DIST[i], 170, Math.cos(ang) * DIST[i]));
  const aim = (i) => (i === 1 ? agentAt.clone() : S[i].clone()).add(V(0, AIM_DROP[i], 0));

  function place(m, p, op, s = 1) { m.position.copy(p); m.material.opacity = op; m.visible = op > 0.01; m.scale.setScalar(s); m.quaternion.copy(cam.quaternion); }

  // ---------- One moment of the journey ----------
  function render(t) {
    const w = where(t), b = w.b, k = w.k, e = ease(k);

    // Captions: the next step's words arrive halfway through a transition (except into the closing line).
    const step = w.tr && k > 0.5 && b !== 4 ? b + 1 : b;
    if (shown !== step) {
      shown = step;
      line.replaceChildren(...BEATS[step].parts.map((tx) => Object.assign(document.createElement("span"), { className: "pj-part", textContent: tx + " " })));
      line.classList.remove("pj-in"); void line.offsetWidth; line.classList.add("pj-in");
    }
    // the first beat right away, the rest one after another across the first half of the step
    const parts = line.children, np = parts.length;
    const into = step === b && !w.tr ? k : (step === b + 1 ? -1 : 1);   // arriving in a transition: only the first beat yet
    for (let j = 0; j < np; j++) {
      const cue = j === 0 ? -1 : (j / np) * 0.55;
      const o = into < 0 ? (j === 0 ? 1 : 0) : clamp((into - cue) / 0.08);
      parts[j].style.opacity = o; parts[j].style.filter = `blur(${(1 - o) * 4}px)`;
    }
    // after the fade to black the closing line sits alone in the middle, then gives way to step 1
    cap.classList.toggle("is-center", b === 5);
    cap.style.opacity = b === 4 ? (w.tr ? 0 : 1 - span(k, 0.84, 1)) : b === 5 && !w.tail ? span(k, 0.03, 0.14) : (w.tail ? 1 - span(w.tk, 0.25, 0.55) : 1);
    const ko = b === 5 && !w.tail ? span(k, 0.38, 0.5) : (w.tail ? 1 : 0);
    kick.style.opacity = ko; kick.style.transform = `translateY(${(1 - ko) * 8}px)`;

    // Camera: straight on to each station, turning slowly around it while the step plays; between stations
    // it swings up and back on its way. From the globe on it holds still, and cuts home while the screen is dark.
    let at, from;
    if (w.tr && b !== 4) {
      at = mix(aim(b), aim(b + 1), e); from = mix(orbit(b, SPIN / 2), orbit(b + 1, -SPIN / 2), e);
      from.y += Math.sin(k * Math.PI) * 300; from.z += Math.sin(k * Math.PI) * 350;
    } else if ((b === 4 && w.tr) || b === 5) {
      at = aim(4); from = orbit(4, SPIN / 2);
      if (w.tail && w.tk >= 0.55) { at = aim(0); from = orbit(0, -SPIN / 2); }
    } else {
      at = aim(b); from = orbit(b, (k - 0.5) * SPIN);
    }
    cam.position.copy(from); cam.lookAt(at);

    const near = (i) => (i === b ? (w.tr ? 1 - span(k, 0.3, 0.9) : 1) : (w.tr && i === b + 1 ? span(k, 0.2, 0.8) : 0));

    // The thread: reaches each station as its step begins, then the head waits there. It fades in with the post,
    // and away once the arcs start spreading around the globe.
    const prog = Math.min(4, w.tail ? 4 : (w.tr ? b + e : b)) / 4;
    drawThread(prog);
    head.position.copy(threadCurve.getPoint(prog));
    const threadOp = w.tail || b === 5 || (b === 4 && w.tr) ? 0 : (b === 4 ? 1 - span(k, 0.36, 0.52) : (b === 0 && !w.tr ? span(k, 0.05, 0.25) : 1));
    setNeon(thread, threadOp); setNeon(head, threadOp);
    head.scale.setScalar(b === 1 && w.tr ? 2.6 + 0.6 * Math.sin(t * 20) : (w.tr ? 1.3 : 1 + 0.25 * Math.sin(t * 6)));   // the surge pulses along the line
    // the portal flares as the surge arrives, and again as each language steps out
    let surgeHit = b === 1 && w.tr ? span(k, 0.85, 1) : 0;
    if (b === 2 && !w.tr) for (let i = 0; i < 9; i++) surgeHit = Math.max(surgeHit, Math.exp(-Math.pow((k - (0.06 + i * 0.04)) / 0.018, 2)));

    // 1 · the post floats and tilts on its own; in T1 it flies into the agent. It ends the loop fading back in.
    let pp = S[0].clone(), po = near(0), ps = 1;
    if (b === 0 && w.tr) { pp = mix(S[0], agentAt, e); pp.y += Math.sin(k * Math.PI) * 120; po = 1 - span(k, 0.88, 1); ps = 1 - 0.72 * e; }
    if (b >= 1) po = 0;
    if (w.tail) { pp = S[0].clone(); po = span(w.tk, 0.62, 1); }
    // the next loop's language goes on while the screen is still dark, before the post fades back in
    if (w.tail && w.tk > 0.55 && !langSwapped) { loopN++; langSwapped = true; post.userData.redraw(); }
    if (!w.tail) langSwapped = false;
    const tw = w.tail ? t - TOTAL : t;                                   // runs straight on through the loop point
    const amp = w.tail ? 1 : (b === 0 ? (w.tr ? 1 - e : 1) : 0);         // the float eases out as it flies to the agent
    const bob = Math.sin(tw * 1.8) * 10 * amp;
    place(post, pp.clone().add(V(0, bob, 0)), po, ps);
    if (amp > 0) { post.rotateY(Math.sin(tw * 0.9) * 0.32 * amp); post.rotateX((-0.12 + Math.sin(tw * 1.3) * 0.05) * amp); }
    postGlow.position.copy(pp).add(V(0, -205, 0)); postGlow.material.opacity = (0.9 - 0.25 * (bob / 10)) * amp * po; postGlow.scale.setScalar(ps * (1 - 0.06 * bob / 10));

    // 2 · the agent: magenta until the pages go in, then green; it gulps the post and each page.
    const ag = near(1);
    agentGroup.rotation.set(0.35, t * 0.5, 0.1);
    const gulp = (b === 0 && w.tr ? span(k, 0.85, 1) : 0) + (b === 1 && !w.tr ? Math.exp(-Math.pow(k / 0.06, 2)) + [0.5, 0.6, 0.7].reduce((m, c) => Math.max(m, Math.exp(-Math.pow((k - c) / 0.04, 2))), 0) : 0);
    agentGroup.scale.setScalar(1 + 0.18 * gulp);
    const working = b === 0 ? 0 : (b === 1 && !w.tr ? span(k, 0.34, 0.7) : 1);
    glass.material.opacity = 0.18 * ag; glass.material.color.copy(GLASS_OFF).lerp(GLASS_ON, working);
    agentEdges.forEach((eg) => { setNeon(eg, ag * (1 + gulp)); eg.userData.mats.forEach((m) => m.color.copy(MAGENTA).lerp(NEON_GREEN, working)); });
    pages.forEach((pg, i) => {
      // orbiting outside the cube, then pushed in one after another; once in, they stay in
      const a = t * 0.8 + i * Math.PI * 2 / 3;
      const outside = agentAt.clone().add(V(Math.cos(a) * 250, 30 * Math.sin(a + i), Math.sin(a) * 250));
      const push = b === 1 && !w.tr ? ease(span(k, 0.34 + i * 0.1, 0.5 + i * 0.1)) : (b >= 1 ? 1 : 0);
      place(pg, mix(outside, agentAt, push), ag * (1 - span(push, 0.75, 1)), 1 - 0.6 * push);
    });

    // The hub and the globe, placed first so the cards can find their tiles and cities.
    hub.position.copy(S[3]); hub.quaternion.copy(cam.quaternion); hub.scale.setScalar(b === 3 && w.tr ? 1 - 0.5 * e : 1); hub.updateMatrixWorld();
    const hubOp = b === 3 ? (w.tr ? 1 - span(k, 0, 0.6) : 1) : (b === 2 && w.tr ? span(k, 0.3, 1) : 0);
    hub.material.opacity = hubOp; hub.visible = hubOp > 0.01;
    const soakEnd = (n) => 0.13 + n * 0.06;   // tiles fill only as their card soaks in
    const filledN = b === 3 && !w.tr ? HUB_TILES.filter((_, n) => k > soakEnd(n)).length : (b > 3 || (b === 3 && w.tr) ? 10 : 0);
    setState(hub, "filled", filledN);
    setState(hub, "hot", b === 3 && !w.tr && filledN > 0 && k < soakEnd(filledN - 1) + 0.12 ? filledN - 1 : -1);
    const e5 = b === 4 ? (w.tr ? 0 : 1 - span(k, 0.84, 1)) : (b === 3 && w.tr ? span(k, 0.2, 1) : 0);   // the globe goes with the cards
    aimEarth(28, 45, (t - starts[4]) * 0.05); earth.updateMatrixWorld(); setEarth(e5);

    // The copies: spat out of the portal in 3, into their tiles in 4, ringing the globe in 5.
    const gridAt = (i) => RING_AT.clone().add(V(215 + (i % 3) * 215, 215 - Math.floor(i / 3) * 205, 30));
    const passK = (i) => 0.06 + i * 0.04;
    const tileOf = (i) => HUB_TILES.findIndex(([l]) => l === LANGS[i]);
    const tabAt = (i) => { const [x, y] = tileXY(tileOf(i)); return hub.localToWorld(V(x + TILE_W / 2 - HUB_W / 2, HUB_H / 2 - y - TILE_H / 2, 8)); };
    copies.forEach((m, i) => {
      let p = agentAt.clone(), op = 0, s = 0.6, hot = false, fix = null, spin = 0;
      if (b === 2 && !w.tr) {
        // out through the ring one by one; KO comes out needing a fix, is rewritten, then turns green
        const f = span(k, passK(i) - 0.06, passK(i) + 0.06);
        p = mix(RING_AT, gridAt(i), ease(f)); op = f > 0 ? 1 : 0; s = 0.25 + 0.55 * ease(f);
        if (f >= 1 && i !== FIX) hot = k < passK(i) + 0.2;
        if (i === FIX && f >= 1) {
          if (k < 0.42) { fix = "bad"; p.y += Math.sin(t * 30) * 4; }
          else if (k < 0.54) fix = "rewrite";   // "Rewriting…" holds still long enough to read
          else if (k < 0.72) { fix = "rewrite"; spin = ease(span(k, 0.54, 0.72)) * Math.PI * 4; s = 0.8 + 0.12 * Math.sin(span(k, 0.54, 0.72) * Math.PI); }
          else hot = true;
        }
      } else if (b === 2 && w.tr) {
        p = mix(gridAt(i), tabAt(i), clamp(e * 1.1 - i * 0.015)); op = 1; s = 0.8 - 0.2 * e;
      } else if (b === 3 && !w.tr) {
        // each copy settles into its tile and becomes it
        const o = tileOf(i), soak = span(k, 0.05 + o * 0.06, 0.13 + o * 0.06);
        p = tabAt(i); op = 1 - soak; s = 0.6 * (1 - 0.3 * soak);
      } else if (b === 3 && w.tr) {
        p = mix(tabAt(i), ringPos(i, t), clamp(e * 1.1 - i * 0.02)); op = 1; s = 0.6 - 0.12 * e;
      } else if (b === 4 && !w.tr) {
        p = ringPos(i, t); op = 1 - span(k, 0.84, 1); s = 0.48;
      }
      const tethered = b === 4 && !w.tr;
      if (tethered) tethers[i].geometry.setFromPoints([onEarth(LANGS[i], 1.01), p]);
      tethers[i].material.opacity = tethered ? op * 0.8 : 0;
      setState(m, "hot", hot); setState(m, "fix", fix);
      place(m, p, op, s);
      if (spin) m.rotateY(spin);
      const mo = b === 2 ? (w.tr ? 1 - span(k, 0, 0.4) : span(k, passK(i) + 0.03, passK(i) + 0.1)) : 0;
      place(managers[i], p.clone().add(V(0, 108 * s, 0)), mo * op, s * 0.9);
    });

    // 3 · the portal, and a fix travelling back along the thread to the agent.
    const r3 = Math.max(near(2), b === 1 && w.tr ? span(k, 0.3, 0.9) : 0);
    setNeon(ringNeon, r3 * (1 + 0.8 * surgeHit)); ringNeon.scale.setScalar(1 + 0.12 * surgeHit); ringNeon.rotation.z = t * 0.6;
    place(portalLabel, RING_AT.clone().add(V(0, 210, 0)), r3);
    const back = b === 2 && !w.tr ? span(k, 0.75, 0.94) : 0;
    pulse.visible = back > 0 && back < 1;
    pulse.position.copy(threadCurve.getPoint((2 - ease(back)) / 4));

    // 5 · each language's city lights up, then the arcs spread to cities around the world.
    regionPins.forEach((m, i) => (m.material.opacity = e5 * (b === 4 && !w.tr ? span(k, 0.12 + i * 0.05, 0.18 + i * 0.05) : (b > 4 || (b === 4 && w.tr) ? 1 : 0))));
    spray.forEach((sp) => {
      const g = b === 4 && !w.tr ? span(k, 0.3 + sp.delay * 0.55, 0.42 + sp.delay * 0.55) : ((b === 4 && w.tr) || b === 5 ? 1 : 0);
      sp.tubes.forEach((m) => m.geometry.setDrawRange(0, Math.floor(ARC_SEGS * g) * 6 * 6));
      sp.mats[0].opacity = 0.95 * e5 * (g > 0 ? 1 : 0); sp.mats[1].opacity = 0.25 * e5 * (g > 0 ? 1 : 0);
      sp.pin.visible = g >= 1;
    });

    renderer.render(scene, cam);
    creditAtEnd(w);
  }

  // ---------- Sizing, theme, playback ----------
  function size() { const r = canvas.getBoundingClientRect(); if (!r.width) return; renderer.setSize(r.width, r.height, false); cam.aspect = r.width / r.height; cam.updateProjectionMatrix(); }
  new ResizeObserver(() => { size(); if (!playing) render(clock); }).observe(canvas);
  size();
  function applyTheme() {
    const next = isDark() ? THEMES.dark : THEMES.light;
    if (next === theme) return;
    theme = next; panels.forEach((p) => p.userData.redraw());
    if (!playing) render(clock);
  }
  new MutationObserver(applyTheme).observe(root, { attributes: true, attributeFilter: ["class"] });
  systemDark.addEventListener?.("change", applyTheme);

  // Plays only while on screen and not paused. With Reduce Motion on it waits on the Champions Hub, full, until Play.
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const toggle = stage.querySelector(".pj-toggle"), restart = stage.querySelector(".pj-restart");
  let userPaused = reduce, onScreen = false, playing = false, raf = 0, last = 0;
  let clock = reduce ? starts[3] + BEATS[3].hold * 0.9 : 0;
  function frame(now) {
    clock = (clock + Math.min(0.25, (now - last) / 1000)) % TOTAL;   // a long gap (a hidden tab) never skips ahead
    last = now; render(clock); raf = requestAnimationFrame(frame);
  }
  function update() {
    const go = onScreen && !userPaused && !document.hidden;
    toggle.classList.toggle("is-paused", userPaused);
    toggle.setAttribute("aria-label", userPaused ? "Play animation" : "Pause animation");
    if (go === playing) return;
    playing = go;
    if (go) { last = performance.now(); raf = requestAnimationFrame(frame); } else cancelAnimationFrame(raf);
  }
  toggle.addEventListener("click", () => { userPaused = !userPaused; update(); });
  // Start over goes back to the first step and plays from there
  restart.addEventListener("click", () => { clock = 0; userPaused = false; render(clock); update(); });
  document.addEventListener("visibilitychange", update);

  // The controls wait behind a tab on the picture's right edge, like a video tucked off the side of an iPhone
  // screen. The tab slides them out; they tuck back to the edge on their own a few seconds after the last use
  // (not while the pointer or keyboard focus is on them), on a click or tap anywhere else, or on Escape.
  // While tucked away they're out of the tab order.
  const controls = stage.querySelector(".pj-controls"), tab = stage.querySelector(".pj-tab"), dock = stage.querySelector(".pj-dock");
  let tuckTimer = 0, overControls = false;
  function showControls(on, stay) {
    clearTimeout(tuckTimer);
    if (!on && controls.contains(document.activeElement)) tab.focus({ preventScroll: true });
    stage.classList.toggle("show-controls", on);
    tab.setAttribute("aria-expanded", String(on));
    controls.inert = !on;
    if (on && !stay) tuckLater();
  }
  function tuckLater(ms = 3500) {
    clearTimeout(tuckTimer);
    if (!overControls && !controls.querySelector(":focus-visible")) tuckTimer = setTimeout(() => showControls(false), ms);
  }
  tab.addEventListener("click", () => showControls(true));
  controls.addEventListener("pointerenter", () => { overControls = true; clearTimeout(tuckTimer); });
  controls.addEventListener("pointerleave", () => { overControls = false; tuckLater(); });
  controls.addEventListener("click", () => tuckLater());
  controls.addEventListener("focusin", () => setTimeout(() => { if (controls.querySelector(":focus-visible")) clearTimeout(tuckTimer); }));
  controls.addEventListener("focusout", () => setTimeout(() => tuckLater()));
  document.addEventListener("pointerdown", (e) => { if (stage.classList.contains("show-controls") && !dock.contains(e.target)) showControls(false); });
  stage.addEventListener("keydown", (e) => { if (e.key === "Escape" && stage.classList.contains("show-controls")) showControls(false); });
  showControls(false);
  // out while the reader scrolls toward the scene, tucked a second after it locks in (main.js, shared by every 3D scene)
  window.sceneControlsPeek?.(stage.closest(".pj-pin") || stage.closest(".pj"), stage.closest(".pj"), (on) => showControls(on, true), () => tuckLater(1000));

  // "How I Made This": opens from its button, near the end of the loop (from the closing line through the fade)
  // and when the reader scrolls to the bottom of the scene. Once open it stays open, through the loop starting
  // over, until it's closed; after the reader closes it, it no longer opens by itself.
  const creditBtn = stage.querySelector(".pj-credit-btn"), creditClose = stage.querySelector(".pj-credits-close"),
    credits = stage.querySelector(".pj-credits");
  let creditOpen = false, creditDismissed = false;
  function setCredit(on) {
    creditOpen = on;
    stage.classList.toggle("show-credits", on);
    creditBtn.setAttribute("aria-expanded", String(on));
  }
  const autoCredit = () => { if (creditBtn && !creditOpen && !creditDismissed) setCredit(true); };
  const dismissCredit = (refocus) => { setCredit(false); creditDismissed = true; if (refocus) creditBtn.focus(); };
  if (creditBtn) {
    creditBtn.addEventListener("click", () => (creditOpen ? dismissCredit(false) : setCredit(true)));
    creditClose.addEventListener("click", () => dismissCredit(true));
    stage.addEventListener("keydown", (e) => { if (e.key === "Escape" && creditOpen) dismissCredit(true); });
    // the subtitles rise above the note by its height
    new ResizeObserver(() => stage.style.setProperty("--pj-credits-h", `${credits.offsetHeight}px`)).observe(credits);
    const fig = stage.closest(".pj"), pin = stage.closest(".pj-pin");
    const atBottom = () => {
      const vh = innerHeight, f = fig.getBoundingClientRect(), r = (pin || fig).getBoundingClientRect();
      // held still on wide screens: the last stretch before the picture lets go; otherwise once its bottom is well up the window
      const bottom = r.height > f.height + 10 ? r.bottom - f.bottom < (r.height - f.height) * 0.15 && r.bottom > 0 : f.bottom < vh * 0.45 && f.bottom > f.height * 0.4;
      if (bottom) autoCredit();
    };
    addEventListener("scroll", atBottom, { passive: true });
    atBottom();
  }
  function creditAtEnd(w) { if (w.b === 5 && (w.tail || w.k > 0.35)) autoCredit(); }
  new IntersectionObserver((entries) => { onScreen = entries[entries.length - 1].isIntersecting; update(); }, { threshold: 0.25 }).observe(stage);
  render(clock);
  stage.classList.add("is-ready");
  update();
  }
})();
