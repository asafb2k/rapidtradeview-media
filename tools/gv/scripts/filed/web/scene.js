// FILED. by RapidTradeView: the episode scene. Three.js (MIT) for the 3D world (monolith, flip, sink, stamp) with
// bloom and grain on the world only; a 2D canvas on top for the real site card (flat, untouched while held), the lifted
// trade row, text, captions and the brand mark. Everything is a pure function of t: window.renderFrame(t) draws a frame.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { Reflector } from "three/addons/objects/Reflector.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const R = await (await fetch("/run/render.json")).json();
const W = R.W, H = R.H, T = R.T, DUR = R.duration, FPS = R.fps;
const C = { red: "#F43F5E", cyan: "#3BE8FF", white: "#FFFFFF" };

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
const deg = THREE.MathUtils.degToRad;

// ---------------------------------------------------------------------------------------------- loading
const loadImg = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("img " + src)); i.src = src; });
const [imgFace, imgDepth, imgCard, imgHold, imgRow] = await Promise.all([R.assets.face, R.assets.depth, R.assets.card, R.assets.card_hold, R.assets.row].map(loadImg));
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
  for (const s of R.mark.mark.stops) mg.addColorStop(s.offset, s.color);
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
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 900);
scene.fog = new THREE.FogExp2(0x0a0614, 0.010);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;   // reflections for the glass only
scene.environmentIntensity = 0.55;

// sky: a violet void with a soft horizon (the mirror floor reflects it, so there is no seam)
const sky = new THREE.Mesh(new THREE.SphereGeometry(500, 32, 16), new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, fog: false,
  vertexShader: `varying vec3 vd; void main(){ vd = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec3 vd; void main(){ float y = vd.y;
    vec3 top = vec3(0.010,0.005,0.026); vec3 hor = vec3(0.075,0.034,0.15);
    vec3 c = mix(hor, top, smoothstep(-0.05, 0.6, y));
    c += vec3(0.035,0.012,0.07) * exp(-abs(y)*9.0);
    gl_FragColor = vec4(c,1.0);
    #include <colorspace_fragment>
  }`
}));
scene.add(sky);

const SW = 9.6, SH = SW / R.slab_aspect, SD = 3.6, FLOOR = -SH / 2;

