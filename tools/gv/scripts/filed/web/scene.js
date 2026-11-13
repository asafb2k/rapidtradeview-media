// FILED. by RapidTradeView: the episode scene. Three.js (MIT) for the 3D world (monolith, flip, sink, stamp) with
// bloom and grain on the world only; a 2D canvas on top for the real site card (flat, untouched while held), text,
// captions and the brand mark. Everything is a pure function of t: window.renderFrame(t) draws one frame.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const R = await (await fetch("/run/render.json")).json();
const W = R.W, H = R.H, T = R.T, DUR = R.duration, FPS = R.fps;
const C = { violet0: "#0B0714", violet1: "#1A0F2E", red: "#F43F5E", cyan: "#3BE8FF", white: "#FFFFFF" };
const SAFE = [60, 200, 920, 1500];

// ---------------------------------------------------------------------------------------------- math
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, k) => a + (b - a) * k;
const prog = (t, a, b) => clamp((t - a) / (b - a));
const smooth = x => x * x * (3 - 2 * x);
const easeInOut = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
const easeOut = x => 1 - Math.pow(1 - x, 3);
const easeIn = x => x * x * x;
const easeOutBack = (x, s = 1.7) => { x -= 1; return 1 + (s + 1) * x * x * x + s * x * x; };
const ph = t => ((t % DUR) + DUR) % DUR;     // loop phase
const LOOP_END = T.end - 0.1;                 // the return lands 3 frames early, so the last frames are frame 0

// ---------------------------------------------------------------------------------------------- loading
const loadImg = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("img " + src)); i.src = src; });
const [imgFace, imgDepth, imgCard, imgHold] = await Promise.all([R.assets.face, R.assets.depth, R.assets.card, R.assets.card_hold].map(loadImg));
await Promise.all(['400 100px "Archivo Black"', '900 100px InterV', '800 100px InterV', '600 100px InterV', '800 100px JBMono'].map(f => document.fonts.load(f)));

// ---------------------------------------------------------------------------------------------- brand mark tile
function makeMark(size) {
  const cv = document.createElement("canvas"); cv.width = cv.height = size;
  const g = cv.getContext("2d"); const k = size / R.mark.viewBox;
  g.scale(k, k);
  const r = R.mark.tileRadius * 1024;
  const bg = g.createLinearGradient(R.mark.bg.x1, R.mark.bg.y1, R.mark.bg.x2, R.mark.bg.y2);
  for (const s of R.mark.bg.stops) bg.addColorStop(s.offset, s.color);
  g.fillStyle = bg; g.beginPath(); g.roundRect(0, 0, 1024, 1024, r); g.fill();
  const b = R.mark.bbox;
  const mg = g.createLinearGradient(b.x, b.y + b.h, b.x + b.w, b.y);
  const ms = R.mark.mark.stops; for (const s of ms) mg.addColorStop(s.offset, s.color);
  g.fillStyle = mg; g.fill(new Path2D(R.mark.path), "evenodd");
  return cv;
}
const MARK = makeMark(256);

// ---------------------------------------------------------------------------------------------- three: renderer
const glc = document.getElementById("gl");
const renderer = new THREE.WebGLRenderer({ canvas: glc, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NoToneMapping;   // no tone curve: the portrait and the card keep their own colours
renderer.localClippingEnabled = true;
const dbg = renderer.getContext().getExtension("WEBGL_debug_renderer_info");
window.glRenderer = dbg ? renderer.getContext().getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "?";

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 600);
scene.fog = new THREE.FogExp2(0x0d0819, 0.012);

// sky: a violet void, a faint horizon glow
const sky = new THREE.Mesh(new THREE.SphereGeometry(400, 32, 16), new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: {},
  vertexShader: `varying vec3 vd; void main(){ vd = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec3 vd; void main(){ float y = vd.y;
    vec3 top = vec3(0.012,0.006,0.03); vec3 hor = vec3(0.10,0.045,0.20); vec3 low = vec3(0.02,0.012,0.05);
    vec3 c = y > 0.0 ? mix(hor, top, smoothstep(0.0, 0.55, y)) : mix(hor, low, smoothstep(0.0, 0.3, -y));
    c += vec3(0.05,0.02,0.10) * exp(-abs(y)*14.0);
    gl_FragColor = vec4(c,1.0);
    #include <colorspace_fragment>
  }`
}));
scene.add(sky);

const SW = 9.6, SH = SW / R.slab_aspect, SD = 1.4, FLOOR = -SH / 2;

// floor: a cyan perspective grid fading into the void
const floor = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.ShaderMaterial({
  transparent: false, fog: false, uniforms: { glow: { value: 1.0 } },
  vertexShader: `varying vec3 wp; void main(){ vec4 w = modelMatrix*vec4(position,1.0); wp = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }`,
  fragmentShader: `varying vec3 wp; uniform float glow;
    float line(float v, float w){ float d = abs(fract(v - 0.5) - 0.5) / fwidth(v); return 1.0 - clamp(d / w, 0.0, 1.0); }
    void main(){
      vec2 g = wp.xz / 1.2;
      float l = max(line(g.x, 1.0), line(g.y, 1.0));
      float dist = length(wp.xz - vec2(0.0, 4.0));
      float fade = exp(-dist * 0.035);
      vec3 base = vec3(0.016, 0.010, 0.035);
      vec3 col = base + vec3(0.12, 0.75, 0.95) * l * 0.55 * fade * glow;
      col += vec3(0.20, 0.08, 0.40) * exp(-dist * 0.09) * 0.35;
      vec3 fogc = vec3(0.05,0.025,0.10);
      col = mix(fogc, col, exp(-dist*0.012));
      gl_FragColor = vec4(col, 1.0);
      #include <colorspace_fragment>
    }`
}));
floor.rotation.x = -Math.PI / 2; floor.position.y = FLOOR; scene.add(floor);

// lights
scene.add(new THREE.AmbientLight(0x6040a0, 0.6));
const kl = new THREE.DirectionalLight(0xffffff, 1.2); kl.position.set(6, 10, 14); scene.add(kl);
const rimC = new THREE.PointLight(0x3be8ff, 60, 40, 1.6); rimC.position.set(-9, 4, -4); scene.add(rimC);
const rimM = new THREE.PointLight(0xb04cff, 60, 40, 1.6); rimM.position.set(9, -2, -3); scene.add(rimM);

