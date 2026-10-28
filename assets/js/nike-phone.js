// The Nike request-to-live scene in 3D (three.js): the placement rides a real phone through the seven steps as
// the section scrolls. Christian's steps keep the phone in its burgundy with an accent edge light; the handoffs
// (QA, Legal) turn it gray and lower it, and their sign-offs arrive as Liquid Glass notifications on its screen.
// The reader can grab the phone and turn it at any step; it eases back when let go.
// It takes over from the flat phone only on the pinned desktop layout (main.js sets .is-live) with WebGL;
// phones, Reduce Motion, short windows and anything without WebGL keep the flat phone. three.js loads only when
// the section nears the screen.
const scene = document.querySelector('[data-scene="flow"][data-phone3d]');
const visual = scene && scene.querySelector(".sc-visual");
const flat = scene && scene.querySelector(".ph");
const webgl = (() => { try { return !!document.createElement("canvas").getContext("webgl2"); } catch (e) { return false; } })();
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

if (scene && visual && flat && webgl && !reduce) {
  // phone widths never pin, so they never download three.js; a window widened later still gets it
  const narrow = matchMedia("(max-width: 720px)");
  let started = false;
  const begin = () => {
    if (started || narrow.matches) return;
    started = true;
    const near = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      near.disconnect();
      import("three").then(start).catch(() => {});   // no three.js: the flat phone stays
    }, { rootMargin: "900px 0px" });
    near.observe(scene);
  };
  begin();
  narrow.addEventListener?.("change", begin);
}