// floor: a dark mirror (blurred reflection) with a faint cyan grid that fades into fog
const FloorShader = {
  name: "FiledFloor",
  uniforms: { color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null }, glow: { value: 1.0 } },
  vertexShader: `uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 wp;
    void main(){ vUv = textureMatrix * vec4(position, 1.0); vec4 w = modelMatrix * vec4(position, 1.0); wp = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
  fragmentShader: `uniform sampler2D tDiffuse; uniform vec3 color; uniform float glow; varying vec4 vUv; varying vec3 wp;
    float line(float v){ float d = abs(fract(v - 0.5) - 0.5) / fwidth(v); return 1.0 - clamp(d, 0.0, 1.0); }
    void main(){
      vec3 r = vec3(0.0);
      for (int i = -2; i <= 2; i++) for (int j = -2; j <= 2; j++) { vec4 uv = vUv; uv.xy += vec2(float(i), float(j)) * 0.0045 * vUv.w; r += texture2DProj(tDiffuse, uv).rgb; }
      r /= 25.0;
      float dist = length(wp.xz - vec2(0.0, 4.0));
      vec2 g = wp.xz / 1.6;
      float l = max(line(g.x), line(g.y));
      float near = exp(-dist * 0.035);
      vec3 col = vec3(0.008, 0.005, 0.018) + r * 0.38;
      col += vec3(0.12, 0.75, 0.95) * l * 0.15 * near * glow;
      col += vec3(0.16, 0.06, 0.32) * exp(-dist * 0.08) * 0.16;
      float fogk = 1.0 - exp(-dist * 0.010);
      col = mix(col, vec3(0.075,0.034,0.15) * 0.55 + r * 0.25, fogk);
      gl_FragColor = vec4(col, 1.0);
      #include <colorspace_fragment>
    }`
};
const floor = new Reflector(new THREE.PlaneGeometry(900, 900), { textureWidth: 540, textureHeight: 960, clipBias: 0.003, shader: FloorShader, multisample: 4 });
floor.rotation.x = -Math.PI / 2; floor.position.y = FLOOR; scene.add(floor);
// the portrait never appears in the mirror (no flipped or blurred copy of the face): the slab is left out of the reflection
const floorBefore = floor.onBeforeRender.bind(floor);
// the glass towers are left out too (transmission does not render in the mirror pass); their edges still reflect
floor.onBeforeRender = (...a) => {
  const v = slabG.visible, g = [spyT, intcT].map(x => x.children[0].visible);
  slabG.visible = false; spyT.children[0].visible = intcT.children[0].visible = false;
  floorBefore(...a);
  slabG.visible = v; spyT.children[0].visible = g[0]; intcT.children[0].visible = g[1];
};

// lights: a key, a cyan rim behind-left, a violet fill; a red under-light for the sinking tower
scene.add(new THREE.AmbientLight(0x6040a0, 0.35));
const kl = new THREE.DirectionalLight(0xffffff, 1.0); kl.position.set(6, 10, 14); scene.add(kl);
const rimC = new THREE.PointLight(0x3be8ff, 140, 60, 1.5); rimC.position.set(-10, 5, -6); scene.add(rimC);
const rimM = new THREE.PointLight(0xb04cff, 70, 40, 1.6); rimM.position.set(10, -2, -3); scene.add(rimM);
const redUnder = new THREE.PointLight(0xf43f5e, 0, 18, 1.4); scene.add(redUnder);

// particles: periodic over the episode so the loop joins
const NP = 520;
const pGeo = new THREE.BufferGeometry();
const pBase = new Float32Array(NP * 4), pPos = new Float32Array(NP * 3), pCol = new Float32Array(NP * 3);
{ let s = 12345; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < NP; i++) { pBase[i * 4] = (rnd() - .5) * 46; pBase[i * 4 + 1] = rnd(); pBase[i * 4 + 2] = -30 + rnd() * 40; pBase[i * 4 + 3] = 1 + Math.floor(rnd() * 2);
    if (Math.abs(pBase[i * 4]) < 8 && pBase[i * 4 + 2] > -3.0) pBase[i * 4 + 2] = -3.0 - rnd() * 6;   // nothing drifts in front of the portrait
    const c = rnd() < 0.7 ? [0.23, 0.9, 1.0] : [0.7, 0.35, 1.0]; const b = 0.5 + rnd() * 1.3; pCol.set([c[0] * b, c[1] * b, c[2] * b], i * 3); } }
pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3)); pGeo.setAttribute("color", new THREE.BufferAttribute(pCol, 3));
const dot = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d"); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32); gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.35, "rgba(255,255,255,0.5)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); })();
const points = new THREE.Points(pGeo, new THREE.PointsMaterial({ size: 0.15, map: dot, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }));
scene.add(points);
function updateParticles(t) {
  const u = ph(t) / DUR, Hh = 26;
  for (let i = 0; i < NP; i++) {
    pPos[i * 3] = pBase[i * 4] + 0.4 * Math.sin(2 * Math.PI * (u * 2 + i * 0.37));
    pPos[i * 3 + 1] = FLOOR + ((pBase[i * 4 + 1] + u * pBase[i * 4 + 3]) % 1) * Hh;
    pPos[i * 3 + 2] = pBase[i * 4 + 2];
  }
  pGeo.attributes.position.needsUpdate = true;
}

// ---------------------------------------------------------------------------------------------- the monolith
function texFrom(img, srgb = true) { const t = new THREE.Texture(img); t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace; t.anisotropy = 8; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter; t.needsUpdate = true; return t; }
const faceTex = texFrom(imgFace), depthTex = texFrom(imgDepth, false);
const faceMat = new THREE.ShaderMaterial({
  uniforms: { img: { value: faceTex }, dep: { value: depthTex }, off: { value: new THREE.Vector2() }, focus: { value: 0.55 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 vUv; uniform sampler2D img, dep; uniform vec2 off; uniform float focus;
    void main(){
      vec2 c = vUv; vec2 s = c;
      for (int i = 0; i < 6; i++) { float d = texture2D(dep, s).r; s = c + off * (d - focus); }
      vec4 col = texture2D(img, s);
      vec2 e = min(vUv, 1.0 - vUv); float edge = smoothstep(0.0, 0.03, min(e.x, e.y));
      col.rgb *= mix(0.82, 1.0, edge);
      gl_FragColor = vec4(col.rgb, 1.0);
      #include <colorspace_fragment>
    }`
});
// back face: the real card centred on a dark slab back (the 2D overlay covers the card region exactly while held)
const backCanvas = (() => {
  const cw = imgCard.width, chh = Math.round(cw / R.slab_aspect);
  const c = document.createElement("canvas"); c.width = cw; c.height = chh; const g = c.getContext("2d");
  const gr = g.createLinearGradient(0, 0, 0, chh); gr.addColorStop(0, "#150e26"); gr.addColorStop(1, "#0b0716"); g.fillStyle = gr; g.fillRect(0, 0, cw, chh);
  g.drawImage(imgCard, 0, Math.round((chh - imgCard.height) / 2));
  return c;
})();
const backTex = new THREE.CanvasTexture(backCanvas); backTex.colorSpace = THREE.SRGBColorSpace; backTex.anisotropy = 8;
const backMat = new THREE.MeshBasicMaterial({ map: backTex, toneMapped: false });
const sideMat = new THREE.MeshPhysicalMaterial({ color: 0x3a2a66, metalness: 0.55, roughness: 0.18, clearcoat: 1.0, clearcoatRoughness: 0.05, emissive: 0x0c0626, envMapIntensity: 2.6 });
const slab = new THREE.Mesh(new THREE.BoxGeometry(SW, SH, SD), [sideMat, sideMat, sideMat, sideMat, faceMat, backMat]);
const slabG = new THREE.Group(); slabG.add(slab); scene.add(slabG);
const edgeMat = new THREE.LineBasicMaterial({ color: new THREE.Color(0.3, 1.5, 1.8), transparent: true, opacity: 0.6 });
const slabEdges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(SW * 1.002, SH * 1.002, SD * 1.002)), edgeMat);
slabG.add(slabEdges);
const pool = new THREE.Mesh(new THREE.PlaneGeometry(SW * 2.4, SD * 5), new THREE.MeshBasicMaterial({ map: dot, color: new THREE.Color(0.25, 1.0, 1.3), transparent: true, opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending }));
pool.rotation.x = -Math.PI / 2; pool.position.y = FLOOR + 0.01; slabG.add(pool);

// ---------------------------------------------------------------------------------------------- the sink: two glass towers
const sinkG = new THREE.Group(); scene.add(sinkG);
const TW = 2.7, TH = 8.0, TX = 2.05, DROP = TH * Math.min(0.9, R.gap / 100);   // drawn to scale: 100 = the filing day
const clip = [new THREE.Plane(new THREE.Vector3(0, 1, 0), -FLOOR)];
const glass = (tint, att) => new THREE.MeshPhysicalMaterial({ color: tint, transmission: 0.9, roughness: 0.08, thickness: 2.2, ior: 1.5,
  attenuationColor: new THREE.Color(att), attenuationDistance: 2.2, metalness: 0.0, clearcoat: 1.0, clearcoatRoughness: 0.04,
  emissive: new THREE.Color(att), emissiveIntensity: 0.16, clippingPlanes: clip, envMapIntensity: 1.3 });