// particles: periodic over the episode so the loop joins
const NP = 520;
const pGeo = new THREE.BufferGeometry();
const pBase = new Float32Array(NP * 4), pPos = new Float32Array(NP * 3), pCol = new Float32Array(NP * 3);
{ let s = 12345; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < NP; i++) { pBase[i * 4] = (rnd() - .5) * 46; pBase[i * 4 + 1] = rnd(); pBase[i * 4 + 2] = -30 + rnd() * 40; pBase[i * 4 + 3] = 1 + Math.floor(rnd() * 2);
    if (Math.abs(pBase[i * 4]) < 7.5 && pBase[i * 4 + 2] > -2.0) pBase[i * 4 + 2] = -2.0 - rnd() * 6;   // nothing drifts in front of the portrait
    const c = rnd() < 0.7 ? [0.23, 0.9, 1.0] : [0.7, 0.35, 1.0]; const b = 0.6 + rnd() * 1.6; pCol.set([c[0] * b, c[1] * b, c[2] * b], i * 3); } }
pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3)); pGeo.setAttribute("color", new THREE.BufferAttribute(pCol, 3));
const dot = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d"); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32); gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.35, "rgba(255,255,255,0.5)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); const t = new THREE.CanvasTexture(c); return t; })();
const points = new THREE.Points(pGeo, new THREE.PointsMaterial({ size: 0.16, map: dot, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
scene.add(points);
function updateParticles(t) {
  const u = ph(t) / DUR, Hh = 26;
  for (let i = 0; i < NP; i++) {
    const y = FLOOR + ((pBase[i * 4 + 1] + u * pBase[i * 4 + 3]) % 1) * Hh;
    const x = pBase[i * 4] + 0.4 * Math.sin(2 * Math.PI * (u * 2 + i * 0.37));
    pPos[i * 3] = x; pPos[i * 3 + 1] = y; pPos[i * 3 + 2] = pBase[i * 4 + 2];
  }
  pGeo.attributes.position.needsUpdate = true;
}

// ---------------------------------------------------------------------------------------------- the monolith
function texFrom(img, srgb = true) { const t = new THREE.Texture(img); t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace; t.anisotropy = 8; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter; t.needsUpdate = true; return t; }
const faceTex = texFrom(imgFace), depthTex = texFrom(imgDepth, false);
const faceMat = new THREE.ShaderMaterial({
  uniforms: { img: { value: faceTex }, dep: { value: depthTex }, off: { value: new THREE.Vector2() }, focus: { value: 0.55 }, dim: { value: 0.0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 vUv; uniform sampler2D img, dep; uniform vec2 off; uniform float focus, dim;
    void main(){
      vec2 c = vUv; vec2 s = c;
      for (int i = 0; i < 6; i++) { float d = texture2D(dep, vec2(s.x, s.y)).r; s = c + off * (d - focus); }
      vec4 col = texture2D(img, s);
      vec2 e = min(vUv, 1.0 - vUv); float edge = smoothstep(0.0, 0.035, min(e.x, e.y));
      col.rgb *= mix(0.8, 1.0, edge) * (1.0 - dim);
      gl_FragColor = vec4(col.rgb, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`
});
faceMat.toneMapped = false;
// back face: the real card centred on a dark slab back (the 2D overlay covers the card region exactly while held)
const backCanvas = (() => {
  const cw = imgCard.width, chh = Math.round(cw / R.slab_aspect);
  const c = document.createElement("canvas"); c.width = cw; c.height = chh; const g = c.getContext("2d");
  const gr = g.createLinearGradient(0, 0, 0, chh); gr.addColorStop(0, "#160f28"); gr.addColorStop(1, "#0c0818"); g.fillStyle = gr; g.fillRect(0, 0, cw, chh);
  const y0 = Math.round((chh - imgCard.height) / 2); g.drawImage(imgCard, 0, y0);
  return { canvas: c, y0, h: chh };
})();
const backTex = new THREE.CanvasTexture(backCanvas.canvas); backTex.colorSpace = THREE.SRGBColorSpace; backTex.anisotropy = 8;
const backMat = new THREE.MeshBasicMaterial({ map: backTex, toneMapped: false });
const sideMat = new THREE.MeshStandardMaterial({ color: 0x1b1235, metalness: 0.7, roughness: 0.28, emissive: 0x0a0418 });
const slab = new THREE.Mesh(new THREE.BoxGeometry(SW, SH, SD), [sideMat, sideMat, sideMat, sideMat, faceMat, backMat]);
const slabG = new THREE.Group(); slabG.add(slab); scene.add(slabG);
const edgeMat = new THREE.LineBasicMaterial({ color: new THREE.Color(0.35, 2.2, 2.6), transparent: true, opacity: 0.85 });
const slabEdges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(SW * 1.002, SH * 1.002, SD * 1.002)), edgeMat);
slabG.add(slabEdges);
// a glowing pool on the floor under the slab
const pool = new THREE.Mesh(new THREE.PlaneGeometry(SW * 2.4, SD * 10), new THREE.MeshBasicMaterial({ map: dot, color: new THREE.Color(0.3, 1.2, 1.6), transparent: true, opacity: 0.45, depthWrite: false, blending: THREE.AdditiveBlending }));
pool.rotation.x = -Math.PI / 2; pool.position.y = FLOOR + 0.01; slabG.add(pool);

// ---------------------------------------------------------------------------------------------- the sink
const sinkG = new THREE.Group(); scene.add(sinkG);
const TW = 3.0, TH = 8.0, DROP = TH * Math.min(0.9, R.gap / 100);
const clip = [new THREE.Plane(new THREE.Vector3(0, 1, 0), -FLOOR)];
const towerMat = new THREE.MeshPhysicalMaterial({ color: 0xf43f5e, transparent: true, opacity: 0.62, roughness: 0.12, metalness: 0.0, clearcoat: 1.0, emissive: 0xf43f5e, emissiveIntensity: 0.38, clippingPlanes: clip, side: THREE.DoubleSide, depthWrite: false });
const tower = new THREE.Mesh(new THREE.BoxGeometry(TW, TH, TW), towerMat);
const towerEdge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(TW, TH, TW)), new THREE.LineBasicMaterial({ color: new THREE.Color(3.0, 0.5, 0.8), clippingPlanes: clip }));
const towerG = new THREE.Group(); towerG.add(tower, towerEdge); sinkG.add(towerG);
const ghost = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(TW, TH, TW)), new THREE.LineDashedMaterial({ color: 0xffffff, transparent: true, opacity: 0.4, dashSize: 0.25, gapSize: 0.18 }));
ghost.computeLineDistances(); ghost.position.y = FLOOR + TH / 2; sinkG.add(ghost);
const spyLine = new THREE.Mesh(new THREE.BoxGeometry(16, 0.07, 0.07), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.6, 3.5, 4.2), toneMapped: false }));
spyLine.position.set(0, FLOOR + TH, TW / 2 + 0.2); sinkG.add(spyLine);
const spySheet = new THREE.Mesh(new THREE.PlaneGeometry(16, 14), new THREE.MeshBasicMaterial({ color: 0x3be8ff, transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide }));
spySheet.rotation.x = -Math.PI / 2; spySheet.position.set(0, FLOOR + TH, -4); sinkG.add(spySheet);

// ---------------------------------------------------------------------------------------------- the stamp
const stampCanvas = (() => {
  const c = document.createElement("canvas"); c.width = 1800; c.height = 700; const g = c.getContext("2d");
  g.strokeStyle = "#fff"; g.lineWidth = 34; g.beginPath(); g.roundRect(40, 40, 1720, 620, 70); g.stroke();
  g.fillStyle = "#fff"; g.font = '400 430px "Archivo Black"'; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(R.text.stamp, 900, 380);
  // ink texture: deterministic speckle knocked out of the ink
  g.globalCompositeOperation = "destination-out"; let s = 99; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 2600; i++) { g.globalAlpha = 0.25 + rnd() * 0.6; const r = 1 + rnd() * 5; g.beginPath(); g.arc(rnd() * 1800, rnd() * 700, r, 0, 6.283); g.fill(); }
  g.globalAlpha = 1; g.globalCompositeOperation = "source-over"; return c;
})();
const stampTex = new THREE.CanvasTexture(stampCanvas); stampTex.colorSpace = THREE.SRGBColorSpace; stampTex.anisotropy = 8;
const stampMat = new THREE.MeshBasicMaterial({ map: stampTex, color: new THREE.Color(0.28, 1.25, 1.5), transparent: true, depthWrite: false, toneMapped: false });
const stampW = 10.5, stampH = stampW * 700 / 1800;
const stamp = new THREE.Mesh(new THREE.PlaneGeometry(stampW * 0.86, stampH * 0.86), stampMat);
stamp.rotation.y = Math.PI; slab.add(stamp);
const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.0, 64), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 1.6, 2.0), transparent: true, depthWrite: false, side: THREE.DoubleSide }));
ring.rotation.y = Math.PI; slab.add(ring);

// ---------------------------------------------------------------------------------------------- post: bloom + grain (world only)
const composer = new EffectComposer(renderer);
composer.setPixelRatio(1); composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W / 2, H / 2), 0.85, 0.55, 0.82); composer.addPass(bloom);
const grain = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, seed: { value: 0 }, amount: { value: 0.028 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float seed, amount; varying vec2 vUv;
    float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233)) + seed) * 43758.5453); }
    void main(){ vec4 c = texture2D(tDiffuse, vUv); vec2 v = vUv - 0.5; c.rgb *= 1.0 - dot(v, v) * 0.9;
      c.rgb += (h(vUv * vec2(1080.0, 1920.0)) - 0.5) * amount; gl_FragColor = c; }`
});
composer.addPass(grain);
composer.addPass(new OutputPass());

// ---------------------------------------------------------------------------------------------- camera poses
const tanH = Math.tan(THREE.MathUtils.degToRad(20));
const HOLD = R.card.hold;                      // [x, y, w, h] of the flat card on screen
const PXU = HOLD[2] / SW;                       // px per world unit at the back face while held
const dHold = H / (2 * tanH * PXU);
const holdCY = (HOLD[1] + HOLD[3] / 2 - H / 2) / PXU;   // card centre below screen centre -> camera above
const cardOffY = 0;                             // card is centred on the slab back
const POSE_HOLD = { pos: [0, holdCY + cardOffY, SD / 2 + dHold], look: [0, holdCY + cardOffY, 0], fov: 40 };
function poseHook(t) {                          // frame 0 .. flip: dolly-in 100 -> 108 %, slight orbit, from below
  const k = clamp(t / 2.7);
  const e = 1 - Math.pow(1 - k, 1.6);
  const dist = 33.0 / (1 + 0.08 * e);
  const ang = THREE.MathUtils.degToRad(-4.0 + 3.0 * e);
  const y = -2.6;
  return { pos: [Math.sin(ang) * dist, y, Math.cos(ang) * dist], look: [0, -1.3, 0], fov: 40, orbit: ang };
}
const POSE_SINK0 = { pos: [6.8, FLOOR + 4.6, 23.0], look: [0, FLOOR + 5.35, 0], fov: 40 };
const POSE_SINK1 = { pos: [4.0, FLOOR + 5.0, 20.5], look: [0, FLOOR + 5.3, 0], fov: 40 };
const POSE_END1 = { pos: [0, -1.4, 36.0], look: [0, -0.9, 0], fov: 40 };
const lerpPose = (a, b, k) => ({ pos: a.pos.map((v, i) => lerp(v, b.pos[i], k)), look: a.look.map((v, i) => lerp(v, b.look[i], k)), fov: lerp(a.fov, b.fov, k) });
function applyPose(p, shake = [0, 0]) {
  camera.position.set(p.pos[0], p.pos[1], p.pos[2]); camera.fov = p.fov; camera.updateProjectionMatrix();
  camera.lookAt(p.look[0], p.look[1], p.look[2]);
  if (shake[0] || shake[1]) { camera.rotateZ(shake[0] * 0.004); camera.rotateX(shake[1] * 0.003); }
}

// ---------------------------------------------------------------------------------------------- world state at time t
function phase(t) {
  if (t < T.flip0) return "hook";
  if (t < T.flip1) return "flip";
  if (t < T.lock0) return "hold";
  if (t < T.cut_sink) return "lock";
  if (t < T.cut_row) return "sink";
  if (t < T.end0) return "row";
  if (t < T.loop0) return "end";
  return "loop";
}
function shakeAt(t) {
  let a = 0;
  if (t >= T.hit && t < T.hit + 0.6) a += 22 * Math.exp(-(t - T.hit) * 9);
  if (t >= T.stamp && t < T.stamp + 0.4) a += 9 * Math.exp(-(t - T.stamp) * 12);
  return [a * Math.sin(t * 97.0), a * Math.cos(t * 71.0)];
}
function world(t) {
  updateParticles(t);
  const p = phase(t);
  slabG.visible = ["hook", "flip", "hold", "end", "loop"].includes(p) || (p === "lock" && t < T.lock0 + 0.3);
  sinkG.visible = p === "sink";
  stamp.visible = ring.visible = (p === "end" || p === "loop") && t >= T.stamp - 0.3;
  let pose, rot = 0, orbit = 0;
  if (p === "hook") { pose = poseHook(t); orbit = pose.orbit; }
  else if (p === "flip" || p === "hold") {
    const k = easeInOut(prog(t, T.flip0, T.flip1));
    const a = poseHook(T.flip0);
    pose = lerpPose(a, POSE_HOLD, easeInOut(prog(t, T.flip0 - 0.05, T.flip1)));
    rot = Math.PI * k;
  } else if (p === "sink") {
    pose = lerpPose(POSE_SINK0, POSE_SINK1, easeOut(prog(t, T.cut_sink, T.cut_row)));
  } else if (p === "end") {
    pose = lerpPose(POSE_HOLD, POSE_END1, easeOut(prog(t, T.end0, T.end0 + 1.6)));
    rot = Math.PI;
  } else if (p === "loop") {
    const k = easeInOut(prog(t, T.loop0, LOOP_END));
    pose = lerpPose(POSE_END1, poseHook(0), k); orbit = poseHook(0).orbit * k;
    rot = Math.PI + Math.PI * k;
  } else { pose = POSE_HOLD; rot = Math.PI; }
  slab.rotation.y = rot; slabEdges.rotation.y = rot;
  const w2 = 2 * Math.PI * 2 * ph(t) / DUR;
  faceMat.uniforms.off.value.set(clamp(orbit * 0.12, -0.009, 0.009) + 0.002 * Math.sin(w2), -0.003 + 0.0015 * Math.cos(w2));
  // sink: tower at the SPY level until the hit, then it drops by the captured gap
  if (p === "sink") {
    const d = t < T.hit ? 0 : DROP * (easeIn(prog(t, T.hit, T.hit + 0.16)) - 0.06 * Math.sin(prog(t, T.hit + 0.16, T.hit + 0.5) * Math.PI) * (t > T.hit + 0.16 ? 1 : 0));
    towerG.position.y = FLOOR + TH / 2 - d;
    ghost.material.opacity = t < T.hit ? 0.0 : 0.45 * prog(t, T.hit, T.hit + 0.3);
  }
  // stamp: falls and slams onto the floor in front of the slab
  if (stamp.visible) {
    const k = prog(t, T.stamp - 0.22, T.stamp);
    const lift = (1 - easeIn(k)) * 6.0;
    const fade = p === "loop" ? 1 - smooth(prog(t, T.loop0, T.loop0 + 0.3)) : 1;
    stamp.position.set(0, -0.2, -(SD / 2 + 0.04 + lift)); stamp.scale.setScalar(1 + (1 - easeIn(k)) * 0.7);
    stamp.rotation.z = THREE.MathUtils.degToRad(7 - (1 - k) * 10);
    stampMat.opacity = Math.min(1, k * 3) * fade * 0.97;
    const rk = prog(t, T.stamp, T.stamp + 0.5);
    ring.position.set(0, -0.2, -(SD / 2 + 0.05)); ring.scale.setScalar(2 + rk * 7); ring.material.opacity = t >= T.stamp ? (1 - rk) * 0.8 * fade : 0;
  }
  floor.material.uniforms.glow.value = p === "sink" ? 0.7 : 1.0;
  applyPose(pose, shakeAt(t));
  grain.uniforms.seed.value = (Math.round(ph(t) * FPS) % 97) * 1.37;
  return { pose, p };
}

// ---------------------------------------------------------------------------------------------- 2D overlay
const out = document.getElementById("out"); const ctx = out.getContext("2d");
const acc = document.createElement("canvas"); acc.width = W; acc.height = H; const actx = acc.getContext("2d");
// the card with a soft fade at its cut bottom edge, for the zoomed row shots (never the held card)
const cardFaded = (() => { const c = document.createElement("canvas"); c.width = imgCard.width; c.height = imgCard.height; const g = c.getContext("2d"); g.drawImage(imgCard, 0, 0);
  g.globalCompositeOperation = "destination-out"; const fh = 140; const gr = g.createLinearGradient(0, c.height - fh, 0, c.height); gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, "rgba(0,0,0,1)"); g.fillStyle = gr; g.fillRect(0, c.height - fh, c.width, fh); return c; })();
let TEXTS = [];
function rec(role, x, y, w, h, size) { TEXTS.push({ role, box: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)], size }); }

function textW(s, font, ls = 0) { ctx.font = font; return ctx.measureText(s).width + ls * Math.max(0, s.length - 1); }
function fitFont(lines, family, max, min, width) { for (let s = max; s >= min; s -= 2) { if (lines.every(l => textW(l, `${family.replace("{s}", s)}`) <= width)) return s; } return min; }

function drawKicker(t, p) {
  // kicker at frame 0 above the headline; glides to the top-left corner on the flip; returns on the loop
  const tile = 60, fs = 44, font = `800 ${fs}px InterV`;
  const tw = textW(R.text.wordmark, font);
  const bw = 18 + tile + 14 + tw + 26, bh = tile + 16;
  const cx0 = W / 2 - bw / 2, cy0 = 204;
  const cx1 = 60, cy1 = 204, s1 = 0.84;
  let k = 0;
  if (t >= T.flip0) k = easeInOut(prog(t, T.flip0, T.flip1 + 0.15));
  if (t >= T.loop0) k = 1 - easeInOut(prog(t, T.loop0, LOOP_END));
  const x = lerp(cx0, cx1, k), y = lerp(cy0, cy1, k), s = lerp(1, s1, k);
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  ctx.fillStyle = "rgba(9,5,20,0.78)"; ctx.strokeStyle = "rgba(59,232,255,0.45)"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.roundRect(0, 0, bw, bh, bh / 2); ctx.fill(); ctx.stroke();
  ctx.drawImage(MARK, 18, 8, tile, tile);
  ctx.font = font; ctx.fillStyle = "rgba(255,255,255,0.96)"; ctx.textBaseline = "middle"; ctx.fillText(R.text.wordmark, 18 + tile + 14, bh / 2 + 2);
  ctx.restore();
  rec("kicker", x, y, bw * s, bh * s);
  const markRect = [x + 18 * s, y + 8 * s, tile * s, tile * s];
  // DAY pill next to the corner mark
  const da = (t >= T.flip0 ? prog(t, T.flip1, T.flip1 + 0.25) : 0) * (t >= T.loop0 ? 1 - prog(t, T.loop0, T.loop0 + 0.3) : 1);
  if (da > 0) {
    const f2 = `400 30px "Archivo Black"`; const dw = textW(R.text.day, f2) + 30;
    const dx = x + bw * s + 12, dy = y + (bh * s - 44) / 2;
    ctx.save(); ctx.globalAlpha = da; ctx.fillStyle = "rgba(59,232,255,0.14)"; ctx.strokeStyle = C.cyan; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.roundRect(dx, dy, dw, 44, 22); ctx.fill(); ctx.stroke();
    ctx.font = f2; ctx.fillStyle = C.cyan; ctx.textBaseline = "middle"; ctx.fillText(R.text.day, dx + 15, dy + 24); ctx.restore();
    rec("day", dx, dy, dw, 44);
  }
  return markRect;
}

function headlineAlpha(t) {
  if (t < T.flip0) return 1;
  if (t < T.loop0) return 1 - prog(t, T.flip0 - 0.02, T.flip0 + 0.22);
  return smooth(prog(t, T.loop0 + 0.2, LOOP_END));
}
function drawHeadline(t) {
  const a = headlineAlpha(t); if (a <= 0) return;
  const lines = R.text.headline; const maxW = 750;
  const fs = fitFont(lines, '400 {s}px "Archivo Black"', 112, 64, maxW);
  const font = `400 ${fs}px "Archivo Black"`;
  const y0 = 300 + fs * 0.82;
  const lift = t >= T.flip0 && t < T.loop0 ? -60 * prog(t, T.flip0, T.flip0 + 0.22) : (t >= T.loop0 ? 30 * (1 - a) : 0);
  ctx.save(); ctx.globalAlpha = a; ctx.font = font; ctx.textBaseline = "alphabetic";
  lines.forEach((ln, i) => {
    const y = y0 + i * fs * 1.04 + lift;
    const words = ln.split(" "); const total = textW(ln, font); let x = W / 2 - total / 2;
    for (const wd of words) {
      const ww = textW(wd + " ", font);
      ctx.lineJoin = "round"; ctx.lineWidth = 14; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.strokeText(wd, x, y);
      ctx.fillStyle = wd === R.text.headline_accent ? C.red : C.white; ctx.fillText(wd, x, y); x += ww;
    }
    rec("headline", W / 2 - total / 2, y - fs * 0.78, total, fs * 0.84, fs);
  });
  ctx.restore();
}

function drawCounterHook(t) {
  let a = 1, sc;
  if (t >= T.flip0 && t < T.loop0) a = 1 - prog(t, T.flip0 - 0.02, T.flip0 + 0.2);
  if (t >= T.loop0) a = smooth(prog(t, T.loop0 + 0.25, LOOP_END));
  if (a <= 0) return;
  // settle: 1.12 -> 1.0 over 0.4 s from frame 0 (the end of the loop sits at 1.12 so the replay joins)
  sc = t < T.flip0 ? lerp(1.12, 1.0, easeOut(prog(t, 0, 0.4))) : 1.12;
  if (t >= T.chip && t < T.chip + 0.25) sc *= 1 + 0.07 * Math.sin(prog(t, T.chip, T.chip + 0.25) * Math.PI);
  drawCounter(R.text.counter, R.text.counter_unit, 1405, sc, a, null);
  // ticker chip at ~1.25 s (the second event)
  const ck = t < T.flip0 ? easeOutBack(prog(t, T.chip, T.chip + 0.22)) : 0;
  if (ck > 0 && a > 0) {
    const f = `800 46px JBMono`; const label = R.text.ticker + " · " + R.text.headline[0].split(" ").slice(-1)[0];
    const cw = textW(label, f) + 44, chh = 66, cx = W / 2 - cw / 2, cy = 1168;
    ctx.save(); ctx.globalAlpha = a * clamp(ck * 2); ctx.translate(W / 2, cy + chh / 2); ctx.scale(ck, ck); ctx.translate(-W / 2, -(cy + chh / 2));
    ctx.fillStyle = "rgba(9,5,20,0.82)"; ctx.strokeStyle = C.cyan; ctx.lineWidth = 3; ctx.beginPath(); ctx.roundRect(cx, cy, cw, chh, 14); ctx.fill(); ctx.stroke();
    ctx.font = f; ctx.fillStyle = C.white; ctx.textBaseline = "middle"; ctx.fillText(label, cx + 22, cy + chh / 2 + 2); ctx.restore();
    rec("chip", cx, cy, cw, chh);
  }
}

function drawCounter(num, unit, baseline, sc, a, label, numColor = C.red) {
  const fN = `800 156px JBMono`, fU = `800 72px JBMono`;
  ctx.letterSpacing = "-10px"; const wN = textW(num, fN);
  ctx.letterSpacing = "0px"; const wU = textW(unit, fU); const gap = 18, tot = wN + gap + wU;
  ctx.save(); ctx.globalAlpha = a;
  // dark band behind for contrast (part of the overlay, not of the portrait)
  ctx.save(); ctx.translate(W / 2, baseline - 62); ctx.scale(1, 0.34);
  const bg = ctx.createRadialGradient(0, 0, 10, 0, 0, 560); bg.addColorStop(0, "rgba(6,3,14,0.78)"); bg.addColorStop(0.6, "rgba(6,3,14,0.45)"); bg.addColorStop(1, "rgba(6,3,14,0)");
  ctx.fillStyle = bg; ctx.fillRect(-W, -1700, 2 * W, 3400); ctx.restore();
  ctx.translate(W / 2, baseline - 60); ctx.scale(sc, sc); ctx.translate(-W / 2, -(baseline - 60));
  const x0 = W / 2 - tot / 2;
  ctx.textBaseline = "alphabetic"; ctx.shadowColor = "rgba(244,63,94,0.85)"; ctx.shadowBlur = 38;
  ctx.letterSpacing = "-10px";
  ctx.font = fN; ctx.fillStyle = numColor; ctx.fillText(num, x0, baseline);
  ctx.shadowBlur = 0; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(255,255,255,0.35)"; ctx.strokeText(num, x0, baseline);
  ctx.letterSpacing = "0px"; ctx.shadowBlur = 38; ctx.font = fU; ctx.fillStyle = C.red; ctx.fillText(unit, x0 + wN + gap, baseline);
  ctx.restore(); ctx.letterSpacing = "0px";
  rec("counter", W / 2 - tot * sc / 2, baseline - 60 - 64 * sc, tot * sc, 124 * sc, 156);
  if (label) {
    const fL = `800 40px InterV`; const ls = 3; ctx.save(); ctx.globalAlpha = a * label.a; ctx.font = fL; ctx.letterSpacing = ls + "px";
    const lw = textW(label.text, fL) + ls * label.text.length; ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.textBaseline = "alphabetic";
    ctx.shadowColor = "rgba(0,0,0,0.9)"; ctx.shadowBlur = 10; ctx.fillText(label.text, W / 2 - lw / 2, baseline + 76); ctx.restore();
    rec("counter_label", W / 2 - lw / 2, baseline + 44, lw, 40);
  }
}

// card in screen space: focus card px (fx, fy) at screen (sx, sy) with scale s (screen px per card px)
const h0 = HOLD[2] / imgCard.width;
const B = R.card.boxes;
const ctr = b => [b[0] + b[2] / 2, b[1] + b[3] / 2];
const union = (...bs) => { const x0 = Math.min(...bs.map(b => b[0])), y0 = Math.min(...bs.map(b => b[1])), x1 = Math.max(...bs.map(b => b[0] + b[2])), y1 = Math.max(...bs.map(b => b[1] + b[3])); return [x0, y0, x1 - x0, y1 - y0]; };
const BOX = { amount: B.amount, owner: B.owner, traded: union(B.traded_word, B.traded), filed: union(B.filed_word, B.filed), perf: B.perf, column: B.column };
const ROW = union(B.ticker, B.amount, B.perf, B.lag, B.filed);
const S_HOLD = { f: [imgCard.width / 2, imgCard.height / 2], s: [HOLD[0] + HOLD[2] / 2, HOLD[1] + HOLD[3] / 2], k: h0 };
const LOCKK = 2.6 * h0;
const KEY = {
  amount: { f: ctr(BOX.amount), s: [470, 860], k: LOCKK },
  owner: { f: ctr(BOX.owner), s: [520, 860], k: LOCKK },
  traded: { f: ctr(BOX.traded), s: [480, 840], k: LOCKK },
  filed: { f: ctr(BOX.filed), s: [500, 840], k: LOCKK },
};
const ROW_WIDE = { f: ctr(ROW), s: [W / 2 - 20, 820], k: Math.min(0.48, 860 / ROW[2]) };
const PERF_Z = { f: [ctr(BOX.perf)[0] - 120, (BOX.column[1] + BOX.perf[1] + BOX.perf[3]) / 2], s: [560, 800], k: 0.86 };
const lerpS = (a, b, k) => ({ f: [lerp(a.f[0], b.f[0], k), lerp(a.f[1], b.f[1], k)], s: [lerp(a.s[0], b.s[0], k), lerp(a.s[1], b.s[1], k)], k: Math.exp(lerp(Math.log(a.k), Math.log(b.k), k)) });
function lockState(t) {
  let st = S_HOLD; let prev = S_HOLD, at = T.lock0;
  const seq = [{ t: T.lock0, to: KEY.amount, dur: Math.max(0.35, T.lock[0].t - T.lock0 + 0.05) }].concat(T.lock.slice(1).map(l => ({ t: l.t - 0.32, to: KEY[l.key], dur: 0.42 })));
  for (const s of seq) { if (t < s.t) break; const k = easeInOut(prog(t, s.t, s.t + s.dur)); st = lerpS(prev, s.to, k); prev = s.to; if (k < 1) break; }
  return st;
}
const toScreen = (st, x, y) => [st.s[0] + (x - st.f[0]) * st.k, st.s[1] + (y - st.f[1]) * st.k];
function drawCard(st, img) {
  const [x, y] = toScreen(st, 0, 0);
  ctx.save(); ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, x, y, img.width * st.k, img.height * st.k); ctx.restore();
}
function highlight(st, box, k, color, pad = 14) {
  if (k <= 0) return;
  const [x0, y0] = toScreen(st, box[0] - pad, box[1] - pad * 0.6), [x1, y1] = toScreen(st, box[0] + box[2] + pad, box[1] + box[3] + pad * 0.6);
  const w = (x1 - x0) * clamp(k);
  ctx.save(); ctx.globalCompositeOperation = "screen"; ctx.fillStyle = color === "red" ? "rgba(244,63,94,0.38)" : "rgba(59,232,255,0.30)";
  ctx.beginPath(); ctx.roundRect(x0, y0, w, y1 - y0, 10); ctx.fill(); ctx.restore();
  ctx.save(); ctx.fillStyle = color === "red" ? C.red : C.cyan; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 14; ctx.fillRect(x0, y1 - 3, w, 7); ctx.restore();
}
function rowOutline(st, a) {
  if (a <= 0) return; const pad = 26;
  const [x0, y0] = toScreen(st, ROW[0] - pad, ROW[1] - pad), [x1, y1] = toScreen(st, ROW[0] + ROW[2] + pad, ROW[1] + ROW[3] + pad);
  ctx.save(); ctx.globalAlpha = a; ctx.strokeStyle = C.cyan; ctx.lineWidth = 4; ctx.shadowColor = C.cyan; ctx.shadowBlur = 22; ctx.beginPath(); ctx.roundRect(x0, y0, x1 - x0, y1 - y0, 18); ctx.stroke(); ctx.restore();
}

function drawCaption(t) {
  if (t >= T.brand_big - 0.02) return;
  const cap = R.captions.find(c => t >= c.t0 && t < c.t1); if (!cap) return;
  const fs = 92, font = `900 ${fs}px InterV`, stroke = 20;
  const txt = cap.parts.map(p => p.text).join(" ");
  let s = fs; let w = textW(txt, font);
  if (w > 780) { s = Math.floor(fs * 780 / w); w = textW(txt, `900 ${s}px InterV`); }
  const f = `900 ${s}px InterV`; const pop = 1 + 0.06 * (1 - easeOut(prog(t, cap.t0, cap.t0 + 0.12)));
  const cx = 490, base = 1440;
  ctx.save(); ctx.translate(cx, base - s * 0.35); ctx.scale(pop, pop); ctx.translate(-cx, -(base - s * 0.35));
  ctx.font = f; ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round";
  let x = cx - w / 2;
  for (const p of cap.parts) {
    const ww = textW(p.text + " ", f);
    ctx.lineWidth = stroke; ctx.strokeStyle = "#07030f"; ctx.strokeText(p.text, x, base);
    ctx.fillStyle = p.color === "cyan" ? C.cyan : p.color === "red" ? C.red : C.white; ctx.fillText(p.text, x, base); x += ww;
  }
  ctx.restore();
  rec("caption", cx - w * pop / 2 - stroke / 2, base - s * 0.76 * pop - stroke / 2, w * pop + stroke, s * 0.98 * pop + stroke, s);
}

function project(v) { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H]; }

function drawSinkOverlay(t) {
  // labels at projected 3D anchors, the gap bracket and the giant counter
  const spyR = project(new THREE.Vector3(-6.2, FLOOR + TH, TW / 2 + 0.2));
  const topY = towerG.position.y + TH / 2;
  const tTop = project(new THREE.Vector3(0, topY, TW / 2));
  const tRight = project(new THREE.Vector3(TW / 2 + 0.6, topY, TW / 2));
  const lineRight = project(new THREE.Vector3(TW / 2 + 0.6, FLOOR + TH, TW / 2));
  ctx.save(); ctx.textBaseline = "alphabetic";
  ctx.font = `800 72px JBMono`; ctx.lineJoin = "round"; ctx.lineWidth = 12; ctx.strokeStyle = "rgba(6,3,14,0.9)";
  const sx = clamp(spyR[0], 72, 600), sy = spyR[1] - 30; ctx.strokeText(R.text.line_label, sx, sy);
  ctx.fillStyle = C.white; ctx.shadowColor = C.cyan; ctx.shadowBlur = 20; ctx.fillText(R.text.line_label, sx, sy); rec("spy_label", sx, sy - 54, textW(R.text.line_label, `800 72px JBMono`), 58);
  ctx.shadowBlur = 0;
  ctx.font = `800 58px JBMono`; ctx.fillStyle = C.white; const tw = textW(R.text.ticker, `800 58px JBMono`);
  const ty = tTop[1] + 72; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(10,4,16,0.85)"; ctx.strokeText(R.text.ticker, tTop[0] - tw / 2, ty); ctx.fillText(R.text.ticker, tTop[0] - tw / 2, ty);
  rec("ticker_label", tTop[0] - tw / 2, ty - 46, tw, 50);
  // bracket between the SPY line and the tower top (draws at the spoken number)
  const bk = prog(t, T.gapnum - 0.1, T.gapnum + 0.25);
  if (t > T.hit + 0.15 && bk > 0) {
    const x = Math.min(tRight[0] + 10, 880), y0 = lineRight[1], y1 = lerp(y0, tRight[1], easeOut(bk));
    ctx.strokeStyle = C.red; ctx.lineWidth = 6; ctx.shadowColor = C.red; ctx.shadowBlur = 16; ctx.beginPath();
    ctx.moveTo(x - 22, y0); ctx.lineTo(x, y0); ctx.lineTo(x, y1); ctx.lineTo(x - 22, y1); ctx.stroke();
  }
  ctx.restore();
  if (t >= T.hit) {
    const k = prog(t, T.hit, T.hit + 0.18);
    let sc = k < 1 ? lerp(1.25, 1.0, easeIn(k)) : 1 + 0.18 * Math.exp(-(t - T.hit - 0.18) * 14) * Math.sin((t - T.hit - 0.18) * 30);
    if (t >= T.gapnum && t < T.gapnum + 0.3) sc *= 1 + 0.08 * Math.sin(prog(t, T.gapnum, T.gapnum + 0.3) * Math.PI);
    drawCounter(R.text.counter, R.text.counter_unit, 1250, sc, clamp(k * 3), { text: R.text.sink_label, a: prog(t, T.hit + 0.12, T.hit + 0.35) }, C.white);
  }
}

function drawEnd(t) {
  if (t < T.brand_big - 0.05) return;
  const a = prog(t, T.brand_big - 0.05, T.brand_big + 0.2) * (t >= T.loop0 ? 1 - prog(t, T.loop0, T.loop0 + 0.3) : 1);
  if (a <= 0) return;
  const tile = 118, fs = 70, font = `900 ${fs}px InterV`;
  const tw = textW(R.text.wordmark, font), tot = tile + 22 + tw;
  const pop = 1 + 0.12 * (1 - easeOutBack(prog(t, T.brand_big - 0.05, T.brand_big + 0.3)));
  const x0 = W / 2 - tot / 2, y0 = 330;
  ctx.save(); ctx.globalAlpha = a; ctx.translate(W / 2, y0 + tile / 2); ctx.scale(pop, pop); ctx.translate(-W / 2, -(y0 + tile / 2));
  ctx.shadowColor = "rgba(59,232,255,0.6)"; ctx.shadowBlur = 30; ctx.drawImage(MARK, x0, y0, tile, tile); ctx.shadowBlur = 0;
  ctx.font = font; ctx.fillStyle = C.white; ctx.textBaseline = "middle"; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(6,3,14,0.85)";
  ctx.strokeText(R.text.wordmark, x0 + tile + 22, y0 + tile / 2 + 4); ctx.fillText(R.text.wordmark, x0 + tile + 22, y0 + tile / 2 + 4); ctx.restore();
  rec("end_brand", x0, y0, tot, tile);
  const f2 = `800 66px InterV`, w2 = textW(R.text.site, f2);
  ctx.save(); ctx.globalAlpha = a; ctx.font = f2; ctx.textBaseline = "alphabetic"; ctx.lineWidth = 12; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.lineJoin = "round";
  ctx.strokeText(R.text.site, W / 2 - w2 / 2, 1392); ctx.fillStyle = C.cyan; ctx.fillText(R.text.site, W / 2 - w2 / 2, 1392); ctx.restore();
  rec("end_site", W / 2 - w2 / 2, 1342, w2, 64);
  const da = a * prog(t, T.disclaim - 0.15, T.disclaim + 0.1);
  if (da > 0) {
    const f3 = `600 46px InterV`, w3 = textW(R.text.disclaimer, f3);
    ctx.save(); ctx.globalAlpha = da; ctx.font = f3; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.lineJoin = "round"; ctx.strokeText(R.text.disclaimer, W / 2 - w3 / 2, 1468); ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.fillText(R.text.disclaimer, W / 2 - w3 / 2, 1468); ctx.restore();
    rec("end_disclaimer", W / 2 - w3 / 2, 1432, w3, 46);
  }
}

// ---------------------------------------------------------------------------------------------- frame
function blurSpans(t) {
  return (t >= T.flip0 - 0.02 && t <= T.flip1 + 0.04) || (t >= T.hit && t <= T.hit + 0.25) || (t >= T.stamp - 0.24 && t <= T.stamp + 0.03) || (t >= T.loop0 && t < LOOP_END - 0.05);
}
function render3D(t) {
  const M = blurSpans(t) ? 7 : 1; const shutter = 0.5 / FPS;
  let st;
  for (let i = 0; i < M; i++) {
    const ts = M === 1 ? t : t - shutter / 2 + shutter * i / (M - 1);
    st = world(ts); composer.render();
    actx.globalAlpha = 1 / (i + 1); actx.drawImage(glc, 0, 0);
  }
  actx.globalAlpha = 1; world(t);   // leave the world at t for projections
  return st;
}

window.renderFrame = (t) => {
  TEXTS = [];
  const p = phase(t);
  render3D(t);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, W, H);
  const sh = shakeAt(t);
  ctx.save(); ctx.translate(sh[0] * 0.6, sh[1] * 0.6);
  ctx.drawImage(acc, 0, 0);
  ctx.restore();
  if (p === "hold") {
    // the real card, flat and untouched, pixel for pixel the Lanczos-scaled capture
    ctx.save(); ctx.strokeStyle = "rgba(59,232,255,0.55)"; ctx.lineWidth = 3; ctx.shadowColor = C.cyan; ctx.shadowBlur = 18; ctx.strokeRect(HOLD[0] - 4, HOLD[1] - 4, HOLD[2] + 8, HOLD[3] + 8); ctx.restore();
    ctx.drawImage(imgHold, HOLD[0], HOLD[1]);   // drawn last: nothing touches the card pixels
  }
  if (p === "lock") {
    const st = lockState(t);
    drawCard(st, prog(t, T.lock0, T.lock0 + 0.25) < 1 ? imgCard : cardFaded);
    rowOutline(st, prog(t, T.lock0 + 0.1, T.lock0 + 0.4));
    for (const l of T.lock) highlight(st, BOX[l.key], prog(t, l.t, l.t + 0.28), "cyan");
  }
  if (p === "row") {
    const k = easeInOut(prog(t, T.cut_row + 0.5, T.cut_row + 1.05));
    const st = lerpS(ROW_WIDE, PERF_Z, k);
    ctx.save(); ctx.fillStyle = "rgba(7,4,15,0.55)"; ctx.fillRect(0, 0, W, H); ctx.restore();
    drawCard(st, cardFaded);
    rowOutline(st, 1 - k * 0.6);
    highlight(st, BOX.perf, prog(t, T.cut_row + 0.12, T.cut_row + 0.4), "red", 18);
    highlight(st, BOX.column, prog(t, T.cut_row + 0.75, T.cut_row + 1.0), "cyan", 10);
  }
  if (p === "lock" || p === "row") {
    const g = ctx.createLinearGradient(0, 150, 0, 330); g.addColorStop(0, "rgba(7,4,15,0.88)"); g.addColorStop(1, "rgba(7,4,15,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, 330); ctx.fillStyle = "rgba(7,4,15,0.88)"; ctx.fillRect(0, 0, W, 150);
  }
  if (p === "hook" || p === "flip" || p === "loop") { drawHeadline(t); drawCounterHook(t); }
  if (p === "sink") drawSinkOverlay(t);
  if (p === "end" || p === "loop") drawEnd(t);
  if (p !== "hook" && p !== "loop") drawCaption(t);
  // flash at the hit (2-3 frames, opacity <= 0.5)
  if (t >= T.hit && t < T.hit + 3 / FPS) { const f = Math.floor((t - T.hit) * FPS + 1e-6); ctx.fillStyle = `rgba(255,255,255,${[0.45, 0.28, 0.12][f] ?? 0})`; ctx.fillRect(0, 0, W, H); }
  const mark = drawKicker(t, p);
  return { phase: p, mark, texts: TEXTS };
};
window.sceneReady = true;
