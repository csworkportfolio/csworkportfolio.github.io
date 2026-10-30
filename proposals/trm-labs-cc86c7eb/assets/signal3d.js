// The signal, in three.js. Staged like the reference footage: the camera sits low and looks up; a moving-head
// fixture stands big in the foreground, right of centre; its beam shoots up and away into haze, so it recedes
// into depth as it sweeps. The beam is a soft core cone plus a chain of billboarded haze puffs (the scattering),
// with particles riding it on the GPU. High above is a cloud deck; where the beam hits it, a disc of light lands,
// foreshortened. The head flickers to life mid-sweep, searches, catches a flock and two figures, then locks onto
// the spot that sits top-centre of the frame, where TRM's mark gathers out of dots and the real white mark settles.
// Falls back to signal.js without WebGL.
(function () {
  const host = document.querySelector(".trm-signal");
  if (!host || typeof THREE === "undefined") return;
  const canvas = host.querySelector("canvas"), copy = host.querySelector(".trm-signal-copy");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" }); }
  catch (e) { return; }
  window.__trmSignal3D = true;
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#00124D");
  scene.fog = new THREE.FogExp2(0x000d3a, 0.010);
  const camera = new THREE.PerspectiveCamera(50, 2, 0.1, 500);
  camera.position.set(0, 1.5, 10);
  const LOOK = new THREE.Vector3(0, 22, -40);
  camera.lookAt(LOOK);
  const CYAN = new THREE.Color("#06E4F9");
  const rnd = (a, b) => a + Math.random() * (b - a);
  const ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
  const U = { time: { value: 0 }, intensity: { value: still ? 1 : 0 } };
  const CLOUD_Y = 44;   // the deck the beam lands on

  // ---- sky, cloud deck, drifting cloud
  const softTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    const r = g.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.45, "rgba(255,255,255,0.4)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, 256, 256); return new THREE.CanvasTexture(c);
  })();
  const clouds = [];
  for (let i = 0; i < 14; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: softTex, color: new THREE.Color("#4A63B8"), transparent: true, opacity: rnd(0.05, 0.11), depthWrite: false, fog: false }));
    const sc = rnd(40, 90); s.position.set(rnd(-110, 110), CLOUD_Y + rnd(-14, 6), rnd(-130, -10)); s.scale.set(sc * 1.9, sc * 0.6, 1); s.userData.v = rnd(0.3, 0.9) * (i % 2 ? 1 : -1);
    scene.add(s); clouds.push(s);
  }

  // ---- a reflective night around the metal and glass
  const envTex = (() => {
    const c = document.createElement("canvas"); c.width = 512; c.height = 256; const g = c.getContext("2d");
    const grad = g.createLinearGradient(0, 0, 0, 256); grad.addColorStop(0, "#02071E"); grad.addColorStop(0.48, "#0B1A4A"); grad.addColorStop(0.52, "#2A3A6A"); grad.addColorStop(0.6, "#0A1230"); grad.addColorStop(1, "#05081A");
    g.fillStyle = grad; g.fillRect(0, 0, 512, 256);
    for (let k = 0; k < 40; k++) { g.fillStyle = `rgba(255,220,160,${0.3 + Math.random() * 0.5})`; g.fillRect(Math.random() * 512, 118 + Math.random() * 14, 2 + Math.random() * 6, 2); }
    const t = new THREE.CanvasTexture(c); t.mapping = THREE.EquirectangularReflectionMapping; return t;
  })();
  scene.environment = new THREE.PMREMGenerator(renderer).fromEquirectangular(envTex).texture;

  // ---- the fixture: an anti-aircraft searchlight. Pedestal and turntable (pans), trunnion arms, and a wide
  // shallow drum (tilts) with a ribbed glass face and a cross frame. The head's local +Y is the beam.
  scene.add(new THREE.AmbientLight("#8FA3DC", 0.18));
  scene.add(new THREE.HemisphereLight("#5B74C4", "#0A1030", 0.25));
  const key = new THREE.DirectionalLight("#D6DEFF", 0.25); key.position.set(-18, 26, 24); scene.add(key);
  const rimL = new THREE.DirectionalLight("#7FD0FF", 0.7); rimL.position.set(12, 10, -20); scene.add(rimL);
  const fill = new THREE.PointLight("#8FD8FF", 4, 40, 2); fill.position.set(-4, 4, 8); scene.add(fill);
  const olive = new THREE.MeshStandardMaterial({ color: "#1E2418", metalness: 0.35, roughness: 0.62, envMapIntensity: 0.25 });
  const olive2 = new THREE.MeshStandardMaterial({ color: "#161B12", metalness: 0.35, roughness: 0.7, envMapIntensity: 0.2 });
  const steel = new THREE.MeshStandardMaterial({ color: "#4A4F4A", metalness: 0.9, roughness: 0.35, envMapIntensity: 0.5 });
  const fixture = new THREE.Group(); fixture.position.set(3.6, -2.4, 1.6); fixture.scale.setScalar(0.82); scene.add(fixture);
  // pedestal: base plate, round turntable, column
  const plate = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.35, 3.6), olive2); plate.position.y = -0.2; fixture.add(plate);
  const turntable = new THREE.Mesh(new THREE.CylinderGeometry(1.7, 1.8, 0.5, 48), olive); turntable.position.y = 0.2; fixture.add(turntable);
  const yoke = new THREE.Group(); yoke.position.y = 0.45; fixture.add(yoke);
  const column = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.7, 1.6, 32), olive); column.position.y = 0.8; yoke.add(column);
  const saddle = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.4, 1.2), olive); saddle.position.y = 1.7; yoke.add(saddle);
  // trunnion arms: two curved arms from the saddle up to the drum's pivots
  for (const sx of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.TorusGeometry(2.3, 0.17, 12, 32, Math.PI * 0.62), olive);
    arm.position.set(sx * 2.55, 1.9, 0); arm.rotation.y = sx > 0 ? Math.PI * 0.69 : Math.PI * 0.31; arm.rotation.z = 0; yoke.add(arm);
    const boss = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.36, 24), steel); boss.rotation.z = Math.PI / 2; boss.position.set(sx * 2.52, 3.75, 0); yoke.add(boss);
  }
  const head = new THREE.Group(); head.position.y = 3.75; yoke.add(head);
  const DR = 2.35;   // drum radius; the face is the whole front
  const drum = new THREE.Mesh(new THREE.CylinderGeometry(DR, DR * 0.96, 1.5, 64), olive); drum.position.y = 0.05; head.add(drum);
  const back = new THREE.Mesh(new THREE.SphereGeometry(DR * 0.96, 48, 24, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), olive); back.scale.y = 0.42; back.position.y = -0.7; head.add(back);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(DR + 0.02, 0.13, 12, 64), olive2); rim.rotation.x = Math.PI / 2; rim.position.y = 0.82; head.add(rim);
  for (let k = 0; k < 10; k++) {   // the clamps around the rim
    const a = (k / 10) * Math.PI * 2, cl = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.34, 0.3), steel);
    cl.position.set(Math.cos(a) * (DR + 0.08), 0.78, Math.sin(a) * (DR + 0.08)); cl.rotation.y = -a; head.add(cl);
  }
  // the glass: a disc with vertical ribs drawn into it, slightly see-through, over a dark reflector dish
  const ribTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 512; const g = c.getContext("2d");
    g.fillStyle = "rgba(190,215,235,0.55)"; g.fillRect(0, 0, 512, 512);
    for (let x = 0; x < 512; x += 11) { g.fillStyle = "rgba(255,255,255,0.35)"; g.fillRect(x, 0, 3, 512); g.fillStyle = "rgba(40,60,90,0.35)"; g.fillRect(x + 6, 0, 3, 512); }
    return new THREE.CanvasTexture(c);
  })();
  const dish = new THREE.Mesh(new THREE.CircleGeometry(DR * 0.97, 64), new THREE.MeshStandardMaterial({ color: "#0E1626", metalness: 0.8, roughness: 0.25, envMapIntensity: 1.5 }));
  dish.rotation.x = -Math.PI / 2; dish.position.y = 0.6; head.add(dish);
  const glass = new THREE.Mesh(new THREE.CircleGeometry(DR * 0.97, 64), new THREE.MeshPhysicalMaterial({ map: ribTex, transparent: true, opacity: 0.4, metalness: 0.1, roughness: 0.15, clearcoat: 1, envMapIntensity: 0.7, side: THREE.DoubleSide }));
  glass.rotation.x = -Math.PI / 2; glass.position.y = 0.84; head.add(glass);
  for (const rz of [0, Math.PI / 2]) {   // the cross frame over the glass, and its hub
    const bar = new THREE.Mesh(new THREE.BoxGeometry(DR * 1.96, 0.1, 0.16), steel); bar.position.y = 0.9; bar.rotation.y = rz; head.add(bar);
  }
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.14, 24), steel); hub.position.y = 0.92; head.add(hub);
  const LENS_R = DR * 0.9;   // the beam leaves as wide as the glass
  const lensMat = new THREE.MeshBasicMaterial({ color: "#FFFFFF", transparent: true, opacity: 0 });
  const lens = new THREE.Mesh(new THREE.CircleGeometry(DR * 0.6, 48), lensMat); lens.rotation.x = -Math.PI / 2; lens.position.y = 0.7; head.add(lens);
  const lensGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: softTex, color: "#DFFBFF", transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }));
  lensGlow.scale.set(6, 6, 1); lensGlow.position.y = 1.2; head.add(lensGlow);
  const lamp = new THREE.PointLight("#06E4F9", 0, 18, 2); lamp.position.y = 1.6; head.add(lamp);

  // ---- the beam, in the head's frame: a soft core cone of unit length (scaled to the throw each frame)
  const coneGeo = new THREE.CylinderGeometry(1, LENS_R, 1, 48, 1, true); coneGeo.translate(0, 0.5, 0);
  const coneMat = new THREE.ShaderMaterial({
    uniforms: { ...U, spread: { value: 9 }, glare: { value: 1 } }, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    vertexShader: "uniform float spread; varying vec2 vUv; varying vec3 vN; varying vec3 vV; void main(){ vUv=uv; vec3 p=position; p.xz*=mix(1.0,spread,uv.y); vN=normalize(normalMatrix*normal); vec4 mv=modelViewMatrix*vec4(p,1.0); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }",
    fragmentShader: `uniform float intensity; uniform float time; uniform float glare; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ float rim=pow(abs(dot(vN,vV)),1.2); float along=1.0-vUv.y;
        float dust=0.85+0.15*sin(vUv.y*52.0-time*6.0)*sin(vUv.x*18.0+time*2.0);
        float a=intensity*glare*(0.008+0.11*along*along*along*along)*rim*dust; gl_FragColor=vec4(0.30,0.80,0.98,a); }`,
  });
  const cone = new THREE.Mesh(coneGeo, coneMat); cone.position.y = 0.9; cone.frustumCulled = false; head.add(cone);
  // the haze: billboarded puffs along the beam, small and bright by the lens, wide and faint far out
  const PUFFS = 34, puffs = [];
  for (let i = 0; i < PUFFS; i++) {
    const p = new THREE.Sprite(new THREE.SpriteMaterial({ map: softTex, color: new THREE.Color().lerpColors(new THREE.Color("#DFFBFF"), CYAN, i / PUFFS), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }));
    scene.add(p); puffs.push(p);
  }
  // particles riding the beam, placed on the GPU in the head's frame
  const N = 16000, pGeo = new THREE.BufferGeometry();
  const at = new Float32Array(N), ang = new Float32Array(N), rad = new Float32Array(N), spd = new Float32Array(N), sz = new Float32Array(N);
  for (let i = 0; i < N; i++) { at[i] = Math.random(); ang[i] = rnd(0, 6.283); rad[i] = Math.pow(Math.random(), 0.5); spd[i] = rnd(0.4, 1.2); sz[i] = rnd(0.35, 1.0); }
  pGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N * 3), 3));
  pGeo.setAttribute("aT", new THREE.BufferAttribute(at, 1)); pGeo.setAttribute("aA", new THREE.BufferAttribute(ang, 1));
  pGeo.setAttribute("aR", new THREE.BufferAttribute(rad, 1)); pGeo.setAttribute("aS", new THREE.BufferAttribute(spd, 1)); pGeo.setAttribute("aZ", new THREE.BufferAttribute(sz, 1));
  const pMat = new THREE.ShaderMaterial({
    uniforms: { ...U, len: { value: 80 }, r0: { value: LENS_R }, spread: { value: 9 }, dpr: { value: renderer.getPixelRatio() } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform float time; uniform float len; uniform float r0; uniform float spread; uniform float dpr;
      attribute float aT; attribute float aA; attribute float aR; attribute float aS; attribute float aZ; varying float vA;
      void main(){ float t=fract(aT+time*0.06*aS); float w=r0*mix(1.0,spread,t); vec3 p=vec3(cos(aA)*aR*w, 0.9+t*len, sin(aA)*aR*w);
        vec4 mv=modelViewMatrix*vec4(p,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=aZ*dpr*(58.0/-mv.z);
        vA=(0.35+0.65*(1.0-aR))*(0.6+0.4*sin(time*2.0+aA*5.0))*pow(1.0-t,1.4)*0.55; }`,
    fragmentShader: `uniform float intensity; varying float vA; void main(){ vec2 c=gl_PointCoord-0.5; float d=length(c); if(d>0.5) discard; gl_FragColor=vec4(0.10,0.85,0.98,intensity*vA*smoothstep(0.5,0.12,d)); }`,
  });
  const pts = new THREE.Points(pGeo, pMat); pts.frustumCulled = false; head.add(pts);

  // ---- the cloud deck: TRM's dotted contour bands laid flat across the sky, faint until the beam lands on them
  const deckPts = [];
  for (let k = 0; k < 120; k++) {
    const z0 = -150 + k * 1.22, ph = k * 1.7, ph2 = k * 0.6;
    const fade = 1 - Math.abs(k / 120 - 0.5) * 1.2;
    for (let x = -150; x < 150; x += 0.4) {
      if (Math.random() > 0.3 + 0.7 * fade * (0.5 + 0.5 * Math.pow(Math.sin(x * 0.021 + ph), 2))) continue;
      const z = z0 + 7 * Math.sin(x * 0.05 + ph) + 2.5 * Math.sin(x * 0.13 + ph2) + rnd(-0.4, 0.4);
      deckPts.push(x + rnd(-0.2, 0.2), CLOUD_Y - 0.4 + rnd(-0.3, 0.3), z);
    }
  }
  const deckGeo = new THREE.BufferGeometry(); deckGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(deckPts), 3));
  const deckU = { disc: { value: new THREE.Vector3(0, CLOUD_Y, -60) }, discR: { value: 15 }, lit: { value: 0 }, dpr: { value: renderer.getPixelRatio() }, time: U.time };
  const deckMat = new THREE.ShaderMaterial({
    uniforms: deckU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform vec3 disc; uniform float discR; uniform float lit; uniform float dpr; uniform float time; varying float vA;
      void main(){ float d=distance(position.xz,disc.xz); float l=lit*smoothstep(discR*1.15,discR*0.35,d);
        vec4 mv=modelViewMatrix*vec4(position,1.0); gl_Position=projectionMatrix*mv; gl_PointSize=dpr*(2.4+1.6*l)*(70.0/-mv.z);
        vA=0.30+0.06*sin(time*0.7+position.x*0.1)+1.0*l; }`,
    fragmentShader: `varying float vA; void main(){ vec2 c=gl_PointCoord-0.5; float d=length(c); if(d>0.5) discard; gl_FragColor=vec4(0.10,0.85,0.98,vA*smoothstep(0.5,0.2,d)); }`,
  });
  const deck = new THREE.Points(deckGeo, deckMat); deck.frustumCulled = false; scene.add(deck);

  // ---- the disc on the cloud deck, lying flat on it so it foreshortens; a faint wash, the dots, the mark
  const discGroup = new THREE.Group(); discGroup.rotation.x = Math.PI / 2; scene.add(discGroup);
  const DISC_R = 15, DU = { intensity: { value: 0 } };
  discGroup.add(new THREE.Mesh(new THREE.CircleGeometry(DISC_R, 64), new THREE.ShaderMaterial({
    uniforms: DU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `uniform float intensity; varying vec2 vUv; void main(){ float d=length(vUv-0.5)*2.0; float a=intensity*(0.03+0.02*smoothstep(0.55,0.95,d))*smoothstep(1.0,0.8,d); gl_FragColor=vec4(0.30,0.80,0.98,a); }`,
  })));
  const RIM = 220, rimGeo = new THREE.BufferGeometry(), rimPos = new Float32Array(RIM * 3);
  rimGeo.setAttribute("position", new THREE.BufferAttribute(rimPos, 3));
  const rimMat = new THREE.PointsMaterial({ color: CYAN, size: 0.5, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
  discGroup.add(new THREE.Points(rimGeo, rimMat));
  const mk = document.createElement("canvas"); mk.width = 600; mk.height = 600; const mg = mk.getContext("2d");
  const path = new Path2D(host.dataset.mark || "");
  mg.fillStyle = "#fff"; mg.fill(path);
  let bx0 = 600, by0 = 600, bx1 = 0, by1 = 0;
  { const d = mg.getImageData(0, 0, 600, 600).data; for (let y = 0; y < 600; y++) for (let x = 0; x < 600; x++) if (d[(y * 600 + x) * 4 + 3] > 10) { bx0 = Math.min(bx0, x); by0 = Math.min(by0, y); bx1 = Math.max(bx1, x); by1 = Math.max(by1, y); } }
  const bw = bx1 - bx0, bh = by1 - by0, S = 440 / Math.max(bw, bh);
  mg.clearRect(0, 0, 600, 600); mg.save(); mg.translate(300 - (bx0 + bw / 2) * S, 300 - (by0 + bh / 2) * S); mg.scale(S, S); mg.fillStyle = "#fff"; mg.fill(path); mg.restore();
  const targets = [];
  { const d = mg.getImageData(0, 0, 600, 600).data; for (let y = 0; y < 600; y += 9) for (let x = 0; x < 600; x += 9) if (d[(y * 600 + x) * 4 + 3] > 120) targets.push([(x - 300) / 300, -(y - 300) / 300]); }
  const M = targets.length, mGeo = new THREE.BufferGeometry(), mPos = new Float32Array(M * 3), mStart = targets.map(() => [rnd(-1.8, 1.8), rnd(-1.8, 1.8)]);
  mGeo.setAttribute("position", new THREE.BufferAttribute(mPos, 3));
  const mMat = new THREE.PointsMaterial({ color: "#F7F7F7", size: 0.42, transparent: true, opacity: 0, depthWrite: false, fog: false });
  const markGroup = new THREE.Group(); markGroup.rotation.x = Math.PI / 2; scene.add(markGroup);
  markGroup.add(new THREE.Points(mGeo, mMat));
  const MR = DISC_R * 0.56;
  const markMesh = new THREE.Mesh(new THREE.PlaneGeometry(MR * 2 * 600 / 440, MR * 2 * 600 / 440), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(mk), transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide, fog: false }));
  markMesh.position.z = -0.3; markGroup.add(markMesh);

  // ---- what the beam passes: pale shapes caught in the light, a flock in the air and two figures on the cloud
  const silTex = (draw) => { const c = document.createElement("canvas"); c.width = 256; c.height = 256; const g = c.getContext("2d"); g.fillStyle = "#BFF3FA"; g.strokeStyle = "#BFF3FA"; draw(g); return new THREE.CanvasTexture(c); };
  const birdTex = silTex((g) => { g.lineWidth = 14; g.lineCap = "round"; g.beginPath(); g.moveTo(20, 150); g.quadraticCurveTo(80, 70, 128, 130); g.quadraticCurveTo(176, 70, 236, 150); g.stroke(); });
  const figureTex = silTex((g) => { g.beginPath(); g.arc(128, 70, 34, 0, 7); g.fill(); g.beginPath(); g.moveTo(60, 250); g.quadraticCurveTo(64, 120, 128, 108); g.quadraticCurveTo(192, 120, 196, 250); g.closePath(); g.fill(); g.beginPath(); g.moveTo(96, 86); g.quadraticCurveTo(128, 20, 160, 86); g.quadraticCurveTo(128, 60, 96, 86); g.fill(); });
  const things = [], flock = [];
  const thing = (tex, x, y, z, w, h, v) => { const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false })); sp.position.set(x, y, z); sp.scale.set(w, h, 1); sp.userData.v = v || 0; scene.add(sp); things.push(sp); return sp; };

  // ---- what the light finds: threat symbols drawn as dots on the deck, lit only when the beam is on them
  const PINK = new THREE.Color("#FA9EBD");
  const icon = (draw) => {   // a 160 px drawing, sampled into dot positions
    const c = document.createElement("canvas"); c.width = c.height = 160; const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.strokeStyle = "#fff"; g.lineCap = "round"; g.lineJoin = "round"; draw(g);
    const d = g.getImageData(0, 0, 160, 160).data, pts = [];
    for (let y = 2; y < 160; y += 4) for (let x = 2; x < 160; x += 4) if (d[(y * 160 + x) * 4 + 3] > 120) pts.push([(x - 80) / 80 + (Math.random() - 0.5) * 0.02, (y - 80) / 80 + (Math.random() - 0.5) * 0.02]);
    return pts;
  };
  const ICONS = {
    hood: icon((g) => { g.beginPath(); g.arc(80, 52, 22, 0, 7); g.fill(); g.beginPath(); g.moveTo(38, 150); g.quadraticCurveTo(42, 78, 80, 72); g.quadraticCurveTo(118, 78, 122, 150); g.closePath(); g.fill(); g.beginPath(); g.moveTo(58, 60); g.quadraticCurveTo(80, 10, 102, 60); g.quadraticCurveTo(80, 44, 58, 60); g.fill(); }),
    wallet: icon((g) => { g.lineWidth = 10; g.strokeRect(22, 46, 116, 76); g.fillRect(96, 70, 42, 30); g.lineWidth = 8; g.beginPath(); g.moveTo(30, 46); g.lineTo(110, 28); g.lineTo(116, 46); g.stroke(); }),
    coin: icon((g) => { g.lineWidth = 10; g.beginPath(); g.arc(80, 80, 56, 0, 7); g.stroke(); g.lineWidth = 9; g.beginPath(); g.moveTo(80, 36); g.lineTo(80, 124); g.stroke(); g.beginPath(); g.moveTo(62, 56); g.lineTo(96, 56); g.quadraticCurveTo(116, 56, 116, 72); g.quadraticCurveTo(116, 86, 96, 86); g.lineTo(62, 86); g.moveTo(96, 86); g.quadraticCurveTo(120, 86, 120, 104); g.quadraticCurveTo(120, 120, 96, 120); g.lineTo(62, 120); g.stroke(); }),
    lock: icon((g) => { g.lineWidth = 10; g.beginPath(); g.arc(80, 62, 28, Math.PI, 0); g.stroke(); g.fillRect(36, 70, 88, 64); }),
    chain: icon((g) => { g.lineWidth = 11; for (const [x, y] of [[52, 56], [108, 104]]) { g.beginPath(); g.ellipse(x, y, 34, 22, Math.PI / 4, 0, 7); g.stroke(); } }),
    heart: icon((g) => { g.lineWidth = 9; g.beginPath(); g.moveTo(20, 40); g.lineTo(140, 40); g.lineTo(140, 108); g.lineTo(70, 108); g.lineTo(44, 132); g.lineTo(44, 108); g.lineTo(20, 108); g.closePath(); g.stroke(); g.beginPath(); g.moveTo(80, 96); g.bezierCurveTo(50, 70, 62, 48, 80, 64); g.bezierCurveTo(98, 48, 110, 70, 80, 96); g.fill(); }),
    network: icon((g) => { const n = [[80, 80], [30, 40], [130, 36], [40, 126], [126, 122], [80, 20]]; g.lineWidth = 6; for (let k = 1; k < n.length; k++) { g.beginPath(); g.moveTo(n[0][0], n[0][1]); g.lineTo(n[k][0], n[k][1]); g.stroke(); } for (const [x, y] of n) { g.beginPath(); g.arc(x, y, 12, 0, 7); g.fill(); } }),
    skull: icon((g) => { g.beginPath(); g.arc(80, 70, 44, 0, 7); g.fill(); g.fillRect(52, 100, 56, 26); g.fillStyle = "#000"; g.beginPath(); g.arc(62, 70, 12, 0, 7); g.arc(98, 70, 12, 0, 7); g.fill(); g.fillRect(74, 86, 12, 14); }),
  };
  // where they sit on the deck, around the home spot: offsets in x and z
  const SYMBOLS = [["hood", -40, 4], ["wallet", -24, 28], ["coin", 32, -12], ["lock", 46, 16], ["chain", -14, -34], ["heart", 24, 32], ["network", -56, 34], ["skull", 58, -34], ["hood", 60, 36], ["wallet", -66, -14], ["chain", 20, -40], ["coin", -6, 40]];
  const symbols = [];
  for (const [name, dx, dz] of SYMBOLS) {
    const pts = ICONS[name], geo = new THREE.BufferGeometry(), arr = new Float32Array(pts.length * 3), SR = DISC_R * 0.62;
    pts.forEach(([x, y], k) => { arr[k * 3] = x * SR; arr[k * 3 + 1] = y * SR; arr[k * 3 + 2] = -0.3; });
    geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    const mat = new THREE.PointsMaterial({ color: PINK, size: 0.72, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
    const grp = new THREE.Group(); grp.rotation.x = Math.PI / 2; grp.add(new THREE.Points(geo, mat)); scene.add(grp);
    symbols.push({ grp, mat, dx, dz });
  }
  const placeSymbols = () => { for (const sy of symbols) sy.grp.position.set(TARGET.x + sy.dx, CLOUD_Y - 0.5, TARGET.z + sy.dz); markGroup.position.set(TARGET.x, CLOUD_Y - 0.5, TARGET.z); };

  // ---- aiming. The lock target is the point on the cloud deck that sits top-centre of the frame, found by
  // casting the camera's own ray through that spot; the fixture pans and tilts to hit it.
  const lensWorld = new THREE.Vector3(), beamDir = new THREE.Vector3(), hit = new THREE.Vector3();
  let TARGET = new THREE.Vector3(0, CLOUD_Y, -60);
  function findTarget() {
    const ndc = new THREE.Vector3(0, 0.46, 0.5).unproject(camera); const d = ndc.sub(camera.position).normalize();
    const t = (CLOUD_Y - camera.position.y) / d.y; TARGET = camera.position.clone().add(d.multiplyScalar(t));
  }
  const sweep = (t) => ({ pan: 0.55 * Math.sin(t * 0.8) + 0.12 * Math.sin(t * 2.5), tilt: 0.16 * Math.sin(t * 1.3 + 1.0) });
  function aim(pan, tilt) {
    yoke.rotation.y = pan; head.rotation.x = tilt; head.updateMatrixWorld(true);
    lens.getWorldPosition(lensWorld); beamDir.set(0, 1, 0).applyQuaternion(head.getWorldQuaternion(new THREE.Quaternion()));
    const up = beamDir.y > 0.3; const len = up ? (CLOUD_Y - lensWorld.y) / beamDir.y : 55;   // not pointing at the deck: just a throw into the night
    hit.copy(lensWorld).addScaledVector(beamDir, len); return len;
  }
  function anglesFor(target) {
    // pan and tilt that point the head at a world point (the head pivot is what turns, so solve from the pivot)
    const pivot = new THREE.Vector3(); head.getWorldPosition(pivot);
    const d = target.clone().sub(pivot).normalize();
    return { pan: Math.atan2(d.x, d.z), tilt: Math.atan2(Math.hypot(d.x, d.z), d.y) };
  }
  let LOCK = { pan: 0, tilt: 0.5 }, VIEW = { pan: 0, tilt: 1.8 };
  function setup() {
    findTarget(); yoke.rotation.y = 0; head.rotation.x = 0; head.updateMatrixWorld(true); LOCK = anglesFor(TARGET); VIEW = anglesFor(new THREE.Vector3(-42, 10, -6)); placeSymbols();
    // figures where the beam will pass on the cloud at two moments of the search
    for (const [t, dx, w] of [[2.0, -2, 6], [3.3, 3, 7]]) { const sw = sweep(t); aim(LOCK.pan + sw.pan, LOCK.tilt + sw.tilt); thing(figureTex, hit.x + dx, CLOUD_Y - 0.6, hit.z + 2, w, w, 0); }
    for (let i = 0; i < 8; i++) { const b = thing(birdTex, rnd(-50, -10) - i * 7, rnd(18, 34), rnd(-48, -22), rnd(1.8, 3.2), rnd(1.1, 2.0), rnd(7, 12)); b.userData.ph = rnd(0, 6.3); flock.push(b); }
  }

  // ---- time: dark; the lamp stutters on while already sweeping; it searches; it locks; the mark gathers
  function flicker(s) {
    if (still) return 1;
    if (s < 0.5) return 0;
    if (s < 1.7) { const k = (s - 0.5) / 1.2; const burst = Math.sin(s * 47) * Math.sin(s * 23) > 0.15 ? 1 : 0.08; return Math.min(1, burst * (0.4 + 0.6 * k)); }
    return 0.97 + 0.03 * Math.sin(s * 31) * Math.sin(s * 17);
  }
  let t0 = performance.now(), px = 0, py = 0, tx = 0, ty = 0, lastMove = -1e9, pointerIn = false, armed = false;
  // the pointer steers the light only once it has passed over the fixture itself; a pointer that just crosses
  // the sky leaves the beam alone. Leaving the scene, or resting long enough for the beam to drift home, disarms it.
  const caster = new THREE.Raycaster(), ndc = new THREE.Vector2();
  host.addEventListener("pointermove", (e) => {
    const b = host.getBoundingClientRect(); tx = ((e.clientX - b.left) / b.width - 0.5) * 2; ty = ((e.clientY - b.top) / b.height - 0.5) * 2; lastMove = performance.now(); pointerIn = true;
    // only the metal counts: the beam cone, its particles and the lens glow are children of the head too
    if (!armed) { ndc.set(tx, -ty); caster.setFromCamera(ndc, camera); armed = caster.intersectObject(fixture, true).some((h) => h.object !== cone && h.object !== pts && h.object !== lensGlow); }
  });
  host.addEventListener("pointerleave", () => { pointerIn = false; armed = false; });
  // the deck point under the pointer: the camera's ray through it, onto the cloud
  const pointerHit = new THREE.Vector3();
  function aimUnderPointer() {
    const v = new THREE.Vector3(tx, -ty, 0.5).unproject(camera); const d = v.sub(camera.position).normalize();
    if (d.y < 0.08) return false;
    const t = (CLOUD_Y - camera.position.y) / d.y; pointerHit.copy(camera.position).addScaledVector(d, t);
    pointerHit.x = Math.max(TARGET.x - 70, Math.min(TARGET.x + 70, pointerHit.x)); pointerHit.z = Math.max(TARGET.z - 50, Math.min(TARGET.z + 42, pointerHit.z));
    return true;
  }
  let curPan = 0, curTilt = 0, steer = 0;
  function resize() {
    const b = host.getBoundingClientRect(); renderer.setSize(b.width, b.height, false); camera.aspect = b.width / b.height; camera.updateProjectionMatrix();
    pMat.uniforms.dpr.value = renderer.getPixelRatio(); findTarget(); yoke.rotation.y = 0; head.rotation.x = 0; head.updateMatrixWorld(true); LOCK = anglesFor(TARGET); VIEW = anglesFor(new THREE.Vector3(-42, 10, -6)); placeSymbols();
  }
  function frame(now) {
    const s = still ? 9 : (now - t0) / 1000;
    const I = flicker(s), turn = ease((s - 2.2) / 2.0), lock = ease((s - 6.0) / 1.3), on = ease((s - 7.3) / 0.6), gather = ease((s - 7.4) / 1.5), solid = ease((s - 9.0) / 0.8);
    U.time.value = s; U.intensity.value = I;
    // it wakes up looking at you, then turns to the sky and searches, then locks
    const sw = sweep(s - 2.2);
    const sp = LOCK.pan + sw.pan * (1 - lock) + 0.012 * Math.sin(s * 0.7) * lock, st = LOCK.tilt + sw.tilt * (1 - lock) + 0.008 * Math.sin(s * 0.9 + 2.0) * lock;
    let wantPan = VIEW.pan + (sp - VIEW.pan) * turn, wantTilt = VIEW.tilt + (st - VIEW.tilt) * turn;
    // after the lock, the pointer steers the light; still for a moment, or gone, and it drifts home
    if (armed && performance.now() - lastMove > 4000) armed = false;
    const active = !still && lock >= 1 && pointerIn && armed && performance.now() - lastMove < 1400 && aimUnderPointer();
    steer += ((active ? 1 : 0) - steer) * 0.05;
    if (lock >= 1) { const a = anglesFor(pointerHit); wantPan = wantPan + (a.pan - wantPan) * steer; wantTilt = wantTilt + (a.tilt - wantTilt) * steer; }
    if (lock < 1) { curPan = wantPan; curTilt = wantTilt; } else { curPan += (wantPan - curPan) * 0.07; curTilt += (wantTilt - curTilt) * 0.07; }
    const len = aim(curPan, curTilt);
    cone.scale.y = len; pMat.uniforms.len.value = len;
    // facing the viewer: the lens flares and the beam itself dims, like looking into the light
    const toCam = camera.position.clone().sub(lensWorld).normalize(); const facing = Math.pow(Math.max(0, beamDir.dot(toCam)), 3);
    const glareK = 1 - 0.75 * facing; coneMat.uniforms.glare.value = glareK;
    lensGlow.scale.setScalar(4 + 26 * facing); DU.intensity.value = I * (beamDir.y > 0.3 ? 1 : 0) * (1 - facing);
    // the haze puffs sit along the beam in world space, growing with the throw
    for (let i = 0; i < PUFFS; i++) {
      const f = (i + 0.5) / PUFFS, p = puffs[i];
      p.position.copy(lensWorld).addScaledVector(beamDir, f * len);
      const w = (LENS_R * 2.2 + f * len * 0.26) * (1 + 0.06 * Math.sin(s * 3 + i));
      p.scale.set(w * 1.3, w * 1.3, 1); p.material.opacity = I * glareK * (0.05 * Math.pow(1 - f, 2.6) + 0.004);
    }
    discGroup.position.copy(hit); discGroup.position.y = CLOUD_Y - 0.5;
    for (const sy of symbols) { const d = Math.hypot(hit.x - sy.grp.position.x, hit.z - sy.grp.position.z); sy.mat.opacity = Math.min(1, 1.3 * DU.intensity.value * Math.max(0, 1 - Math.max(0, d - DISC_R * 0.4) / (DISC_R * 0.8))); sy.grp.position.y = CLOUD_Y - 0.5 + 0.15 * Math.sin(s * 2 + sy.dx); }
    const homeD = Math.hypot(hit.x - TARGET.x, hit.z - TARGET.z), home = Math.max(0, Math.min(1, 1 - (homeD - DISC_R * 0.25) / (DISC_R * 0.6)));
    for (const b of flock) { b.position.x += b.userData.v * 0.016; b.position.y += Math.sin(s * 2.2 + b.userData.ph) * 0.015; if (b.position.x > 60) b.position.x = -70; b.scale.y = Math.abs(b.scale.y) * (Math.sin(s * 9 + b.userData.ph) > 0 ? 1 : 0.75); }
    // anything near the beam lights up: distance from the beam line, not just the disc
    const tmp = new THREE.Vector3();
    for (const t of things) {
      tmp.copy(t.position).sub(lensWorld); const along = Math.max(0, Math.min(len, tmp.dot(beamDir)));
      const radial = tmp.addScaledVector(beamDir, -along).length(); const w = LENS_R * (1 + 8 * along / len) * 1.1;
      t.material.opacity = 0.8 * I * Math.max(0, 1 - radial / w);
    }
    for (const c of clouds) { c.position.x += c.userData.v * 0.016; if (c.position.x > 130) c.position.x = -130; if (c.position.x < -130) c.position.x = 130; c.material.opacity = 0.05 + 0.06 * I; }
    for (let i = 0; i < RIM; i++) { const a = (i / RIM) * 6.283 + s * 0.05, r = DISC_R * (0.97 + 0.03 * Math.sin(a * 12)); rimPos[i * 3] = Math.cos(a) * r; rimPos[i * 3 + 1] = Math.sin(a) * r; rimPos[i * 3 + 2] = -0.2; }
    rimGeo.attributes.position.needsUpdate = true; rimMat.opacity = 0.0; deckU.disc.value.copy(hit); deckU.discR.value = DISC_R; deckU.lit.value = DU.intensity.value;
    const g2 = gather * home, s2 = solid * home;
    for (let i = 0; i < M; i++) { const [sx, sy] = mStart[i], [ex, ey] = targets[i]; mPos[i * 3] = (sx * (1 - g2) + ex * g2) * MR; mPos[i * 3 + 1] = (sy * (1 - g2) + ey * g2) * MR; mPos[i * 3 + 2] = -0.4; }
    mGeo.attributes.position.needsUpdate = true; mMat.opacity = on * home * (1 - s2) * DU.intensity.value; markMesh.material.opacity = s2 * DU.intensity.value;
    lensMat.opacity = 0.95 * I; lensGlow.material.opacity = (0.6 + 0.35 * facing) * I; lamp.intensity = 14 * I;
    px += (tx - px) * 0.05; py += (ty - py) * 0.05;
    camera.position.x = px * 1.2; camera.position.y = 1.5 - py * 0.6; camera.lookAt(LOOK.x + px * 2, LOOK.y, LOOK.z);
    if (copy) copy.style.opacity = still ? 1 : ease((s - 7.8) / 0.9);
    renderer.render(scene, camera);
    if (!still) requestAnimationFrame(frame);
  }
  resize(); setup(); new ResizeObserver(resize).observe(host);
  const start = () => { t0 = performance.now(); if (still) frame(0); else requestAnimationFrame(frame); };
  start();
  host.querySelector(".trm-signal-replay")?.addEventListener("click", start);
})();