function tower(tint, att, edge) {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.BoxGeometry(TW, TH, TW), glass(tint, att)));
  const core = new THREE.Mesh(new THREE.BoxGeometry(TW * 0.5, TH * 0.98, TW * 0.5), new THREE.MeshBasicMaterial({ color: new THREE.Color(att).multiplyScalar(0.55), transparent: true, opacity: 0.35, clippingPlanes: clip, depthWrite: false, blending: THREE.AdditiveBlending }));
  core.visible = false;
  g.add(new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(TW, TH, TW)), new THREE.LineBasicMaterial({ color: edge, clippingPlanes: clip })));
  return g;
}
const spyT = tower(0xbff6ff, 0x3be8ff, new THREE.Color(0.4, 1.7, 2.0)); spyT.position.set(-TX, FLOOR + TH / 2, 0); sinkG.add(spyT);
const intcT = tower(0xffc2cc, 0xf43f5e, new THREE.Color(1.9, 0.35, 0.55)); intcT.position.set(TX, FLOOR + TH / 2, 0); sinkG.add(intcT);
const ghost = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(TW, TH, TW)), new THREE.LineDashedMaterial({ color: 0xffffff, transparent: true, opacity: 0.0, dashSize: 0.25, gapSize: 0.18 }));
ghost.computeLineDistances(); ghost.position.set(TX, FLOOR + TH / 2, 0); sinkG.add(ghost);
const spyLine = new THREE.Mesh(new THREE.BoxGeometry(TX * 2 + TW + 2.2, 0.045, 0.045), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.45, 1.35, 1.6), toneMapped: false }));
spyLine.position.set(0, FLOOR + TH, TW / 2 + 0.05); sinkG.add(spyLine);