function start(THREE) {
  // ---------- the placements: the screens each set shows (the switcher under the phone picks one) ----------
  const setsEl = scene.querySelector(".sc-sets");
  const sets = setsEl ? JSON.parse(setsEl.textContent)
    : [{ src: flat.querySelector(".ph-layer img")?.src, next: flat.querySelector(".ph-next")?.src }];
  const cuts = [...flat.querySelectorAll(".ph-layer")].map((l) => parseFloat(l.style.top) / 100);
  cuts.push(1);

  // ---------- renderer, camera, studio light ----------
  const canvas = document.createElement("canvas");
  canvas.className = "ph3d";
  canvas.setAttribute("aria-hidden", "true");
  visual.append(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const world = new THREE.Scene();
  world.environment = new THREE.PMREMGenerator(renderer).fromScene(studio(THREE), 0.04).texture;
  const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(2, 3, 4); world.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0); rim.position.set(-3, 1.2, -2); world.add(rim);
  const rim2 = new THREE.DirectionalLight(0xffffff, 0); rim2.position.set(3, -1, -2); world.add(rim2);

  // ---------- the phone (modeled on a current pro phone, burgundy, Christian's CS mark on the back) ----------
  const W = 0.76, H = 1.62, D = 0.088, R = 0.125;
  const BURGUNDY = new THREE.Color(0x4d1822), GRAPHITE = new THREE.Color(0x9a9aa0);   // the handoffs' gray, light enough to read as gray
  // the phone sits in a rig: the turntable tips the rig to a hero angle (leaning back and to one side) and the
  // phone turns about its own long axis inside it
  const rig = new THREE.Group(); world.add(rig);
  // the soft shadow it casts on the page while it's out over the words (a blurred dark shape behind it)
  const shadowCanvas = document.createElement("canvas"); shadowCanvas.width = shadowCanvas.height = 256;
  { const g = shadowCanvas.getContext("2d"), gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    gr.addColorStop(0, "rgba(0,0,0,.55)"); gr.addColorStop(0.55, "rgba(0,0,0,.22)"); gr.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 256, 256); }
  const cast = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 2.6), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(shadowCanvas), transparent: true, opacity: 0, depthWrite: false }));
  cast.position.set(0.16, -0.22, -0.9); cast.visible = false; world.add(cast);
  const phone = new THREE.Group(); rig.add(phone);
  const roundedRect = (w, h, r, rb = r) => {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + rb, y); s.lineTo(x + w - rb, y); s.quadraticCurveTo(x + w, y, x + w, y + rb);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + rb); s.quadraticCurveTo(x, y, x + rb, y);
    return s;
  };
  const shapeMesh = (w, h, r, mat, z, rb = r, uv0 = 0, uv1 = 1) => {
    const geo = new THREE.ShapeGeometry(roundedRect(w, h, r, rb), 32);
    const pos = geo.attributes.position, uv = [];
    for (let i = 0; i < pos.count; i++) uv.push(pos.getX(i) / w + 0.5, uv0 + (pos.getY(i) / h + 0.5) * (uv1 - uv0));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    const m = new THREE.Mesh(geo, mat); m.position.z = z; return m;
  };
  const slab = (shape, depth, bevel = 0.004) => new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 4, curveSegments: 32 });
  const rbox = (w, h, d) => { const g = slab(roundedRect(w, h, Math.min(w, h) / 2 - 0.0005), d, 0.002); g.translate(0, 0, -d / 2); return g; };

  // the materials the handoffs gray out
  const metal = new THREE.MeshPhysicalMaterial({ color: BURGUNDY, metalness: 0.7, roughness: 0.42, clearcoat: 0.2, clearcoatRoughness: 0.4 });
  const plateauMat = new THREE.MeshPhysicalMaterial({ color: BURGUNDY, metalness: 0.75, roughness: 0.32, clearcoat: 0.3 });
  const panelMat = new THREE.MeshPhysicalMaterial({ color: 0x531b26, roughness: 0.72, metalness: 0.35, clearcoat: 0.1, clearcoatRoughness: 0.7 });
  const ringMat = new THREE.MeshPhysicalMaterial({ color: 0x5a1d28, metalness: 0.85, roughness: 0.28, clearcoat: 0.5 });
  const markMat = new THREE.MeshPhysicalMaterial({ color: 0xa45566, alphaTest: 0.5, metalness: 0.25, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.15 });
  const tinted = [[metal, BURGUNDY.clone()], [plateauMat, BURGUNDY.clone()], [panelMat, new THREE.Color(0x531b26)], [ringMat, new THREE.Color(0x5a1d28)], [markMat, new THREE.Color(0xa45566)]];

  const bodyGeo = new THREE.ExtrudeGeometry(roundedRect(W - 0.02, H - 0.02, R), { depth: D - 0.02, bevelEnabled: true, bevelSize: 0.01, bevelThickness: 0.01, bevelSegments: 6, curveSegments: 40 });
  bodyGeo.translate(0, 0, -(D - 0.02) / 2);
  phone.add(new THREE.Mesh(bodyGeo, metal));

  // front: black glass, the screen, a clear layer that catches the room, the island
  const front = D / 2 + 0.0015;
  phone.add(shapeMesh(W - 0.022, H - 0.022, R - 0.011, new THREE.MeshPhysicalMaterial({ color: 0x050505, roughness: 0.12 }), front));
  const SW = W - 0.036, SH = SW * 2868 / 1320, SR = 0.112;
  const screenCanvas = document.createElement("canvas"); screenCanvas.width = 660; screenCanvas.height = 1434;
  const screenTex = new THREE.CanvasTexture(screenCanvas); screenTex.colorSpace = THREE.SRGBColorSpace; screenTex.anisotropy = 8;
  const screenMat = new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false });
  const screen = shapeMesh(SW, SH, SR, screenMat, front + 0.0008); phone.add(screen);
  phone.add(shapeMesh(W - 0.022, H - 0.022, R - 0.011,
    new THREE.MeshPhysicalMaterial({ color: 0xffffff, transparent: true, opacity: 0.05, roughness: 0.02, clearcoat: 1, envMapIntensity: 2.4, depthWrite: false }), front + 0.002));
  // the island sits above the slices' resting place, and grows in as they come together (main loop)
  const island = new THREE.Mesh(slab(roundedRect(0.2, 0.058, 0.029), 0.0005, 0.0005), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true }));
  island.position.set(0, SH / 2 - 0.068, front + 0.0018); phone.add(island);
  const islandHome = island.position.clone();

  // the brief: the screen in its three slices (the story template's sections), apart and then together
  // both sides show the picture, so from behind a slice reads as a pane of glass (the picture mirrored)
  const sliceMat = new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false, side: THREE.DoubleSide });
  const sliceEdge = new THREE.MeshBasicMaterial({ color: 0xaeaeb2, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false, toneMapped: false });
  const slices = [];
  const EDGE = 0.006;
  for (let i = 0; i < cuts.length - 1; i++) {
    const t = cuts[i], b = cuts[i + 1], h = (b - t) * SH;
    // each slice keeps the screen's own rounded corners where it has them: the top one at the top, the last at the bottom
    const rTop = i === 0 ? SR : 0.0001, rBottom = i === cuts.length - 2 ? SR : 0.0001;
    const card = new THREE.Group();
    card.add(shapeMesh(SW, h, rTop, sliceMat, 0, rBottom, 1 - b, 1 - t));
    // a soft gray edge, so a black slice never disappears into the black phone or page
    const ring = roundedRect(SW + EDGE, h + EDGE, rTop + EDGE / 2, rBottom + EDGE / 2);
    ring.holes.push(roundedRect(SW, h, rTop, rBottom));
    card.add(new THREE.Mesh(new THREE.ShapeGeometry(ring, 32), sliceEdge));
    card.userData.home = new THREE.Vector3(0, SH / 2 - (t + b) / 2 * SH, front + 0.0012);
    // further out toward the reader, each a step nearer than the last (the bottom one lifts as it comes, so it
    // clears the switcher under the phone)
    card.userData.away = [new THREE.Vector3(-0.07, 0.07, 0.22), new THREE.Vector3(0.24, -0.01, 0.42), new THREE.Vector3(-0.16, 0.04, 0.62)][i] || new THREE.Vector3();
    card.visible = false; phone.add(card); slices.push(card);
  }

  // sides: buttons and antenna lines
  const btn = (x, y, h) => { const b = new THREE.Mesh(rbox(0.012, h, 0.032), metal); b.position.set(x, y, 0); phone.add(b); };
  btn(-W / 2 - 0.002, 0.46, 0.07); btn(-W / 2 - 0.002, 0.3, 0.13); btn(-W / 2 - 0.002, 0.13, 0.13);
  btn(W / 2 + 0.002, 0.32, 0.2); btn(W / 2 + 0.002, -0.18, 0.14);
  const bandMat = new THREE.MeshStandardMaterial({ color: 0x2a0b10, roughness: 0.6 });
  [[-1, 1], [1, 1], [-1, -1], [1, -1]].forEach(([sx, sy]) => {
    const b = new THREE.Mesh(new THREE.BoxGeometry(0.004, 0.012, D * 0.7), bandMat);
    b.position.set(sx * (W / 2 + 0.0005), sy * (H / 2 - 0.16), 0); phone.add(b);
  });

  // back: the inset camera plateau, the glass panel stopping just short of the bottom, the CS mark
  const PT = H / 2, INSET = 0.036, PTOP = 0.04, PH = 0.43;
  const plateau = new THREE.Mesh(slab(roundedRect(W - 2 * INSET, PH, 0.1, 0.055), 0.014, 0.008), plateauMat);
  plateau.rotation.y = Math.PI; plateau.position.set(0, PT - PTOP - PH / 2, -D / 2 + 0.004); phone.add(plateau);
  const PANEL_TOP = PT - PTOP - PH - 0.048, PANEL_BOTTOM = -H / 2 + 0.036;
  const panel = shapeMesh(W - 2 * INSET, PANEL_TOP - PANEL_BOTTOM, 0.035, panelMat, -front - 0.0006, R - 0.03);
  panel.rotation.y = Math.PI; panel.position.y = (PANEL_TOP + PANEL_BOTTOM) / 2; phone.add(panel);
  const markCanvas = document.createElement("canvas"); markCanvas.width = 512; markCanvas.height = 300;
  { const g = markCanvas.getContext("2d"); g.fillStyle = "#fff"; g.font = "700 250px Helvetica Neue, Helvetica, Arial, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("CS", 256, 160); }
  markMat.alphaMap = new THREE.CanvasTexture(markCanvas);
  const mark = new THREE.Mesh(new THREE.PlaneGeometry(0.27, 0.158), markMat);
  mark.rotation.y = Math.PI; mark.position.set(0, -0.17, -front - 0.0015); phone.add(mark);
  // lenses: a thin burgundy rim, a black surround, charcoal glass, a glossy black lens with a glint
  const zp = -D / 2 - 0.026;
  const lipMat = new THREE.MeshPhysicalMaterial({ color: 0x060607, metalness: 0.2, roughness: 0.38, clearcoat: 0.4, clearcoatRoughness: 0.4, envMapIntensity: 0.35 });
  const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x2b2b30, roughness: 0.32, metalness: 0.1, clearcoat: 0.6, clearcoatRoughness: 0.3, envMapIntensity: 0.6 });
  const innerMat = new THREE.MeshPhysicalMaterial({ color: 0x050506, roughness: 0.1, metalness: 0.3, clearcoat: 1 });
  const lens = (x, y) => {
    const g = new THREE.Group(); g.position.set(x, y, 0); g.scale.set(0.88, 0.88, 1);
    const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.104, 0.108, 0.03, 64), [ringMat, lipMat, lipMat]);
    ring.rotation.x = Math.PI / 2; ring.position.z = zp - 0.012; g.add(ring);
    const rimT = new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.006, 16, 64), ringMat); rimT.position.z = zp - 0.027; g.add(rimT);
    const lip = new THREE.Mesh(new THREE.TorusGeometry(0.086, 0.013, 16, 64), lipMat); lip.position.z = zp - 0.028; g.add(lip);
    const glass = new THREE.Mesh(new THREE.SphereGeometry(0.084, 48, 16, 0, Math.PI * 2, 0, Math.PI / 5), glassMat);
    glass.rotation.x = -Math.PI / 2; glass.scale.set(1, 0.25, 1); glass.position.z = zp - 0.022; g.add(glass);
    const e1 = new THREE.Mesh(new THREE.TorusGeometry(0.036, 0.004, 12, 48), innerMat); e1.position.z = zp - 0.029; g.add(e1);
    const e2 = new THREE.Mesh(new THREE.CircleGeometry(0.036, 40), innerMat); e2.rotation.y = Math.PI; e2.position.z = zp - 0.0305; g.add(e2);
    const glint = new THREE.Mesh(new THREE.CircleGeometry(0.008, 20), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55 }));
    glint.rotation.y = Math.PI; glint.position.set(0.012, 0.012, zp - 0.031); g.add(glint);
    phone.add(g);
  };
  lens(0.228, PT - 0.16); lens(0.228, PT - 0.366); lens(0.04, PT - 0.263);
  const flash = new THREE.Mesh(new THREE.CircleGeometry(0.03, 40), new THREE.MeshPhysicalMaterial({ color: 0xf4efe6, roughness: 0.15, clearcoat: 1, emissive: 0x2a2620 }));
  flash.rotation.y = Math.PI; flash.position.set(-0.232, PT - 0.16, zp - 0.0005); phone.add(flash);
  const dot = (r, x, y) => { const m = new THREE.Mesh(new THREE.CircleGeometry(r, 24), new THREE.MeshPhysicalMaterial({ color: 0x050505, roughness: 0.2, clearcoat: 1 })); m.rotation.y = Math.PI; m.position.set(x, y, zp - 0.0005); phone.add(m); };
  dot(0.006, -0.236, PT - 0.265); dot(0.034, -0.232, PT - 0.37);

  // the device check: an Apple Intelligence glow, the soft blue, purple, pink and orange light that runs round
  // the screen's edge, starting at the bottom and going all the way round
  const siri = siriGlow(THREE, roundedRect, SW, SH, SR);
  siri.position.z = front + 0.0016; siri.visible = false; phone.add(siri);

  // ---------- notifications in Liquid Glass: real glass that bends and blurs the placement behind it ----------
  const NOTES = [
    { title: "QA Approved", body: "The build came back signed off.", icon: "check", colors: ["#4cd964", "#28b446"], y: 0.6 },
    { title: "Legal Cleared", body: "Claims and promo copy cleared review.", icon: "doc", colors: ["#3e9bff", "#0a6cf0"], y: 0.435 },
    { title: "Scheduled", body: "Publish window confirmed.", icon: "cal", colors: ["#ff5e57", "#e8332a"], y: 0.27 },
    { title: "Live", body: "On Nike.com and in the app.", icon: "live", colors: ["#c25a4a", "#8e3527"], y: 0.6 },
  ];
  const NW = 0.67, NH = NW * 236 / 1000, NR = NH * 0.32, GLASS = 0.0015, BEVEL = 0.003, zScreen = front + 0.001;
  const glassBanner = new THREE.MeshPhysicalMaterial({
    transmission: 1, thickness: 0.05, ior: 1.5, roughness: 0.22,
    clearcoat: 1, clearcoatRoughness: 0.04, specularIntensity: 1, envMapIntensity: 1.6, color: 0xffffff,
  });
  const slabGeo = new THREE.ExtrudeGeometry(roundedRect(NW - 0.01, NH - 0.01, NR - 0.005), { depth: GLASS, bevelEnabled: true, bevelSize: BEVEL, bevelThickness: BEVEL, bevelSegments: 6, curveSegments: 32 });
  const tintGeo = new THREE.ShapeGeometry(roundedRect(NW - 0.012, NH - 0.012, NR - 0.006), 32);
  const notes = NOTES.map((n) => {
    const group = new THREE.Group(); group.visible = false; phone.add(group);
    const glass = new THREE.Mesh(slabGeo, glassBanner); glass.position.z = zScreen + BEVEL + 0.0005; group.add(glass);
    const tint = new THREE.Mesh(tintGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false, toneMapped: false }));
    tint.position.z = glass.position.z + GLASS + BEVEL + 0.0004; group.add(tint);
    const c = document.createElement("canvas"); c.width = 1000; c.height = 236;
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
    const words = new THREE.Mesh(new THREE.PlaneGeometry(NW, NH), new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false, toneMapped: false }));
    words.position.z = tint.position.z + 0.0008; group.add(words);
    return { n, c, tex, group, tint, words, k: 0 };
  });
  function drawNote(c, n, dark) {
    const g = c.getContext("2d"), w = c.width, h = c.height;
    g.clearRect(0, 0, w, h);
    const ix = 40, iy = (h - 112) / 2, is = 112;
    const grad = g.createLinearGradient(0, iy, 0, iy + is); grad.addColorStop(0, n.colors[0]); grad.addColorStop(1, n.colors[1]);
    g.fillStyle = grad; g.beginPath(); g.roundRect(ix, iy, is, is, 26); g.fill();
    g.strokeStyle = "#fff"; g.fillStyle = "#fff"; g.lineWidth = 11; g.lineCap = "round"; g.lineJoin = "round"; g.beginPath();
    if (n.icon === "check") { g.moveTo(ix + 32, iy + 58); g.lineTo(ix + 50, iy + 76); g.lineTo(ix + 82, iy + 38); g.stroke(); }
    else if (n.icon === "doc") { g.lineWidth = 8; g.roundRect(ix + 32, iy + 24, 48, 64, 7); g.moveTo(ix + 42, iy + 46); g.lineTo(ix + 70, iy + 46); g.moveTo(ix + 42, iy + 62); g.lineTo(ix + 62, iy + 62); g.stroke(); }
    else if (n.icon === "cal") {   // a calendar page: a band across the top and a grid of days (no particular date)
      g.lineWidth = 7; g.beginPath(); g.roundRect(ix + 26, iy + 28, 60, 58, 8); g.stroke();
      g.fillRect(ix + 26, iy + 28, 60, 14);
      for (let r = 0; r < 2; r++) for (let q = 0; q < 3; q++) { g.beginPath(); g.arc(ix + 40 + q * 16, iy + 56 + r * 15, 3.5, 0, Math.PI * 2); g.fill(); }
    }
    else { g.beginPath(); g.arc(ix + 56, iy + 56, 16, 0, Math.PI * 2); g.fill(); g.lineWidth = 6; g.beginPath(); g.arc(ix + 56, iy + 56, 32, 0, Math.PI * 2); g.globalAlpha = 0.6; g.stroke(); g.globalAlpha = 1; }
    const tx = ix + is + 30, ink = dark ? "#f5f5f7" : "#1d1d1f", second = dark ? "rgba(235,235,245,.62)" : "rgba(60,60,67,.62)";
    g.textBaseline = "alphabetic";
    g.fillStyle = ink; g.font = "600 46px -apple-system, 'SF Pro Text', Helvetica, sans-serif"; g.fillText(n.title, tx, h / 2 - 8);
    g.fillStyle = second; g.font = "400 38px -apple-system, 'SF Pro Text', Helvetica, sans-serif"; g.textAlign = "right"; g.fillText("now", w - 46, h / 2 - 10);
    g.textAlign = "left"; g.fillStyle = ink; g.font = "400 42px -apple-system, 'SF Pro Text', Helvetica, sans-serif"; g.fillText(n.body, tx, h / 2 + 48);
  }

  // ---------- the screen: this set's placement, rolling to the next screen once it's live ----------
  let shots = { src: null, next: null }, rollDrawn = -1;
  const loadImg = (url) => new Promise((ok) => { if (!url) return ok(null); const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = url; });
  function useSet(i) {
    const s = sets[i] || sets[0];
    Promise.all([loadImg(s.src), loadImg(s.next)]).then(([a, b]) => { shots = { src: a, next: b }; rollDrawn = -1; kick(); });
  }
  function drawScreen(roll) {
    if (!shots.src || Math.abs(roll - rollDrawn) < 0.001) return;
    rollDrawn = roll;
    const g = screenCanvas.getContext("2d"), w = screenCanvas.width, h = screenCanvas.height;
    g.fillStyle = "#000"; g.fillRect(0, 0, w, h);
    g.drawImage(shots.src, 0, -roll * h, w, h);
    if (shots.next && roll > 0) g.drawImage(shots.next, 0, (1 - roll) * h, w, h);
    screenTex.needsUpdate = true;
  }
  useSet(0);
  scene.querySelectorAll(".sc-switch button").forEach((b) => b.addEventListener("click", () => useSet(+b.dataset.set)));

  // ---------- light and dark: the page's setting, or the switch in the header ----------
  let wake = () => {};
  const root = document.documentElement, systemDark = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => root.classList.contains("can-dark") && (root.classList.contains("theme-dark") || (!root.classList.contains("theme-light") && systemDark.matches));
  let dark = null;
  function applyTheme() {
    const d = isDark();
    if (d === dark) return;
    dark = d;
    wake();   // (kick, once the loop is set up)
    notes.forEach(({ n, c, tex }) => { drawNote(c, n, d); tex.needsUpdate = true; });
    glassBanner.color.set(d ? 0xd8d8de : 0xffffff);
    renderer.toneMappingExposure = d ? 0.95 : 1.1;
    key.intensity = d ? 1.1 : 1.6;
  }
  new MutationObserver(applyTheme).observe(root, { attributes: true, attributeFilter: ["class"] });
  systemDark.addEventListener?.("change", applyTheme);
  applyTheme();

  // ---------- where the scroll is: the same measure main.js uses for the stages ----------
  const N = scene.querySelectorAll(".sc-panel").length || 7;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const ease = (t) => (t = clamp(t), t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const pin = () => parseFloat(getComputedStyle(root).getPropertyValue("--pills-h")) || 0;
  const progress = () => {
    const r = scene.getBoundingClientRect(), run = r.height - (innerHeight - pin());
    return run > 0 ? clamp((pin() - r.top) / run) : 0;
  };

  // the pose of each step: turn (y), tilt (x), drop (into the gray lane), gray, and what's on the screen
  function pose(p) {
    const at = Math.min(N - 1, Math.floor(p * N)), k = p * N - at;
    const o = { ry: -0.42, rx: 0.1, y: 0, s: 1, gray: 0, apart: Math.pow(Math.max(0, 1 - p * N / 1.6), 2), glow: 0, roll: 0, notes: [0, 0, 0, 0], mine: 1 };
    if (at === 1) { o.ry = -0.42 + 0.22 * ease(k); o.rx = 0.1 - 0.04 * ease(k); }
    if (at === 2) {   // the device check: the phone lifts and turns all the way round, then a line of light runs down it
      o.ry = -0.2 + ease(clamp(k / 0.6)) * Math.PI * 2; o.rx = 0.06; o.y = 0.05 * Math.sin(Math.PI * clamp(k / 0.6));
      // the glow slowly appears round the whole edge, pulses, and fades away before the step ends
      o.glow = k < 0.55 ? 0 : k < 0.72 ? ease((k - 0.55) / 0.17) : k < 0.86 ? 1 : 1 - ease((k - 0.86) / 0.12);
    }
    if (at === 3 || at === 4) {   // out of his hands: lower, smaller, gray; the sign-offs arrive
      const d = at === 3 ? ease(clamp(k / 0.35)) : 1;
      o.ry = -0.2 + 0.1 * d; o.rx = 0.06; o.y = -0.06 * d; o.s = 1 - 0.08 * d; o.gray = d; o.mine = 1 - d;   // it sinks from the top; its foot stays clear of the switcher
      o.notes[0] = at === 4 ? 1 : clamp((k - 0.45) / 0.2);
      o.notes[1] = at === 4 ? clamp((k - 0.3) / 0.2) : 0;
    }
    if (at === 5) {   // back in his lane, stamped: color returns, and he schedules it
      const u = 1 - ease(clamp(k / 0.35));
      o.ry = -0.1 - 0.12 * (1 - u); o.rx = 0.06; o.y = -0.06 * u; o.s = 1 - 0.08 * u; o.gray = u; o.mine = 1 - u;
      o.notes = [1, 1, clamp((k - 0.45) / 0.2), 0];
    }
    if (at === 6) {   // live: the sign-offs clear, the next screen rolls up, Live arrives
      const clear = clamp(k / 0.2);
      o.ry = -0.22 + 0.12 * ease(k); o.rx = 0.04; o.notes = [1 - clear, 1 - clear, 1 - clear, clamp((k - 0.55) / 0.2)];
      o.roll = ease(clamp((k - 0.15) / 0.4));
    }
    return o;
  }

  // ---------- grab and turn: follows the pointer, coasts, then eases back to the step's pose ----------
  let drag = null, off = { x: 0, y: 0 }, vel = { x: 0, y: 0 }, idle = 0;
  visual.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" && e.pointerType !== "pen") return;   // touch scrolls the page
    if (!scene.classList.contains("has-3d") || e.target.closest("button, a, .sc-count, .n3-note, .n3-dock")) return;
    drag = { x: e.clientX, y: e.clientY }; visual.setPointerCapture(e.pointerId); visual.classList.add("is-dragging"); vel = { x: 0, y: 0 };
  });
  visual.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY };
    off.y += dx * 0.009; off.x = clamp(off.x + dy * 0.006, -0.7, 0.7);
    vel = { x: dy * 0.006, y: dx * 0.009 };
  });
  const release = () => { if (!drag) return; drag = null; visual.classList.remove("is-dragging"); idle = performance.now(); };
  // the phone leans a little toward the pointer while it's over the section (mouse only), and settles back after
  const look = { x: 0, y: 0 }, lookAim = { x: 0, y: 0 };
  scene.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    const r = canvas.getBoundingClientRect();
    lookAim.x = clamp(((e.clientX - (r.left + r.width / 2)) / (r.width / 2)), -1, 1);
    lookAim.y = clamp(((e.clientY - (r.top + r.height / 2)) / (r.height / 2)), -1, 1);
  });
  scene.addEventListener("pointerleave", () => { lookAim.x = 0; lookAim.y = 0; });
  visual.addEventListener("pointerup", release); visual.addEventListener("pointercancel", release);

  // ---------- the side controls: like the Cohesity animation's, a tab on the column's right edge slides out a pill
  // (spin, zoom in, how it was made); it tucks back on its own, on a click elsewhere, or on Escape ----------
  const ICON = {
    spin: '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="12" rx="9" ry="4"/><path d="M15.5 6.6l2.6 1.9-2.9 1.4"/><path d="M12 3v18" opacity=".45"/></svg>',
    zoom: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.3 15.3L20 20M10.5 7.8v5.4M7.8 10.5h5.4"/></svg>',
    info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="6.8" r="1.5" class="dot"/><path d="M12 11v7.5"/></svg>',
  };
  const dock = document.createElement("div");
  dock.className = "n3-dock";
  dock.innerHTML = '<div class="n3-drawer"><button class="n3-tab" type="button" aria-label="Show phone controls" aria-expanded="false">'
    + '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5L8.5 12l6 6.5"/></svg></button>'
    + '<div class="n3-controls" role="group" aria-label="Phone controls">'
    + `<button class="n3-btn" type="button" data-act="spin" aria-label="Spin the phone" aria-pressed="false">${ICON.spin}</button>`
    + `<button class="n3-btn" type="button" data-act="zoom" aria-label="Zoom in close">${ICON.zoom}</button>`
    + `<button class="n3-btn" type="button" data-act="info" aria-label="How This Phone Was Made" aria-expanded="false" aria-controls="n3-note">${ICON.info}</button>`
    + '</div></div>';
  const note = document.createElement("aside");
  note.className = "n3-note"; note.id = "n3-note"; note.setAttribute("aria-label", "How This Phone Was Made");
  note.innerHTML = '<button class="n3-note-close" type="button" aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg></button>'
    + '<p class="n3-note-title">How This Phone Was Made</p>'
    + "<p>Directing Claude Code, I storyboarded the journey from request to live, then built the phone and every step in three.js, refining the details against real phone photography until they held up.</p>";
  visual.append(dock, note);
  const tab = dock.querySelector(".n3-tab"), pill = dock.querySelector(".n3-controls"), infoBtn = dock.querySelector('[data-act="info"]');
  let tuckTimer = 0, overPill = false;
  function showControls(on) {
    clearTimeout(tuckTimer);
    if (!on && pill.contains(document.activeElement)) tab.focus({ preventScroll: true });
    dock.classList.toggle("is-out", on);
    tab.setAttribute("aria-expanded", String(on));
    pill.inert = !on;
    if (on) tuckLater();
  }
  function tuckLater() {
    clearTimeout(tuckTimer);
    if (!overPill && !pill.querySelector(":focus-visible")) tuckTimer = setTimeout(() => showControls(false), 3500);
  }
  tab.addEventListener("click", () => showControls(true));
  pill.addEventListener("pointerenter", () => { overPill = true; clearTimeout(tuckTimer); });
  pill.addEventListener("pointerleave", () => { overPill = false; tuckLater(); });
  pill.addEventListener("click", tuckLater);
  pill.addEventListener("focusin", () => setTimeout(() => { if (pill.querySelector(":focus-visible")) clearTimeout(tuckTimer); }));
  pill.addEventListener("focusout", () => setTimeout(tuckLater));
  document.addEventListener("pointerdown", (e) => { if (dock.classList.contains("is-out") && !dock.contains(e.target)) showControls(false); });
  showControls(false);
  // the note: opens and closes from its button, which stays lit while it's open
  const setNote = (on) => { scene.classList.toggle("n3-noting", on); infoBtn.setAttribute("aria-expanded", String(on)); };
  infoBtn.addEventListener("click", () => setNote(!scene.classList.contains("n3-noting")));
  note.querySelector(".n3-note-close").addEventListener("click", () => setNote(false));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (scene.classList.contains("n3-noting")) setNote(false);
    if (dock.classList.contains("is-out")) showControls(false);
  });
  // the shows: a full turn, and a commercial push-in on the cameras
  // spin is a switch: on, the phone keeps turning like a showroom turntable, speeding up and slowing down, while the
  // camera drifts in and out over different parts of it; off, it settles back. The zoom is a commercial pass down the
  // screen: one turn to face the reader, then a slow close-up from the top of the placement down to its nav bar
  let spinning = false, spinK = 0, spinAngle = 0, zoomAt = -1;
  const spinBtn = dock.querySelector('[data-act="spin"]');
  const setSpin = (on) => { spinning = on; spinBtn.setAttribute("aria-pressed", String(on)); if (on) zoomAt = -1; kick(); };
  spinBtn.addEventListener("click", () => setSpin(!spinning));
  dock.querySelector('[data-act="zoom"]').addEventListener("click", () => { setSpin(false); zoomAt = performance.now(); kick(); });
  const midOf = (a, b) => SH / 2 - (a + b) / 2 * SH;   // the screen height at the middle of a stretch of the placement
  // the close-up: one full turn that ends facing straight on, then the camera moves in close to the top of the screen
  // and slowly travels down it so the words can be read, then pulls back
  const Z_SPIN = 1600, Z_IN = 1200, Z_PAN = 16000, Z_OUT = 1200, ZOOM_MS = Z_SPIN + Z_IN + Z_PAN + Z_OUT;
  const PAN_TOP = SH / 2 - 0.3, PAN_BOTTOM = -SH / 2 + 0.3;
  const lookAt = new THREE.Vector3(), aim = new THREE.Vector3();

  // ---------- sizing: the canvas covers the flat phone's place, with room round it to turn ----------
  const FOV = 28, ROOM = 1.75, SIDE = 0.4;
  function size() {
    if (full) return;   // the shows size themselves (fullFrame)
    const v = visual.getBoundingClientRect(), f = flat.getBoundingClientRect();
    if (!f.width) return;
    // the canvas is this many phones tall, and reaches past the column on both sides, so the brief's slices, the
    // full turn and a phone spun by hand are never cut off; it is centred on the flat phone's place
    const h = f.height * ROOM, w = v.width * (1 + 2 * SIDE);
    const cx = f.left + f.width / 2 - v.left;
    Object.assign(canvas.style, { left: `${cx - w / 2}px`, top: `${f.top - v.top - f.height * (ROOM - 1) / 2}px`, width: `${w}px`, height: `${h}px` });
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = FOV;
    camBase = (H * ROOM / 2) / Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    camera.position.set(0, 0, camBase);
    camera.updateProjectionMatrix();
    note.style.top = `${f.top - v.top + f.height * 0.6}px`;
    note.style.left = `${cx}px`;
  }
  let camBase = 5;
  // the shows (spin, zoom) step the phone out over the whole page: the canvas covers the window, in front of the
  // words (casting a soft shadow on them), behind the tab bar, the switcher and these controls. The phone stays
  // the same size and in the same place, by shifting the lens's centre to where it stood
  const stageEl = scene.querySelector(".sc-stage");
  let full = false, fullW = 0, fullH = 0, centreK = 0;
  function setFull(on) {
    if (on === full) return;
    full = on;
    if (on) { canvas.removeAttribute("style"); canvas.classList.add("ph3d-full"); stageEl.append(canvas); fullW = fullH = 0; }
    else { canvas.classList.remove("ph3d-full"); visual.append(canvas); renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); size(); }
  }
  function fullFrame() {
    const f = flat.getBoundingClientRect(), W = innerWidth, Hv = innerHeight;
    if (W !== fullW || Hv !== fullH) { fullW = W; fullH = Hv; renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5)); renderer.setSize(W, Hv, false); }
    camera.aspect = W / Hv;
    camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan((H * ROOM * Hv / (f.height * ROOM)) / 2 / camBase));
    camera.updateProjectionMatrix();
    // centred on the phone's place, moving to the window's centre as the close-up comes in
    const e = camera.projectionMatrix.elements;
    e[8] = -(2 * (f.left + f.width / 2) / W - 1) * (1 - centreK); e[9] = -(1 - 2 * (f.top + f.height / 2) / Hv) * (1 - centreK);
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  }
  new ResizeObserver(size).observe(visual);
  size();

  // ---------- the loop: only while the pinned layout is on and the scene is on screen ----------
  let onScreen = false, raf = 0, last = performance.now();
  const cur = { ry: -0.42, rx: 0.1, y: 0, s: 1, gray: 0, mine: 1 };
  const live = () => scene.classList.contains("is-live");
  function frame(now) {
    raf = 0;
    // settled, only the float is moving: it draws at 30 frames a second instead of 60
    if (still > 20 && now - lastDraw < 32) { raf = requestAnimationFrame(frame); return; }
    lastDraw = now;
    if (!onScreen || !live()) { flag("has-3d", false); return; }
    flag("has-3d", true);
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const o = pose(progress());
    const f = 1 - Math.exp(-dt * 7);   // follows the scroll closely, without judder
    for (const k of ["rx", "y", "s", "gray", "mine"]) cur[k] += (o[k] - cur[k]) * f;
    // the turn takes the short way to each step's pose (the device check's full turn doesn't unwind afterwards)
    const ry = o.ry + Math.round((cur.ry - o.ry) / (Math.PI * 2)) * Math.PI * 2;
    cur.ry += (ry - cur.ry) * f;
    if (!drag) {
      off.x += vel.x; off.y += vel.y; vel.x *= 0.9; vel.y *= 0.9;
      if (now - idle > 900) {
        const turns = Math.round(off.y / (Math.PI * 2));
        off.x += (0 - off.x) * Math.min(1, dt * 3.5); off.y += (turns * Math.PI * 2 - off.y) * Math.min(1, dt * 3.5);
      }
    }
    const lf = Math.min(1, dt * 4);
    look.x += ((drag ? 0 : lookAim.x) - look.x) * lf; look.y += ((drag ? 0 : lookAim.y) - look.y) * lf;
    if (Math.abs(look.x - lookAim.x) + Math.abs(look.y - lookAim.y) < 0.002 && !drag) { look.x = lookAim.x; look.y = lookAim.y; }
    // the turntable: its speed wanders between slow and fast; off, it settles to the nearest full turn
    spinK += ((spinning ? 1 : 0) - spinK) * Math.min(1, dt * 2.2);
    if (spinning) spinAngle += (0.3 + 1.3 * Math.pow(0.5 + 0.5 * Math.sin(now / 1700) * Math.sin(now / 2900 + 1.3), 2)) * dt;
    else spinAngle += (Math.round(spinAngle / (Math.PI * 2)) * Math.PI * 2 - spinAngle) * Math.min(1, dt * 2.5);
    // the close-up: a turn to face the reader (zf), then in close (zk), down the screen, and out
    let zk = 0, zf = 0, zturn = 0, shotY = PAN_TOP, sway = 0;
    if (zoomAt >= 0) {
      const t = now - zoomAt;
      if (t >= ZOOM_MS) zoomAt = -1;
      else {
        zturn = ease(clamp(t / Z_SPIN)) * Math.PI * 2;
        zf = t > ZOOM_MS - Z_OUT ? 1 - ease((t - (ZOOM_MS - Z_OUT)) / Z_OUT) : ease(clamp(t / Z_SPIN));
        const ti = t - Z_SPIN;
        zk = ti <= 0 ? 0 : ti < Z_IN ? ease(ti / Z_IN) : t > ZOOM_MS - Z_OUT ? 1 - ease((t - (ZOOM_MS - Z_OUT)) / Z_OUT) : 1;
        // starts at the top and glides steadily down, easing at both ends
        shotY = PAN_TOP + (PAN_BOTTOM - PAN_TOP) * ease(clamp((ti - Z_IN * 0.6) / Z_PAN));
      }
    }
    const lx = look.y * 0.06 * (1 - zf), ly = look.x * 0.13 * (1 - zf);   // a slight lean toward the pointer from the step's pose (none during the zoom)
    const wob = spinK * 0.1 * Math.sin(now / 2600);                          // the turntable tips a little as it turns
    const hero = ease(spinK);
    rig.rotation.set(0.3 * hero, 0, -0.32 * hero);                            // the hero angle: leaning back, tilted to one side
    phone.rotation.set(cur.rx + off.x + lx + wob + (0 - cur.rx - off.x) * zf, cur.ry + off.y + ly + spinAngle + zturn + (0 - cur.ry - off.y) * zf, 0);   // straight on, to read
    phone.position.y = cur.y + Math.sin(now / 900) * 0.012;   // the slow float
    phone.scale.setScalar(cur.s);
    // gray in the handoffs, burgundy in his steps; his steps also get a warm accent edge light
    tinted.forEach(([m, c]) => m.color.copy(c).lerp(GRAPHITE, cur.gray));
    screenMat.color.setScalar(1 - 0.35 * cur.gray); sliceMat.color.copy(screenMat.color);
    rim.color.set(0xc25a4a); rim.intensity = (dark ? 3.2 : 1.4) * cur.mine;
    rim2.color.set(dark ? 0xff9fb2 : 0xffffff); rim2.intensity = dark ? 1.2 : 0.4;
    // the brief's slices, or the whole screen
    const apart = o.apart;
    screen.visible = apart < 0.002;
    slices.forEach((m) => { m.visible = !screen.visible; m.position.copy(m.userData.home).addScaledVector(m.userData.away, apart); });
    drawScreen(o.roll);
    // the island grows in as the slices close; the glow fades in, breathes, and fades before the step is done
    const ik = clamp(1 - apart * 3);
    island.material.opacity = ik; island.scale.set(0.5 + 0.5 * ease(ik), 0.6 + 0.4 * ease(ik), 1); island.visible = ik > 0.01;
    island.position.copy(islandHome); if (slices[0]) island.position.addScaledVector(slices[0].userData.away, apart);   // it rides in on the top slice
    const u = siri.material.uniforms;
    u.uOpacity.value += (o.glow * (0.72 + 0.28 * Math.sin(now / 420)) - u.uOpacity.value) * Math.min(1, dt * 6);   // breathing
    u.uProg.value = 1;
    u.uTime.value = now / 1000;
    siri.visible = u.uOpacity.value > 0.01;
    // the notifications drop in (and leave) like iOS banners
    notes.forEach((nt, i) => {
      nt.k += (o.notes[i] - nt.k) * Math.min(1, dt * 9);
      const k = nt.k;
      nt.group.visible = k > 0.02;
      nt.group.position.y = nt.n.y + (1 - k) * 0.12;
      nt.group.scale.setScalar(0.94 + 0.06 * k);
      nt.words.material.opacity = k; nt.tint.material.color.set(dark ? 0x1c1c1e : 0xffffff); nt.tint.material.opacity = k * (dark ? 0.6 : 0.8);   // enough tint that the glass reads as a solid banner (whiter by day)
    });
    if (zk > 0) {   // close on the screen, a little to one side, looking at the shot's point on it
      phone.updateMatrixWorld();
      const target = phone.localToWorld(aim.set(sway, shotY, front));
      // straight on, close enough to read, with both sides of the phone still in the frame
      const fit = (W * 1.3 / 2) / (Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * Math.min(camera.aspect, 1.6));
      camera.position.set(target.x * zk, target.y * zk, camBase + (target.z + fit - camBase) * zk);
      camera.lookAt(lookAt.set(target.x * zk, target.y * zk, target.z * zk));
    } else if (spinK > 0.002) {   // the turntable's camera drifts in and out, its aim wandering up and down the phone
      const fy = (Math.sin(now / 2300) * 0.3 + Math.sin(now / 3700 + 2) * 0.14) * spinK;
      const near = (0.5 + 0.5 * Math.sin(now / 3100 + 0.7)) * spinK;
      camera.position.set(0, fy * 0.5, camBase * (1 - 0.22 * near));
      camera.lookAt(lookAt.set(0, fy, 0));
    } else if (camera.position.z !== camBase || camera.position.x !== 0 || camera.position.y !== 0) { camera.position.set(0, 0, camBase); camera.lookAt(0, 0, 0); }
    // out over the page during the shows; back in its column after
    const showing = zk > 0 || zf > 0 || spinK > 0.01;
    setFull(showing);
    centreK = zk;
    flag("n3-zooming", zk > 0.02);   // the close-up passes over the placement switcher too
    if (full) fullFrame();
    const sk = Math.max(zk, spinK);
    cast.visible = sk > 0.01; cast.material.opacity = sk * (dark ? 0.7 : 0.45) * (1 - zk * 0.6);
    // the tab sits on the window's right edge, level with the phone
    const fr = flat.getBoundingClientRect(); dock.style.top = `${fr.top + fr.height / 2}px`;
    renderer.render(world, camera);
    // once the phone has settled (no scroll, pointer, drag, show, glow or banner moving) only the float runs, at half
    // the frame rate; the next scroll, pointer move, click or resize brings it back to full
    const sig = [phone.rotation.x, phone.rotation.y, cur.y, phone.scale.x, cur.gray, look.x, look.y, off.x, off.y, apart, o.roll,
      ...notes.map((n) => n.k), island.material.opacity, camera.position.z];
    const moved = sig.some((v, i) => Math.abs(v - (lastSig[i] ?? 1e9)) > 3e-4);
    lastSig = sig;
    const busy = drag || spinning || spinK > 0.002 || zoomAt >= 0 || siri.visible || Math.abs(vel.x) + Math.abs(vel.y) > 1e-5;
    still = moved || busy ? 0 : still + 1;
    raf = requestAnimationFrame(frame);
  }
  let lastSig = [], still = 0, lastDraw = 0;
  // classes are only written when they change: any write wakes the loop (it watches the section's classes)
  function flag(c, on) { if (scene.classList.contains(c) !== on) scene.classList.toggle(c, on); }
  wake = () => kick();
  const kick = () => { still = 0; if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); } };
  addEventListener("scroll", () => { if (onScreen) kick(); }, { passive: true });
  addEventListener("resize", () => { if (onScreen) kick(); }, { passive: true });
  scene.addEventListener("pointermove", kick, { passive: true });
  scene.addEventListener("pointerleave", kick);
  scene.addEventListener("click", kick);
  new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; if (onScreen) kick(); }, { threshold: 0 }).observe(scene);
  new MutationObserver(kick).observe(scene, { attributes: true, attributeFilter: ["class"] });
}

