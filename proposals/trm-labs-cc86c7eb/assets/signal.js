// The signal: a lamp flickers on at the bottom right, a cone of TRM particles climbs into a night sky, and the
// TRM symbol assembles out of dots inside the disc of light. Pure 2D canvas, drawn to look deep: three particle
// layers at different sizes and speeds, a perspective ellipse for the disc, drifting cloud. Reduced motion gets
// the finished frame.
(function () {
  const host = document.querySelector(".trm-signal");
  if (!host || window.__trmSignal3D) return;   // the WebGL version took the band
  const canvas = host.querySelector("canvas"), g = canvas.getContext("2d");
  const copy = host.querySelector(".trm-signal-copy");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const CYAN = [6, 228, 249], NAVY = "#00124D";
  let W = 0, H = 0, dpr = 1, t0 = performance.now();
  const rnd = (a, b) => a + Math.random() * (b - a);

  // the beam: from the lamp to the disc; width grows with distance, like a real throw
  const geo = () => {
    const lamp = { x: W * 0.86, y: H + 10 };
    const disc = { x: W * (W < 700 ? 0.5 : 0.36), y: H * 0.34, rx: Math.min(W, H * 1.6) * 0.17, ry: Math.min(W, H * 1.6) * 0.13 };
    return { lamp, disc };
  };

  // beam particles: t along the beam, u across it, z for depth
  const beam = Array.from({ length: 720 }, () => ({ t: Math.random(), u: rnd(-1, 1), z: rnd(0.35, 1), s: rnd(0.6, 1.4), ph: rnd(0, 6.28) }));
  // the symbol: TRM's node-and-spoke mark, as dot targets inside the disc; each dot starts scattered and converges
  const symbol = [];
  const SP = 8;
  symbol.push({ a: 0, r: 0 });
  for (let k = 0; k < SP; k++) {
    const a = (k / SP) * Math.PI * 2 + Math.PI / 8;
    for (let r = 0.28; r <= 0.82; r += 0.09) symbol.push({ a, r });
    symbol.push({ a, r: 0.95, end: true });
  }
  symbol.forEach((p) => { p.sx = rnd(-1.6, 1.6); p.sy = rnd(-1.6, 1.6); });
  // the disc's scalloped dotted rim, TRM's ring motif, turning slowly
  const rim = Array.from({ length: 160 }, (_, i) => (i / 160) * Math.PI * 2);
  // cloud blobs that drift across the sky
  const clouds = Array.from({ length: 7 }, (_, i) => ({ x: Math.random(), y: rnd(0.05, 0.75), r: rnd(0.25, 0.5), v: rnd(0.004, 0.012) * (i % 2 ? 1 : -1), a: rnd(0.05, 0.12) }));

  function resize() {
    const b = host.getBoundingClientRect();
    dpr = Math.min(2, devicePixelRatio || 1);
    W = Math.round(b.width); H = Math.round(b.height);
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // the lamp's intensity over time: dark, a nervous flicker, then it holds
  function intensity(s) {
    if (still) return 1;
    if (s < 0.5) return 0;
    if (s < 1.7) {
      const k = (s - 0.5) / 1.2;
      const burst = Math.sin(s * 47) * Math.sin(s * 23) > 0.15 ? 1 : 0.08;
      return Math.min(1, burst * (0.4 + 0.6 * k));
    }
    return 1;
  }
  const ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

  function draw(now) {
    const s = still ? 9 : (now - t0) / 1000;
    const I = intensity(s), on = ease((s - 1.7) / 0.9), gather = ease((s - 2.0) / 1.6);
    const { lamp, disc } = geo();
    g.clearRect(0, 0, W, H);
    // sky
    const sky = g.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#030B2E"); sky.addColorStop(1, NAVY);
    g.fillStyle = sky; g.fillRect(0, 0, W, H);
    for (const c of clouds) {
      c.x = (c.x + c.v * 0.016 + 1) % 1;
      const r = c.r * Math.max(W, H);
      const cg = g.createRadialGradient(c.x * W, c.y * H, 0, c.x * W, c.y * H, r);
      cg.addColorStop(0, `rgba(120,150,220,${c.a * (0.5 + 0.5 * I)})`); cg.addColorStop(1, "rgba(120,150,220,0)");
      g.fillStyle = cg; g.beginPath(); g.arc(c.x * W, c.y * H, r, 0, 7); g.fill();
    }
    // the cone of light, soft
    const ax = disc.x - lamp.x, ay = disc.y - lamp.y, L = Math.hypot(ax, ay), nx = -ay / L, ny = ax / L;
    const wEnd = disc.rx * 1.05, wStart = 10;
    if (I > 0) {
      const cone = g.createLinearGradient(lamp.x, lamp.y, disc.x, disc.y);
      cone.addColorStop(0, `rgba(${CYAN},${0.30 * I})`); cone.addColorStop(0.6, `rgba(${CYAN},${0.11 * I})`); cone.addColorStop(1, `rgba(${CYAN},${0.02 * I})`);
      g.fillStyle = cone;
      g.beginPath();
      g.moveTo(lamp.x + nx * wStart, lamp.y + ny * wStart);
      g.lineTo(disc.x + nx * wEnd, disc.y + ny * wEnd);
      g.lineTo(disc.x - nx * wEnd, disc.y - ny * wEnd);
      g.lineTo(lamp.x - nx * wStart, lamp.y - ny * wStart);
      g.closePath(); g.fill();
      // the disc on the cloud: a perspective ellipse, bright edge, TRM's dotted rim
      const dg = g.createRadialGradient(disc.x, disc.y, 0, disc.x, disc.y, disc.rx);
      dg.addColorStop(0, `rgba(${CYAN},${0.10 * I})`); dg.addColorStop(0.85, `rgba(${CYAN},${0.16 * I})`); dg.addColorStop(1, `rgba(${CYAN},0)`);
      g.save(); g.translate(disc.x, disc.y); g.scale(1, disc.ry / disc.rx);
      g.fillStyle = dg; g.beginPath(); g.arc(0, 0, disc.rx, 0, 7); g.fill();
      for (let i = 0; i < rim.length; i++) {
        const a = rim[i] + s * 0.05, rr = disc.rx * (0.97 + 0.03 * Math.sin(a * 12));
        const al = I * (0.35 + 0.65 * Math.abs(Math.sin(a * 6)));
        g.fillStyle = `rgba(${CYAN},${al})`; g.beginPath(); g.arc(Math.cos(a) * rr, Math.sin(a) * rr, 1.6, 0, 7); g.fill();
      }
      g.restore();
    }
    // particles riding the beam, three depths
    for (const p of beam) {
      if (!still) p.t = (p.t + 0.0018 * p.s * (0.5 + p.z)) % 1;
      const wd = wStart + (wEnd - wStart) * p.t;
      const x = lamp.x + ax * p.t + nx * p.u * wd + Math.sin(s * 1.3 + p.ph) * 2 * p.z;
      const y = lamp.y + ay * p.t + ny * p.u * wd;
      const al = I * p.z * (0.25 + 0.75 * (1 - Math.abs(p.u))) * (0.6 + 0.4 * Math.sin(s * 2 + p.ph));
      if (al <= 0.01) continue;
      g.fillStyle = `rgba(${CYAN},${al.toFixed(3)})`; g.beginPath(); g.arc(x, y, 0.8 + 2.2 * p.z, 0, 7); g.fill();
    }
    // the symbol gathering inside the disc
    if (on > 0) {
      g.save(); g.translate(disc.x, disc.y); g.scale(1, disc.ry / disc.rx);
      const R = disc.rx * 0.62;
      for (const p of symbol) {
        const tx = Math.cos(p.a) * p.r * R, ty = Math.sin(p.a) * p.r * R;
        const x = p.sx * R * (1 - gather) + tx * gather, y = p.sy * R * (1 - gather) + ty * gather;
        const big = p.end || p.r === 0;
        g.fillStyle = `rgba(247,245,244,${(0.35 + 0.65 * gather) * on})`;
        g.beginPath(); g.arc(x, y, (big ? 6 : 3) * (0.6 + 0.4 * gather), 0, 7); g.fill();
      }
      g.restore();
    }
    // the lamp: a hot core, and a brief lens flare while it flickers
    if (I > 0) {
      const lg = g.createRadialGradient(lamp.x, lamp.y, 0, lamp.x, lamp.y, 90);
      lg.addColorStop(0, `rgba(255,255,255,${0.9 * I})`); lg.addColorStop(0.15, `rgba(${CYAN},${0.6 * I})`); lg.addColorStop(1, `rgba(${CYAN},0)`);
      g.fillStyle = lg; g.beginPath(); g.arc(lamp.x, lamp.y, 90, 0, 7); g.fill();
    }
    if (copy) copy.style.opacity = still ? 1 : ease((s - 2.4) / 0.9);
    if (!still) requestAnimationFrame(draw);
  }
  resize();
  new ResizeObserver(resize).observe(host);
  // the lamp starts when the band is in view; a replay button runs it again
  const start = () => { t0 = performance.now(); requestAnimationFrame(draw); };
  if (still) draw(0); else start();
  host.querySelector(".trm-signal-replay")?.addEventListener("click", start);
})();