// ---------------------------------------------------------------------------------------------- the stamp
const stampCanvas = (() => {
  const c = document.createElement("canvas"); c.width = 1800; c.height = 700; const g = c.getContext("2d");
  g.strokeStyle = "#fff"; g.lineWidth = 34; g.beginPath(); g.roundRect(40, 40, 1720, 620, 70); g.stroke();
  g.fillStyle = "#fff"; g.font = '400 430px "Archivo Black"'; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(R.text.stamp, 900, 380);
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
const bloom = new UnrealBloomPass(new THREE.Vector2(W / 2, H / 2), 0.7, 0.45, 0.86); composer.addPass(bloom);
const grain = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, seed: { value: 0 }, amount: { value: 0.024 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float seed, amount; varying vec2 vUv;
    float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233)) + seed) * 43758.5453); }
    void main(){ vec4 c = texture2D(tDiffuse, vUv); vec2 v = vUv - 0.5; c.rgb *= 1.0 - dot(v, v) * 0.9;
      c.rgb += (h(vUv * vec2(1080.0, 1920.0)) - 0.5) * amount; gl_FragColor = c; }`
});
composer.addPass(grain);
composer.addPass(new OutputPass());

// ---------------------------------------------------------------------------------------------- camera poses
const tanH = Math.tan(deg(20));
const HOLD = R.card.hold;                      // [x, y, w, h] of the flat card on screen
const PXU = HOLD[2] / SW;                       // px per world unit at the back face while held
const dHold = H / (2 * tanH * PXU);
const holdCY = (HOLD[1] + HOLD[3] / 2 - H / 2) / PXU;   // card centre below screen centre -> camera above
const POSE_HOLD = { pos: [0, holdCY, SD / 2 + dHold], look: [0, holdCY, 0], fov: 40 };
const orbitPos = (pos, a) => [pos[0] * Math.cos(a) + pos[2] * Math.sin(a), pos[1], -pos[0] * Math.sin(a) + pos[2] * Math.cos(a)];
const HOOK_ANG0 = deg(-12);
function poseHook(t) {                          // frame 0 .. flip: from below, orbit -10 deg, dolly-in 100 -> 108 %, a whip at the chip
  const e = 1 - Math.pow(1 - clamp(t / T.flip0), 1.6);
  const dist = 36.5 / (1 + 0.08 * e);
  const whip = deg(6) * easeOutBack(prog(t, T.chip - 0.14, T.chip + 0.16), 1.3);
  const ang = HOOK_ANG0 + deg(2) * e + whip;
  return { pos: [Math.sin(ang) * dist, -2.7, Math.cos(ang) * dist], look: [0, -0.15, 0], fov: 40, orbit: ang };
}
const POSE_SINK0 = { pos: [3.4, 4.3, 25.0], look: [0, 0.35, 0], fov: 40 };
const POSE_SINK1 = { pos: [2.1, 3.9, 23.0], look: [0, 0.3, 0], fov: 40 };
const POSE_END1 = { pos: [0, -1.4, 37.0], look: [0, -0.9, 0], fov: 40 };
const lerpPose = (a, b, k) => ({ pos: a.pos.map((v, i) => lerp(v, b.pos[i], k)), look: a.look.map((v, i) => lerp(v, b.look[i], k)), fov: lerp(a.fov, b.fov, k) });
function poseEnd(t) {                           // pull back from the card, then a slow orbit round the stamped slab
  const p = lerpPose(POSE_HOLD, POSE_END1, easeOut(prog(t, T.end0, T.end0 + 1.4)));
  const a = deg(11) * easeInOut(prog(t, T.end0 + 0.3, T.loop0 + 0.2));
  return { ...p, pos: orbitPos(p.pos, a) };
}
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
  if (t >= T.chip && t < T.chip + 0.3) a += 5 * Math.exp(-(t - T.chip) * 14);
  return [a * Math.sin(t * 97.0), a * Math.cos(t * 71.0)];
}
function intcDrop(t) {
  if (t < T.hit) return 0;
  const k = prog(t, T.hit, T.hit + 0.16);
  return DROP * (easeIn(k) - (t > T.hit + 0.16 ? 0.06 * Math.sin(prog(t, T.hit + 0.16, T.hit + 0.5) * Math.PI) : 0));
}
function world(t) {
  updateParticles(t);
  const p = phase(t);
  slabG.visible = p !== "sink";
  sinkG.visible = p === "sink";
  stamp.visible = ring.visible = (p === "end" || p === "loop") && t >= T.stamp - 0.3;
  let pose, rot = 0, orbit = 0;
  if (p === "hook") { pose = poseHook(t); orbit = pose.orbit; }
  else if (p === "flip" || p === "hold") {
    const k = easeInOut(prog(t, T.flip0, T.flip1));
    pose = lerpPose(poseHook(T.flip0), POSE_HOLD, easeInOut(prog(t, T.flip0 - 0.05, T.flip1)));
    rot = Math.PI * k;
  } else if (p === "sink") {
    pose = lerpPose(POSE_SINK0, POSE_SINK1, easeOut(prog(t, T.cut_sink, T.cut_row)));
  } else if (p === "end") { pose = poseEnd(t); rot = Math.PI; }
  else if (p === "loop") {
    const k = easeInOut(prog(t, T.loop0, LOOP_END));
    pose = lerpPose(poseEnd(T.loop0), poseHook(0), k); orbit = poseHook(0).orbit * k;
    rot = Math.PI + Math.PI * k;
  } else { pose = POSE_HOLD; rot = Math.PI; }
  slab.rotation.y = rot; slabEdges.rotation.y = rot;
  const w2 = 2 * Math.PI * 2 * ph(t) / DUR;
  faceMat.uniforms.off.value.set(clamp(orbit * 0.06, -0.008, 0.008) + 0.0015 * Math.sin(w2), -0.002 + 0.001 * Math.cos(w2));
  if (p === "sink") {
    intcT.position.y = FLOOR + TH / 2 - intcDrop(t);
    ghost.material.opacity = t < T.hit ? 0.0 : 0.4 * prog(t, T.hit, T.hit + 0.3);
    redUnder.intensity = t < T.hit ? 4 : 4 + 22 * Math.exp(-(t - T.hit) * 3);
    redUnder.position.set(TX + 2.4, FLOOR + 0.4, TW / 2 + 2.5);
  } else redUnder.intensity = 0;
  if (stamp.visible) {
    const k = prog(t, T.stamp - 0.22, T.stamp);
    const lift = (1 - easeIn(k)) * 6.0;
    const fade = p === "loop" ? 1 - smooth(prog(t, T.loop0, T.loop0 + 0.3)) : 1;
    stamp.position.set(0, -0.2, -(SD / 2 + 0.04 + lift)); stamp.scale.setScalar(1 + (1 - easeIn(k)) * 0.7);
    stamp.rotation.z = deg(7 - (1 - k) * 10);
    stampMat.opacity = Math.min(1, k * 3) * fade * 0.97;
    const rk = prog(t, T.stamp, T.stamp + 0.5);
    ring.position.set(0, -0.2, -(SD / 2 + 0.05)); ring.scale.setScalar(2 + rk * 7); ring.material.opacity = t >= T.stamp ? (1 - rk) * 0.8 * fade : 0;
  }
  floor.material.uniforms.glow.value = p === "sink" ? 0.8 : 1.0;
  applyPose(pose, shakeAt(t));
  grain.uniforms.seed.value = (Math.round(ph(t) * FPS) % 97) * 1.37;
  return { pose, p };
}

// ---------------------------------------------------------------------------------------------- 2D overlay
const out = document.getElementById("out"); const ctx = out.getContext("2d");
const acc = document.createElement("canvas"); acc.width = W; acc.height = H; const actx = acc.getContext("2d");
let TEXTS = [];
function rec(role, x, y, w, h, size) { TEXTS.push({ role, box: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)], size }); }
function textW(s, font, ls = 0) { ctx.font = font; return ctx.measureText(s).width + ls * Math.max(0, s.length - 1); }
function fitFont(lines, family, max, min, width) { for (let s = max; s >= min; s -= 2) { if (lines.every(l => textW(l, family.replace("{s}", s)) <= width)) return s; } return min; }

// the end lockup's opacity: while it shows, the corner pill steps aside (one brand mark on screen at a time)
const bigA = t => t < T.brand_big - 0.05 ? 0 : prog(t, T.brand_big - 0.05, T.brand_big + 0.2) * (t >= T.loop0 ? 1 - prog(t, T.loop0, T.loop0 + 0.3) : 1);

function drawKicker(t) {
  const tile = 60, fs = 44, font = `800 ${fs}px InterV`;
  const tw = textW(R.text.wordmark, font);
  const bw = 18 + tile + 14 + tw + 26, bh = tile + 16;
  const cx0 = W / 2 - bw / 2, cy0 = 204, cx1 = 60, cy1 = 204, s1 = 0.84;
  let k = 0;
  if (t >= T.flip0) k = easeInOut(prog(t, T.flip0, T.flip1 + 0.15));
  if (t >= T.loop0) k = 1 - easeInOut(prog(t, T.loop0, LOOP_END));
  const x = lerp(cx0, cx1, k), y = lerp(cy0, cy1, k), s = lerp(1, s1, k);
  const al = 1 - bigA(t);
  if (al > 0) {
    ctx.save(); ctx.globalAlpha = al; ctx.translate(x, y); ctx.scale(s, s);
    ctx.fillStyle = "rgba(9,5,20,0.82)"; ctx.strokeStyle = "rgba(59,232,255,0.45)"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.roundRect(0, 0, bw, bh, bh / 2); ctx.fill(); ctx.stroke();
    ctx.drawImage(MARK, 18, 8, tile, tile);
    ctx.font = font; ctx.fillStyle = "rgba(255,255,255,0.96)"; ctx.textBaseline = "middle"; ctx.fillText(R.text.wordmark, 18 + tile + 14, bh / 2 + 2);
    ctx.restore();
    rec("kicker", x, y, bw * s, bh * s);
    const da = (t >= T.flip0 ? prog(t, T.flip1, T.flip1 + 0.25) : 0) * (t >= T.loop0 ? 1 - prog(t, T.loop0, T.loop0 + 0.3) : 1) * al;
    if (da > 0) {
      const f2 = `400 30px "Archivo Black"`; const dw = textW(R.text.day, f2) + 30;
      const dx = x + bw * s + 12, dy = y + (bh * s - 44) / 2;
      ctx.save(); ctx.globalAlpha = da; ctx.fillStyle = "rgba(59,232,255,0.14)"; ctx.strokeStyle = C.cyan; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.roundRect(dx, dy, dw, 44, 22); ctx.fill(); ctx.stroke();
      ctx.font = f2; ctx.fillStyle = C.cyan; ctx.textBaseline = "middle"; ctx.fillText(R.text.day, dx + 15, dy + 24); ctx.restore();
      rec("day", dx, dy, dw, 44);
    }
  }
  return [x + 18 * s, y + 8 * s, tile * s, tile * s];
}

function headlineAlpha(t) {
  if (t < T.flip0) return 1;
  if (t < T.loop0) return 1 - prog(t, T.flip0 - 0.02, T.flip0 + 0.22);
  return smooth(prog(t, T.loop0 + 0.2, LOOP_END));
}
function drawHeadline(t) {
  const a = headlineAlpha(t); if (a <= 0) return;
  const lines = R.text.headline; const maxW = 800;
  const fs = fitFont(lines, '400 {s}px "Archivo Black"', 104, 64, maxW);
  const font = `400 ${fs}px "Archivo Black"`;
  const y0 = 296 + fs * 0.82;
  const lift = t >= T.flip0 && t < T.loop0 ? -60 * prog(t, T.flip0, T.flip0 + 0.22) : (t >= T.loop0 ? 30 * (1 - a) : 0);
  ctx.save(); ctx.globalAlpha = a; ctx.font = font; ctx.textBaseline = "alphabetic";
  lines.forEach((ln, i) => {
    const y = y0 + i * fs * 1.04 + lift;
    const words = ln.split(" "); const total = textW(ln, font); let x = W / 2 - total / 2;
    for (const wd of words) {
      const ww = textW(wd + " ", font);
      ctx.lineJoin = "round"; ctx.lineWidth = 14; ctx.strokeStyle = "rgba(6,3,14,0.92)"; ctx.strokeText(wd, x, y);
      ctx.fillStyle = wd.replace(/[^A-Z']/g, "") === R.text.headline_accent ? C.cyan : C.white; ctx.fillText(wd, x, y); x += ww;
    }
    rec("headline", W / 2 - total / 2, y - fs * 0.78, total, fs * 0.84, fs);
  });
  ctx.restore();
}

// monospace counter with the period's cell tightened (the mono "." leaves a wide gap)
function monoLayout(s, size) {
  ctx.font = `800 ${size}px JBMono`; const adv = ctx.measureText("0").width;
  const xs = []; let x = 0;
  for (const ch of s) {
    if (ch === ".") { xs.push(x - adv * 0.27); x += adv * 0.42; }
    else { xs.push(x); x += adv - size * 0.06; }
  }
  return { xs, w: x + size * 0.06 };
}
function drawCounter(num, unit, baseline, sc, a, label, numColor = C.red, cx = W / 2) {
  const N = 156, fU = `800 72px JBMono`;
  const L = monoLayout(num, N);
  const wU = textW(unit, fU); const gap = 16, tot = L.w + gap + wU;
  ctx.save(); ctx.globalAlpha = a;
  ctx.save(); ctx.translate(cx, baseline - 62); ctx.scale(1, 0.34);
  const bg = ctx.createRadialGradient(0, 0, 10, 0, 0, 560); bg.addColorStop(0, "rgba(6,3,14,0.78)"); bg.addColorStop(0.6, "rgba(6,3,14,0.45)"); bg.addColorStop(1, "rgba(6,3,14,0)");
  ctx.fillStyle = bg; ctx.fillRect(-W, -1700, 2 * W, 3400); ctx.restore();
  ctx.translate(cx, baseline - 60); ctx.scale(sc, sc); ctx.translate(-cx, -(baseline - 60));
  const x0 = cx - tot / 2;
  ctx.textBaseline = "alphabetic"; ctx.font = `800 ${N}px JBMono`;
  [...num].forEach((ch, i) => {
    ctx.shadowColor = "rgba(244,63,94,0.85)"; ctx.shadowBlur = 38; ctx.fillStyle = numColor; ctx.fillText(ch, x0 + L.xs[i], baseline);
    ctx.shadowBlur = 0; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(255,255,255,0.35)"; ctx.strokeText(ch, x0 + L.xs[i], baseline);
  });
  ctx.shadowBlur = 38; ctx.shadowColor = "rgba(244,63,94,0.85)"; ctx.font = fU; ctx.fillStyle = C.red; ctx.fillText(unit, x0 + L.w + gap, baseline);
  ctx.restore();
  rec("counter", cx - tot * sc / 2, baseline - 60 - 64 * sc, tot * sc, 124 * sc, N);
  if (label && label.a > 0) {
    const fL = `800 40px InterV`; const ls = 3; ctx.save(); ctx.globalAlpha = a * label.a; ctx.font = fL; ctx.letterSpacing = ls + "px";
    const lw = ctx.measureText(label.text).width; ctx.fillStyle = "rgba(255,255,255,0.94)"; ctx.textBaseline = "alphabetic";
    ctx.lineJoin = "round"; ctx.lineWidth = 9; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.strokeText(label.text, cx - lw / 2, baseline + 70);
    ctx.fillText(label.text, cx - lw / 2, baseline + 70); ctx.restore(); ctx.letterSpacing = "0px";
    rec("counter_label", cx - lw / 2, baseline + 38, lw, 40);
  }
}

function drawHookOverlay(t) {
  let a = 1;
  if (t >= T.flip0 && t < T.loop0) a = 1 - prog(t, T.flip0 - 0.02, T.flip0 + 0.2);
  if (t >= T.loop0) a = smooth(prog(t, T.loop0 + 0.25, LOOP_END));
  if (a <= 0) return;
  let sc = 1;
  if (t < T.flip0 && t >= T.punch) sc *= 1 + 0.12 * Math.sin(prog(t, T.punch, T.punch + 0.26) * Math.PI);
  if (t < T.flip0 && t >= T.chip) sc *= 1 + 0.05 * Math.sin(prog(t, T.chip + 0.05, T.chip + 0.25) * Math.PI);
  drawCounter(R.text.counter, R.text.counter_unit, 1392, sc, a, { text: R.text.counter_label, a: 1 });
  // the ticker chip slams in at the whip (the second event)
  const ck = t < T.flip0 ? prog(t, T.chip, T.chip + 0.16) : 0;
  if (ck > 0) {
    const f = `800 66px JBMono`; const label = R.text.chip;
    const cw = textW(label, f) + 52, chh = 86, cx = W / 2 - cw / 2, cy = 458;
    const s = lerp(1.9, 1.0, easeOut(ck)) * (1 + 0.06 * Math.sin(prog(t, T.chip + 0.16, T.chip + 0.36) * Math.PI));
    ctx.save(); ctx.globalAlpha = a * clamp(ck * 4); ctx.translate(W / 2, cy + chh / 2); ctx.scale(s, s); ctx.rotate(deg(-3) * (1 - easeOut(ck))); ctx.translate(-W / 2, -(cy + chh / 2));
    ctx.shadowColor = C.cyan; ctx.shadowBlur = 26;
    ctx.fillStyle = "rgba(9,5,20,0.9)"; ctx.strokeStyle = C.cyan; ctx.lineWidth = 4; ctx.beginPath(); ctx.roundRect(cx, cy, cw, chh, 18); ctx.fill(); ctx.stroke();
    ctx.shadowBlur = 0; ctx.font = f; ctx.fillStyle = C.white; ctx.textBaseline = "middle"; ctx.fillText(label, cx + 26, cy + chh / 2 + 3); ctx.restore();
    if (ck >= 1) rec("chip", cx, cy, cw, chh);
  }
}

// ---------------------------------------------------------------------------------------------- the card, the lifted row
const B = R.card.boxes, ROW = R.card.row, h0 = HOLD[2] / R.card.w;
const union = (...bs) => { const x0 = Math.min(...bs.map(b => b[0])), y0 = Math.min(...bs.map(b => b[1])), x1 = Math.max(...bs.map(b => b[0] + b[2])), y1 = Math.max(...bs.map(b => b[1] + b[3])); return [x0, y0, x1 - x0, y1 - y0]; };
const BOX = { amount: B.amount, owner: B.owner, traded: union(B.traded_word, B.traded), filed: union(B.filed_word, B.filed), perf: B.perf, column: B.column };
const rowRect = k => ROW.orig.map((v, i) => lerp(v, ROW.lift[i], k));
const toRow = (rect, x, y) => { const s = rect[2] / (ROW.crop[2] - ROW.crop[0]); return [rect[0] + (x - ROW.crop[0]) * s, rect[1] + (y - ROW.crop[1]) * s, s]; };
const toHold = (x, y) => [HOLD[0] + x * h0, HOLD[1] + y * h0];
function sweep(x0, y0, x1, y1, k, color, a = 1) {
  if (k <= 0) return;
  const w = (x1 - x0) * clamp(k);
  ctx.save(); ctx.globalAlpha = a; ctx.globalCompositeOperation = "screen"; ctx.fillStyle = color === "red" ? "rgba(244,63,94,0.40)" : "rgba(59,232,255,0.30)";
  ctx.beginPath(); ctx.roundRect(x0, y0, w, y1 - y0, 8); ctx.fill(); ctx.restore();
  ctx.save(); ctx.globalAlpha = a; ctx.fillStyle = color === "red" ? C.red : C.cyan; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 12; ctx.fillRect(x0, y1 - 2, w, 6); ctx.restore();
}
function rowHighlight(rect, box, k, color, a = 1, pad = 12) {
  const [x0, y0] = toRow(rect, box[0] - pad, box[1] - pad * 0.5), [x1, y1] = toRow(rect, box[0] + box[2] + pad, box[1] + box[3] + pad * 0.5);
  sweep(x0, y0, x1, y1, k, color, a);
}
function drawDimCard(dim) {
  ctx.drawImage(imgHold, HOLD[0], HOLD[1]);
  ctx.fillStyle = `rgba(6,3,12,${dim})`; ctx.fillRect(HOLD[0], HOLD[1], HOLD[2], HOLD[3]);
}
function drawRow(k) {
  const rect = rowRect(k);
  // shadow + cyan rim outside the row (the row's own pixels are drawn untouched on top)
  ctx.save(); ctx.shadowColor = "rgba(0,0,0,0.85)"; ctx.shadowBlur = 50 * k; ctx.shadowOffsetY = 22 * k; ctx.fillStyle = "#101010"; ctx.fillRect(rect[0], rect[1], rect[2], rect[3]); ctx.restore();
  ctx.save(); ctx.globalAlpha = k; ctx.strokeStyle = C.cyan; ctx.lineWidth = 4; ctx.shadowColor = C.cyan; ctx.shadowBlur = 24; ctx.beginPath(); ctx.roundRect(rect[0] - 7, rect[1] - 7, rect[2] + 14, rect[3] + 14, 16); ctx.stroke(); ctx.restore();
  if (k >= 1) ctx.drawImage(imgRow, ROW.lift[0], ROW.lift[1]);          // settled: 1:1, the Lanczos row pixels
  else { ctx.save(); ctx.imageSmoothingQuality = "high"; ctx.drawImage(imgRow, rect[0], rect[1], rect[2], rect[3]); ctx.restore(); }
  return rect;
}
function drawLock(t) {
  const k = clamp(easeOutBack(prog(t, T.lock0, T.lock0 + 0.42), 1.5), 0, 1.06);
  drawDimCard(0.72 * prog(t, T.lock0, T.lock0 + 0.3));
  const rect = drawRow(Math.min(1, k));
  T.lock.forEach((l, i) => {
    const nxt = T.lock[i + 1];
    const a = nxt && t >= nxt.t ? 0.35 : 1;                 // the newest fact is lit, older ones stay faintly marked
    rowHighlight(rect, BOX[l.key], prog(t, l.t, l.t + 0.28), "cyan", a);
  });
}
function drawProof(t) {
  drawDimCard(0.72);
  // the column header row stays lit, untouched, in place: it names the measure
  const cy0 = BOX.column[1] - 40, cy1 = BOX.column[1] + BOX.column[3] + 40;
  ctx.drawImage(imgHold, 0, cy0 * h0, HOLD[2], (cy1 - cy0) * h0, HOLD[0], HOLD[1] + cy0 * h0, HOLD[2], (cy1 - cy0) * h0);
  const k = clamp(easeOutBack(prog(t, T.cut_row, T.cut_row + 0.3), 1.5), 0, 1);
  const rect = drawRow(k);
  rowHighlight(rect, BOX.perf, prog(t, T.cut_row + 0.1, T.cut_row + 0.38), "red", 1, 16);
  const [hx0, hy0] = toHold(BOX.column[0] - 10, BOX.column[1] - 8), [hx1, hy1] = toHold(BOX.column[0] + BOX.column[2] + 10, BOX.column[1] + BOX.column[3] + 8);
  sweep(hx0, hy0, hx1, hy1, prog(t, T.cut_row + 0.55, T.cut_row + 0.8), "cyan");
  const aa = prog(t, T.cut_row + 0.7, T.cut_row + 0.95);
  if (aa > 0) {
    const f = `800 36px JBMono`, w = textW(R.text.asof, f), x = 490 - w / 2, y = ROW.lift[1] + ROW.lift[3] + 84;
    ctx.save(); ctx.globalAlpha = aa; ctx.font = f; ctx.lineJoin = "round"; ctx.lineWidth = 9; ctx.strokeStyle = "rgba(6,3,14,0.95)"; ctx.strokeText(R.text.asof, x, y);
    ctx.fillStyle = C.cyan; ctx.fillText(R.text.asof, x, y); ctx.restore(); rec("asof", x, y - 30, w, 36);
  }
}

function drawCaption(t) {
  if (t >= T.brand_big - 0.02) return;
  const cap = R.captions.find(c => t >= c.t0 && t < c.t1); if (!cap) return;
  const fs = 92, stroke = 20;
  const txt = cap.parts.map(p => p.text).join(" ");
  let s = fs; let w = textW(txt, `900 ${fs}px InterV`);
  if (w > 800) { s = Math.floor(fs * 800 / w); w = textW(txt, `900 ${s}px InterV`); }
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
  const lvl = FLOOR + TH, top = intcT.position.y + TH / 2;
  const spyTop = project(new THREE.Vector3(-TX, lvl, TW / 2)), inTop = project(new THREE.Vector3(TX, top, TW / 2));
  const bx = project(new THREE.Vector3(TX + TW / 2 + 0.45, lvl, TW / 2)), bxl = project(new THREE.Vector3(TX + TW / 2 + 0.45, top, TW / 2));
  ctx.save(); ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round";
  const tag = (txt, x, y, col) => { const f = `800 64px JBMono`, w = textW(txt, f); ctx.font = f; ctx.lineWidth = 12; ctx.strokeStyle = "rgba(6,3,14,0.92)"; ctx.strokeText(txt, x - w / 2, y); ctx.fillStyle = col; ctx.fillText(txt, x - w / 2, y); rec("tower_label", x - w / 2, y - 48, w, 52); };
  tag(R.text.line_label, clamp(spyTop[0], 140, 480), spyTop[1] - 34, C.cyan);
  tag(R.text.ticker, clamp(inTop[0], 500, 840), inTop[1] - 34, C.white);
  const bk = prog(t, T.gapnum - 0.1, T.gapnum + 0.25);
  if (t > T.hit + 0.15 && bk > 0) {
    const x = Math.min(bx[0], 900), y0 = bx[1], y1 = lerp(y0, bxl[1], easeOut(bk));
    ctx.strokeStyle = C.red; ctx.lineWidth = 6; ctx.shadowColor = C.red; ctx.shadowBlur = 16; ctx.beginPath();
    ctx.moveTo(x - 22, y0); ctx.lineTo(x, y0); ctx.lineTo(x, y1); ctx.lineTo(x - 22, y1); ctx.stroke();
  }
  ctx.restore();
  if (t >= T.hit) {
    const k = prog(t, T.hit, T.hit + 0.18);
    let sc = k < 1 ? lerp(1.3, 1.0, easeIn(k)) : 1 + 0.18 * Math.exp(-(t - T.hit - 0.18) * 14) * Math.sin((t - T.hit - 0.18) * 30);
    if (t >= T.gapnum && t < T.gapnum + 0.3) sc *= 1 + 0.08 * Math.sin(prog(t, T.gapnum, T.gapnum + 0.3) * Math.PI);
    drawCounter(R.text.counter, R.text.counter_unit, 470, sc, clamp(k * 3), { text: R.text.sink_label, a: prog(t, T.hit + 0.12, T.hit + 0.35) }, C.white, 490);
  }
}

function drawEnd(t) {
  const a = bigA(t); if (a <= 0) return null;
  const tile = 118, fs = 70, font = `900 ${fs}px InterV`;
  const tw = textW(R.text.wordmark, font), tot = tile + 22 + tw;
  const pop = 1 + 0.12 * (1 - easeOutBack(prog(t, T.brand_big - 0.05, T.brand_big + 0.3)));
  const x0 = W / 2 - tot / 2, y0 = 300;
  ctx.save(); ctx.globalAlpha = a; ctx.translate(W / 2, y0 + tile / 2); ctx.scale(pop, pop); ctx.translate(-W / 2, -(y0 + tile / 2));
  ctx.shadowColor = "rgba(59,232,255,0.6)"; ctx.shadowBlur = 30; ctx.drawImage(MARK, x0, y0, tile, tile); ctx.shadowBlur = 0;
  ctx.font = font; ctx.fillStyle = C.white; ctx.textBaseline = "middle"; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(6,3,14,0.85)";
  ctx.strokeText(R.text.wordmark, x0 + tile + 22, y0 + tile / 2 + 4); ctx.fillText(R.text.wordmark, x0 + tile + 22, y0 + tile / 2 + 4); ctx.restore();
  rec("end_brand", x0, y0, tot, tile);
  // the domain types on, letter by letter
  const f2 = `800 66px InterV`, full = R.text.site, w2 = textW(full, f2);
  const n = Math.round(full.length * prog(t, T.brand_big + 0.15, T.brand_big + 0.75));
  if (n > 0) {
    const s = full.slice(0, n), cur = n < full.length && Math.floor(t * 8) % 2 === 0;
    ctx.save(); ctx.globalAlpha = a; ctx.font = f2; ctx.textBaseline = "alphabetic"; ctx.lineWidth = 12; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.lineJoin = "round";
    ctx.strokeText(s, W / 2 - w2 / 2, 1392); ctx.fillStyle = C.cyan; ctx.fillText(s, W / 2 - w2 / 2, 1392);
    if (cur) ctx.fillRect(W / 2 - w2 / 2 + textW(s, f2) + 6, 1340, 6, 60);
    ctx.restore(); rec("end_site", W / 2 - w2 / 2, 1342, w2, 64);
  }
  const da = a * prog(t, T.disclaim - 0.15, T.disclaim + 0.25);
  if (da > 0) {
    const f3 = `600 46px InterV`, w3 = textW(R.text.disclaimer, f3), dy = 1472 - 14 * (1 - easeOut(prog(t, T.disclaim - 0.15, T.disclaim + 0.25)));
    ctx.save(); ctx.globalAlpha = da; ctx.font = f3; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(6,3,14,0.9)"; ctx.lineJoin = "round"; ctx.strokeText(R.text.disclaimer, W / 2 - w3 / 2, dy); ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.fillText(R.text.disclaimer, W / 2 - w3 / 2, dy); ctx.restore();
    rec("end_disclaimer", W / 2 - w3 / 2, dy - 36, w3, 46);
  }
  const ox = W / 2 + (x0 - W / 2) * pop, oy = y0 + tile / 2 + (y0 - (y0 + tile / 2)) * pop;
  return [ox, oy, tile * pop, tile * pop];
}

// ---------------------------------------------------------------------------------------------- frame
function blurSpans(t) {
  return (t >= T.flip0 - 0.02 && t <= T.flip1 + 0.04) || (t >= T.hit && t <= T.hit + 0.25) || (t >= T.stamp - 0.24 && t <= T.stamp + 0.03) || (t >= T.loop0 && t < LOOP_END - 0.05) || (t >= T.chip - 0.1 && t <= T.chip + 0.12);
}
function render3D(t) {
  const M = blurSpans(t) ? 7 : 1; const shutter = 0.5 / FPS;
  for (let i = 0; i < M; i++) {
    const ts = M === 1 ? t : t - shutter / 2 + shutter * i / (M - 1);
    world(ts); composer.render();
    actx.globalAlpha = 1 / (i + 1); actx.drawImage(glc, 0, 0);
  }
  actx.globalAlpha = 1; world(t);   // leave the world at t for projections
}

window.renderFrame = (t) => {
  TEXTS = [];
  const p = phase(t);
  render3D(t);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, W, H);
  const sh = shakeAt(t);
  ctx.save(); ctx.translate(sh[0] * 0.6, sh[1] * 0.6); ctx.drawImage(acc, 0, 0); ctx.restore();
  if (p === "hold") {
    // the real card, flat and untouched, pixel for pixel the Lanczos-scaled capture
    ctx.save(); ctx.strokeStyle = "rgba(59,232,255,0.55)"; ctx.lineWidth = 3; ctx.shadowColor = C.cyan; ctx.shadowBlur = 18; ctx.strokeRect(HOLD[0] - 4, HOLD[1] - 4, HOLD[2] + 8, HOLD[3] + 8); ctx.restore();
    ctx.drawImage(imgHold, HOLD[0], HOLD[1]);   // drawn last: nothing touches the card pixels
  }
  if (p === "lock") drawLock(t);
  if (p === "row") drawProof(t);
  if (p === "hook" || p === "flip" || p === "loop") { drawHeadline(t); drawHookOverlay(t); }
  if (p === "sink") drawSinkOverlay(t);
  const bigRect = (p === "end" || p === "loop") ? drawEnd(t) : null;
  if (p !== "hook" && p !== "loop" && p !== "sink") drawCaption(t);
  if (t >= T.hit && t < T.hit + 3 / FPS) { const f = Math.floor((t - T.hit) * FPS + 1e-6); ctx.fillStyle = `rgba(255,255,255,${[0.45, 0.28, 0.12][f] ?? 0})`; ctx.fillRect(0, 0, W, H); }
  const kick = drawKicker(t);
  const mark = bigRect && bigA(t) >= 0.5 ? bigRect : kick;
  return { phase: p, mark, texts: TEXTS };
};
window.sceneReady = true;