// a small studio for the reflections: a dim room with soft light panels (like three.js's RoomEnvironment)
function studio(THREE) {
  const room = new THREE.Scene();
  const box = new THREE.BoxGeometry();
  const walls = new THREE.Mesh(box, new THREE.MeshStandardMaterial({ side: THREE.BackSide, color: 0x7a7a7a }));
  walls.scale.set(10, 8, 10); walls.position.y = 2; room.add(walls);
  const panel = (x, y, z, sx, sy, sz, power) => {
    const m = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: new THREE.Color(power, power, power) }));
    m.position.set(x, y, z); m.scale.set(sx, sy, sz); room.add(m);
  };
  panel(-4.9, 3, 0, 0.1, 3, 5, 6); panel(4.9, 2, 1, 0.1, 2, 3, 4); panel(0, 5.9, 0, 4, 0.1, 4, 8); panel(0, 2.5, -4.9, 4, 2, 0.1, 3); panel(0, 2, 4.9, 3, 2, 0.1, 2);
  return room;
}

// the Apple Intelligence edge glow: a band just inside the screen's rounded edge, brightest at the edge and fading
// inward, its colors flowing round (uProg below 1 would reveal it from the bottom centre round; the scene keeps it at 1)
function siriGlow(THREE, roundedRect, w, h, r) {
  const BAND = 0.07, N = 360;
  const outer = roundedRect(w, h, r).getSpacedPoints(N), inner = roundedRect(w - 2 * BAND, h - 2 * BAND, Math.max(0.001, r - BAND)).getSpacedPoints(N);
  // the paths start at the bottom-left corner; shift so the glow starts at the bottom centre
  const per = 2 * (w + h) - 8 * r + 2 * Math.PI * r, shift = (w / 2 - r) / per;
  const pos = [], edge = [], tt = [], idx = [];
  for (let i = 0; i <= N; i++) {
    const t = ((i / N - shift) % 1 + 1) % 1;
    pos.push(outer[i].x, outer[i].y, 0, inner[i].x, inner[i].y, 0);
    edge.push(1, 0); tt.push(t, t);
    if (i < N) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("edge", new THREE.Float32BufferAttribute(edge, 1));
  geo.setAttribute("tpos", new THREE.Float32BufferAttribute(tt, 1));
  geo.setIndex(idx);
  const mat = new THREE.ShaderMaterial({
    uniforms: { uProg: { value: 0 }, uTime: { value: 0 }, uOpacity: { value: 0 } },
    vertexShader: `attribute float edge; attribute float tpos; varying float vEdge; varying float vT;
      void main() { vEdge = edge; vT = tpos; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform float uProg; uniform float uTime; uniform float uOpacity; varying float vEdge; varying float vT;
      vec3 pal(float x) {   // blue, purple, pink, orange, round again
        x = fract(x) * 4.0;
        vec3 c0 = vec3(0.03, 0.58, 1.0), c1 = vec3(0.79, 0.35, 0.87), c2 = vec3(1.0, 0.18, 0.33), c3 = vec3(1.0, 0.56, 0.02);
        if (x < 1.0) return mix(c0, c1, x); if (x < 2.0) return mix(c1, c2, x - 1.0); if (x < 3.0) return mix(c2, c3, x - 2.0); return mix(c3, c0, x - 3.0);
      }
      void main() {
        float shown = uProg >= 0.999 ? 1.0 : clamp((uProg - vT) / 0.05, 0.0, 1.0);   // a soft leading edge as it travels
        float a = pow(vEdge, 2.2) * shown * uOpacity;
        gl_FragColor = vec4(pal(vT * 1.5 - uTime * 0.25), a);
      }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, toneMapped: false,
  });
  return new THREE.Mesh(geo, mat);
}
