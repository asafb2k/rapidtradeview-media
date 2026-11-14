// SHOWCASE "studio" look (default since day 2): a generic, logo-free phone built in code (aluminium frame, glass front,
// side keys, plain punch-hole), lit by the CC0 Poly Haven studio_small_09 HDRI plus a cool key and rim, standing on the
// brand ground (near-black blue-green, a soft green key pool, contact shadow, vignette, grain on the ground only).
// The screen is the recorded app frame: unlit, never tone mapped, exact colours. Ported from the 2026-11-14 look test
// (.ops/app-showcase/lookdev-2026-11-14/studio-3d/scene) with the judges' changes.
//
// API (all coordinates in 1080x1920 output px, screen points in capture px):
//   window.probe(cfg)          -> measurements only (phone/screen rect, projected points), no pixels
//   window.frame({subs, ov})   -> renders every sub-frame cfg at 2x, averages them in linear light on the GPU,
//                                 box-reduces 2:1, composites the 2D overlay and returns {b64: RGBA bottom-up, m}
// cfg: {screen: url, z, uv:[u,v], A:[x,y], yaw, pitch, camPitch, sheen, tap:{u,v,scale,alpha,ripple}, seed}
import * as THREE from "three";
import { RGBELoader } from "three/addons/loaders/RGBELoader.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeVertices } from "three/addons/utils/BufferGeometryUtils.js";

const W = 1080, H = 1920, SS = 2, RW = W * SS, RH = H * SS;
try {
const SPEC = await (await fetch("/run/scene.json")).json();
const L = SPEC.look;
const FOV = L.fov ?? 20;
for (const w of [800, 900]) await document.fonts.load(`${w} 100px InterV`);
const BRAND = await (await fetch("/brand/brand-mark.json")).json();

// ------------------------------------------------------------------ renderer
const glc = document.getElementById("gl");
const renderer = new THREE.WebGLRenderer({ canvas: glc, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
renderer.setPixelRatio(SS); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.AgXToneMapping; renderer.toneMappingExposure = 1.0;
renderer.autoClear = false;
const gl = renderer.getContext();
const dbg = gl.getExtension("WEBGL_debug_renderer_info");
window.glRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "?";
const floatBlend = !!gl.getExtension("EXT_float_blend") && !!gl.getExtension("EXT_color_buffer_float");
window.floatBlend = floatBlend;
const MAXANI = renderer.capabilities.getMaxAnisotropy();

const camera = new THREE.PerspectiveCamera(FOV, W / H, 50, 6000);
camera.rotation.order = "YXZ";
const FPX = (H / 2) / Math.tan(THREE.MathUtils.degToRad(FOV / 2));   // focal length in output px

const pmrem = new THREE.PMREMGenerator(renderer);
const hdr = await new RGBELoader().loadAsync("/hdri/studio_small_09_2k.hdr");
const envTex = pmrem.fromEquirectangular(hdr).texture; hdr.dispose();
const phoneScene = new THREE.Scene(); phoneScene.environment = envTex;
phoneScene.environmentIntensity = L.envi; phoneScene.environmentRotation.set(0, L.envrot, 0);
// the env map is bound per material (scene.environment would override each material's envMapIntensity)
const envRot = new THREE.Euler(0, L.envrot, 0);

// ------------------------------------------------------------------ phone geometry (mm)
const CAP_W = SPEC.cap[0], CAP_H = SPEC.cap[1];
const SCR_W = 68, SCR_H = SCR_W * CAP_H / CAP_W;
const BZ = 1.45, LIP = 0.75;
const BW = SCR_W + 2 * (BZ + LIP), BH = SCR_H + 2 * (BZ + LIP), DEPTH = 8.2;
const NEXP = 3.2;
const RB = 11.6, RG = RB - LIP, RS = RG - BZ;
window.phoneMM = { BW, BH, SCR_W, SCR_H, BZ, LIP };
function rrShape(w, h, r, n = NEXP, seg = 32) {
  const pts = [], cx = [w / 2 - r, -w / 2 + r, -w / 2 + r, w / 2 - r], cy = [h / 2 - r, h / 2 - r, -h / 2 + r, -h / 2 + r];
  for (let c = 0; c < 4; c++) for (let i = 0; i <= seg; i++) {
    const a = c * Math.PI / 2 + i / seg * Math.PI / 2, ca = Math.cos(a), sa = Math.sin(a);
    pts.push(new THREE.Vector2(cx[c] + Math.sign(ca) * Math.pow(Math.abs(ca), 2 / n) * r, cy[c] + Math.sign(sa) * Math.pow(Math.abs(sa), 2 / n) * r));
  }
  return new THREE.Shape(pts);
}
function smooth(geo) { geo.deleteAttribute("uv"); geo.deleteAttribute("normal"); const g = mergeVertices(geo, 1e-4); g.computeVertexNormals(); return g; }
function planeUV(geo, w, h) { const p = geo.attributes.position, uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) { uv[2 * i] = p.getX(i) / w + .5; uv[2 * i + 1] = p.getY(i) / h + .5; }
  geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2)); return geo; }
function canvasTex(w, h, draw) { const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; }

const phone = new THREE.Group(); phoneScene.add(phone);
const frameMat = new THREE.MeshPhysicalMaterial({ color: L.frame, metalness: 1, roughness: L.rough, envMap: envTex, envMapIntensity: L.envi });
frameMat.envMapRotation.copy(envRot);
let bodyMesh;
{ const bs = 1.15, bt = L.bevel_t ?? 1.35;
  const g = new THREE.ExtrudeGeometry(rrShape(BW - 2 * bs, BH - 2 * bs, RB - bs), { depth: DEPTH - 2 * bt, bevelEnabled: true,
    bevelThickness: bt, bevelSize: bs, bevelSegments: 12, curveSegments: 4 });
  g.center(); bodyMesh = new THREE.Mesh(smooth(g), frameMat); phone.add(bodyMesh); }
const ZF = DEPTH / 2;
// front glass: black, almost no environment on the face (the inner border must read black, <= 14/255)
const glassMat = new THREE.MeshPhysicalMaterial({ color: L.glass, roughness: 0.05, metalness: 0, clearcoat: L.glass_clearcoat,
  clearcoatRoughness: 0.03, envMap: envTex, envMapIntensity: L.glass_env });
glassMat.envMapRotation.copy(envRot);
let ZG;
{ const gb = 0.5, gt = 0.32;
  const g = new THREE.ExtrudeGeometry(rrShape(BW - 2 * LIP - 2 * gb, BH - 2 * LIP - 2 * gb, RG - gb), { depth: 0.1, bevelEnabled: true,
    bevelThickness: gt, bevelSize: gb, bevelSegments: 8, curveSegments: 4 });
  g.center(); const glass = new THREE.Mesh(smooth(g), glassMat); glass.position.z = ZF + 0.12; phone.add(glass);
  ZG = ZF + 0.12 + 0.05 + gt; }
for (const [y, len] of [[46, 24], [20, 12]]) {        // volume rocker + power key, right edge; no logo anywhere
  const k = new THREE.Mesh(new RoundedBoxGeometry(1.4, len, 2.4, 5, 0.6), frameMat); k.position.set(BW / 2 - 0.15, y, 0); phone.add(k); }

const scrGeo = planeUV(new THREE.ShapeGeometry(rrShape(SCR_W, SCR_H, RS), 32), SCR_W, SCR_H);
const scrMat = new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false });
const screen = new THREE.Mesh(scrGeo, scrMat); screen.position.z = ZG + 0.02; phone.add(screen);
const hole = new THREE.Group(); phone.add(hole);
if (SPEC.punch_hole) { const [pu, pv] = SPEC.punch_hole, PH_Y = SCR_H / 2 - pv / CAP_H * SCR_H, PH_X = (pu / CAP_W - 0.5) * SCR_W;
  const lens = new THREE.Mesh(new THREE.CircleGeometry(1.3, 48), new THREE.MeshBasicMaterial({ color: 0x000000, toneMapped: false }));
  lens.position.set(PH_X, PH_Y, ZG + 0.05); hole.add(lens);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.50, 0.66, 48), new THREE.MeshBasicMaterial({ color: 0x101318, toneMapped: false }));
  ring.position.set(PH_X, PH_Y, ZG + 0.06); hole.add(ring); }
const sheenTex = canvasTex(1024, 1024, (g, w, h) => { const gr = g.createLinearGradient(0, h, w, 0);
  gr.addColorStop(0, "rgba(255,255,255,0)"); gr.addColorStop(.40, "rgba(255,255,255,0)"); gr.addColorStop(.5, "rgba(255,255,255,1)");
  gr.addColorStop(.60, "rgba(255,255,255,0)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, w, h); });
sheenTex.repeat.set(0.7, 0.7);
const sheenMat = new THREE.MeshBasicMaterial({ map: sheenTex, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false });
const sheen = new THREE.Mesh(scrGeo.clone(), sheenMat); sheen.position.z = ZG + 0.09; phone.add(sheen);
// touch disc: drawn on a plane on the glass so it follows the phone in perspective
const tapCv = document.createElement("canvas"); tapCv.width = tapCv.height = 512;
const tapTex = new THREE.CanvasTexture(tapCv); tapTex.colorSpace = THREE.SRGBColorSpace;
const TAP_MM = 26;
const tap = new THREE.Mesh(new THREE.PlaneGeometry(TAP_MM, TAP_MM), new THREE.MeshBasicMaterial({ map: tapTex, transparent: true, depthWrite: false, toneMapped: false }));
tap.position.z = ZG + 0.12; tap.visible = false; phone.add(tap);
function drawTap(st, sPx) {   // st: {scale, alpha, ripple 0..1}; sPx = output px per mm (ring 2 px, shadow 12 px)
  const g = tapCv.getContext("2d"), k = 512 / TAP_MM; g.clearRect(0, 0, 512, 512);
  const r = (SPEC.tap_d_mm / 2) * k * (st.scale ?? 1), ring = (st.ring_px ?? 2) / sPx * k;
  g.save(); g.translate(256, 256);
  if (st.ripple > 0 && st.ripple < 1) { g.globalAlpha = st.alpha * (1 - st.ripple) * 0.85; g.strokeStyle = "#fff"; g.lineWidth = ring;
    g.beginPath(); g.arc(0, 0, r * (1 + 1.3 * st.ripple), 0, 7); g.stroke(); }
  g.globalAlpha = st.alpha;
  g.shadowColor = "rgba(0,0,0,0.25)"; g.shadowBlur = 12 / sPx * k;
  g.fillStyle = "rgba(255,255,255,0.80)"; g.beginPath(); g.arc(0, 0, r, 0, 7); g.fill();
  g.shadowColor = "transparent"; g.globalAlpha = st.ring_full ? 1 : Math.min(1, 2 * st.alpha); g.strokeStyle = "rgba(255,255,255,0.95)"; g.lineWidth = ring;
  g.beginPath(); g.arc(0, 0, r + ring / 2, 0, 7); g.stroke();
  g.restore(); tapTex.needsUpdate = true;
}
const key = new THREE.DirectionalLight(L.key_col, L.key); key.position.set(-0.55, 0.75, 0.6); phoneScene.add(key);
const rim = new THREE.DirectionalLight(L.rim_col, L.rim); rim.position.set(0.8, 0.25, -0.7); phoneScene.add(rim);

// ------------------------------------------------------------------ brand ground (screen space, written as sRGB)
const quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2)); const quadScene = new THREE.Scene(); quadScene.add(quad);
const VS = "varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }";
const c3 = a => new THREE.Vector3(a[0] / 255, a[1] / 255, a[2] / 255);
const bgMat = new THREE.ShaderMaterial({ vertexShader: VS, depthTest: false, depthWrite: false,
  uniforms: { wallTop: { value: c3(L.wall_top) }, wallLow: { value: c3(L.wall_low) }, floorC: { value: c3(L.floor) },
    poolC: { value: c3(L.pool) }, poolW: { value: L.pool_w }, poolDy: { value: L.pool_dy ?? -0.06 }, vig: { value: L.vig }, grain: { value: L.grain }, seed: { value: 0 },
    base: { value: new THREE.Vector2(540, 1468) }, ctr: { value: new THREE.Vector2(540, 893) }, pw: { value: 535 }, ph: { value: 1150 },
    shadowA: { value: L.shadow_a }, shadowBlur: { value: L.shadow_blur }, horizon: { value: 1468 } },
  fragmentShader: `uniform vec3 wallTop, wallLow, floorC, poolC; uniform float poolW, poolDy, vig, grain, seed, pw, ph, shadowA, shadowBlur, horizon;
  uniform vec2 base, ctr; varying vec2 vUv;
  float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423) + seed); p += dot(p, p.yx + 19.19); return fract((p.x + p.y) * p.x); }
  void main(){
    vec2 px = vec2(vUv.x * 1080.0, (1.0 - vUv.y) * 1920.0);
    vec3 c = px.y < horizon ? mix(wallTop, wallLow, smoothstep(0.0, horizon, px.y))
                            : mix(wallLow, floorC, smoothstep(horizon, 1920.0, px.y));
    vec2 d = (px - (ctr + vec2(0.0, poolDy * ph))) / vec2(0.62 * pw, 0.46 * ph);
    c = mix(c, poolC, poolW * exp(-0.5 * dot(d, d)));
    float r = length((vUv - 0.5) * vec2(1.0, 1.15)) * 1.55;
    c *= 1.0 - vig * smoothstep(0.35, 1.0, r);
    // contact shadow: a soft capsule under the phone's base (1.1x its width), ~80 px blur
    float hx = 0.55 * pw - 0.5 * shadowBlur; vec2 q = px - (base + vec2(0.0, 6.0));
    float sd = length(vec2(max(abs(q.x) - max(hx, 1.0), 0.0), q.y)) - 6.0;
    c *= 1.0 - shadowA * exp(-0.5 * pow(max(sd, 0.0) / (0.5 * shadowBlur), 2.0));
    c += (hash(floor(px * 2.0)) - 0.5) * grain;
    gl_FragColor = vec4(c, 1.0);
  }` });

// ------------------------------------------------------------------ accumulation (linear light) + 2:1 reduce + overlay
const grab = new THREE.FramebufferTexture(RW, RH);
const accRT = new THREE.WebGLRenderTarget(RW, RH, { type: floatBlend ? THREE.FloatType : THREE.HalfFloatType, depthBuffer: false });
accRT.texture.minFilter = accRT.texture.magFilter = THREE.NearestFilter; accRT.texture.generateMipmaps = false;
const accMat = new THREE.ShaderMaterial({ vertexShader: VS, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending, transparent: true,
  uniforms: { src: { value: grab } },
  fragmentShader: `uniform sampler2D src; varying vec2 vUv;
  vec3 s2l(vec3 c){ return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
  void main(){ gl_FragColor = vec4(s2l(texture2D(src, vUv).rgb), 1.0); }` });
const outRT = new THREE.WebGLRenderTarget(W, H, { type: THREE.UnsignedByteType, depthBuffer: false });
const ov = document.getElementById("ov"); ov.width = RW; ov.height = RH; const ctx = ov.getContext("2d");
const ovTex = new THREE.CanvasTexture(ov); ovTex.premultiplyAlpha = true; ovTex.minFilter = ovTex.magFilter = THREE.NearestFilter; ovTex.generateMipmaps = false;
const finMat = new THREE.ShaderMaterial({ vertexShader: VS, depthTest: false, depthWrite: false,
  uniforms: { acc: { value: accRT.texture }, ovt: { value: ovTex }, invN: { value: 1 }, src: { value: new THREE.Vector2(RW, RH) } },
  fragmentShader: `uniform sampler2D acc, ovt; uniform float invN; uniform vec2 src;
  vec3 l2s(vec3 c){ c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
  void main(){ vec2 p = floor(gl_FragCoord.xy) * 2.0; vec3 s = vec3(0.0); vec4 o = vec4(0.0);
    for (int i = 0; i < 2; i++) for (int j = 0; j < 2; j++) { vec2 uv = (p + vec2(float(i) + 0.5, float(j) + 0.5)) / src;
      s += l2s(texture2D(acc, uv).rgb * invN); o += texture2D(ovt, uv); }
    s *= 0.25; o *= 0.25;
    gl_FragColor = vec4(s * (1.0 - o.a) + o.rgb, 1.0); }` });
function quadPass(mat, target) { quad.material = mat; renderer.setRenderTarget(target); renderer.render(quadScene, quadCam); }

// ------------------------------------------------------------------ screen textures (cached by url)
const texCache = new Map();
async function screenTex(url) {
  if (texCache.has(url)) return texCache.get(url);
  const img = new Image(); img.src = url; await img.decode();
  const t = new THREE.Texture(img); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = MAXANI;
  t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter; t.generateMipmaps = true; t.needsUpdate = true;
  if (texCache.size > 10) { const [k, v] = texCache.entries().next().value; v.dispose(); texCache.delete(k); }
  texCache.set(url, t); return t;
}

// ------------------------------------------------------------------ overlay (one typeface: Inter 800)
function makeMark(size) { const cv = document.createElement("canvas"); cv.width = cv.height = size;
  const g = cv.getContext("2d"); const k = size / BRAND.viewBox; g.scale(k, k);
  const bg = g.createLinearGradient(BRAND.bg.x1, BRAND.bg.y1, BRAND.bg.x2, BRAND.bg.y2); for (const s of BRAND.bg.stops) bg.addColorStop(s.offset, s.color);
  g.fillStyle = bg; g.beginPath(); g.roundRect(0, 0, 1024, 1024, BRAND.tileRadius * 1024); g.fill();
  const b = BRAND.bbox; const mg = g.createLinearGradient(b.x, b.y + b.h, b.x + b.w, b.y); for (const s of BRAND.mark.stops) mg.addColorStop(s.offset, s.color);
  g.fillStyle = mg; g.fill(new Path2D(BRAND.path), "evenodd"); return cv; }
const MARK = makeMark(512);
const FONT = (sz) => `800 ${sz}px InterV`;
function pill(o, boxes) { const h = o.h, pad = Math.round(h * 0.125), tile = h - 2 * pad, fs = h * 0.56;
  ctx.font = FONT(fs); ctx.letterSpacing = `${-0.01 * fs}px`; const tw = ctx.measureText("RapidTradeView").width;
  const bw = pad + tile + 0.27 * h + tw + 0.42 * h, x = o.cx - bw / 2, y = o.top;
  ctx.save(); ctx.shadowColor = "rgba(0,0,0,0.35)"; ctx.shadowBlur = 20; ctx.shadowOffsetY = 5;
  ctx.fillStyle = "rgba(6,14,12,0.86)"; ctx.beginPath(); ctx.roundRect(x, y, bw, h, h / 2); ctx.fill();
  ctx.shadowColor = "transparent"; ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.drawImage(MARK, x + pad, y + pad, tile, tile);
  ctx.fillStyle = "#fff"; ctx.textBaseline = "middle"; ctx.fillText("RapidTradeView", x + pad + tile + 0.27 * h, y + h / 2 + 0.03 * h);
  ctx.restore(); boxes.pill = [x, y, bw, h]; }
// a line of words: o = {words:[{t, color, alpha, blur}], size, top (cap top), cx, maxRight, track, chip:{pad,alpha}}
function line(o, name, boxes) { const fs = o.size; ctx.save(); ctx.font = FONT(fs); ctx.letterSpacing = `${(o.track ?? 0) * fs}px`;
  ctx.textBaseline = "alphabetic"; const sp = ctx.measureText(" ").width;
  const ws = o.words.map(w => ctx.measureText(w.t).width); const tot = ws.reduce((a, b) => a + b, 0) + sp * (ws.length - 1);
  let cx = o.cx; if (o.maxRight && cx + tot / 2 > o.maxRight) cx = o.maxRight - tot / 2;
  const capH = fs * 0.727, base = o.top + capH;
  let x = cx - tot / 2;
  if (o.chip && o.chip.alpha > 0) { const px = o.chip.padx * fs, py = o.chip.pady * fs, ch = capH + fs * 0.21 + 2 * py;
    ctx.save(); ctx.globalAlpha = o.chip.alpha; ctx.shadowColor = "rgba(0,0,0,0.35)"; ctx.shadowBlur = 18; ctx.shadowOffsetY = 4;
    ctx.fillStyle = "rgba(6,14,12,0.88)"; ctx.beginPath(); ctx.roundRect(x - px, o.top - py, tot + 2 * px, ch, ch / 2); ctx.fill();
    ctx.shadowColor = "transparent"; ctx.strokeStyle = "rgba(255,255,255,0.10)"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.restore();
    boxes[name + "_chip"] = [x - px, o.top - py, tot + 2 * px, ch]; }
  if (o.shadow) { ctx.shadowColor = "rgba(0,0,0,0.45)"; ctx.shadowBlur = 18; ctx.shadowOffsetY = 3; }
  o.words.forEach((w, i) => { if (w.alpha > 0) { ctx.globalAlpha = w.alpha; ctx.filter = w.blur > 0.05 ? `blur(${w.blur}px)` : "none";
      ctx.fillStyle = w.color; ctx.fillText(w.t, x, base); } x += ws[i] + sp; });
  ctx.restore(); boxes[name] = [cx - tot / 2, o.top, tot, capH + fs * 0.21]; }
function drawOverlay(o) { const boxes = {};
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, RW, RH); ctx.setTransform(SS, 0, 0, SS, 0, 0);
  if (o.pill) pill(o.pill, boxes);
  for (const [name, ln] of Object.entries(o.lines || {})) line(ln, name, boxes);
  ovTex.needsUpdate = true; return boxes; }

// ------------------------------------------------------------------ camera + measurements
const D2R = THREE.MathUtils.degToRad;
const uvLocal = (u, v, z = ZG + 0.02) => new THREE.Vector3((u / CAP_W - 0.5) * SCR_W, (0.5 - v / CAP_H) * SCR_H, z);
function proj(p) { const q = p.clone().project(camera); return [(q.x + 1) / 2 * W, (1 - q.y) / 2 * H]; }
const bodyPts = (() => { const pos = bodyMesh.geometry.attributes.position, out = [], v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += 3) { v.fromBufferAttribute(pos, i); out.push(v.clone()); } return out; })();
function rectOfPts(pts, mesh) { let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; mesh.updateMatrixWorld(true);
  for (const p of pts) { const [x, y] = proj(p.clone().applyMatrix4(mesh.matrixWorld)); x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1]; }
const scrPts = (() => { const pos = scrGeo.attributes.position, out = [], v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i); out.push(v.clone()); } return out; })();
function setup(cfg) {
  phone.position.set(0, 0, 0); phone.rotation.set(D2R(cfg.pitch ?? 0), D2R(cfg.yaw ?? 0), D2R(cfg.roll ?? 0), "YXZ"); phone.updateMatrixWorld(true);
  const s = cfg.z * SPEC.s0;                                   // output px per mm at the screen plane
  camera.rotation.set(D2R(cfg.camPitch ?? 0), 0, 0); camera.updateMatrixWorld();
  const P = phone.localToWorld(uvLocal(cfg.uv[0], cfg.uv[1]));
  const dist = FPX / s, A = cfg.A;
  const off = new THREE.Vector3((A[0] - W / 2) / FPX * dist, (H / 2 - A[1]) / FPX * dist, -dist).applyQuaternion(camera.quaternion);
  camera.position.copy(P).sub(off); camera.updateMatrixWorld(true); camera.updateProjectionMatrix();
  const m = { phone_rect: rectOfPts(bodyPts, bodyMesh), screen_rect: rectOfPts(scrPts, screen) };
  const pr = cfg.probe || cfg.uv; const a = proj(phone.localToWorld(uvLocal(pr[0], pr[1]))), b = proj(phone.localToWorld(uvLocal(pr[0] + 100, pr[1])));
  const c = proj(phone.localToWorld(uvLocal(pr[0], pr[1] + 100)));
  m.px_per_cap = [Math.hypot(b[0] - a[0], b[1] - a[1]) / 100, Math.hypot(c[0] - a[0], c[1] - a[1]) / 100];
  m.pts = (cfg.points || []).map(([u, v]) => proj(phone.localToWorld(uvLocal(u, v))).map(x => Math.round(x * 100) / 100));
  return m;
}
window.probe = (cfg) => setup(cfg);
window.probeMany = (cfgs) => cfgs.map(c => setup(c));

async function renderSub(cfg) {
  const m = setup(cfg);
  scrMat.map = await screenTex(cfg.screen); scrMat.needsUpdate = true;
  sheenMat.opacity = cfg.sheen ?? 0;
  sheenTex.offset.set(0.15 - phone.rotation.y * 0.8, 0.2 + phone.rotation.x * 0.6);
  hole.visible = !!SPEC.punch_hole;
  if (cfg.tap && cfg.tap.alpha > 0) { const p = uvLocal(cfg.tap.u, cfg.tap.v, ZG + 0.12); tap.position.set(p.x, p.y, p.z); tap.visible = true;
    drawTap(cfg.tap, FPX / camera.position.distanceTo(phone.localToWorld(p.clone()))); } else tap.visible = false;
  // ground follows the phone's projected rect
  const r = m.phone_rect, pw = r[2] - r[0], ph = r[3] - r[1];
  const u = bgMat.uniforms; u.ctr.value.set((r[0] + r[2]) / 2, (r[1] + r[3]) / 2); u.pw.value = pw; u.ph.value = ph;
  const bc = proj(phone.localToWorld(new THREE.Vector3(0, -BH / 2, 0))); u.base.value.set(bc[0], bc[1]);
  u.horizon.value = Math.min(Math.max(bc[1], 600), 1900); u.seed.value = cfg.seed ?? 0.37;
  renderer.setRenderTarget(null); renderer.setClearColor(0x000000, 1); renderer.clear();
  quad.material = bgMat; renderer.render(quadScene, quadCam);
  renderer.clearDepth(); renderer.render(phoneScene, camera);
  return m;
}

window.frame = async (job) => {
  const t0 = performance.now(); let mid = null; const n = job.subs.length;
  for (let k = 0; k < n; k++) {
    const m = await renderSub(job.subs[k]); if (k === Math.floor(n / 2)) mid = m;
    renderer.copyFramebufferToTexture(grab);
    if (k === 0) { renderer.setRenderTarget(accRT); renderer.setClearColor(0x000000, 1); renderer.clear(); }
    quadPass(accMat, accRT);
  }
  const boxes = drawOverlay(job.ov || {});
  finMat.uniforms.invN.value = 1 / n; quadPass(finMat, outRT);
  const buf = new Uint8Array(W * H * 4); renderer.readRenderTargetPixels(outRT, 0, 0, W, H, buf);
  renderer.setRenderTarget(null);
  let s = ""; const CH = 0x8000; for (let i = 0; i < buf.length; i += CH) s += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
  return { b64: btoa(s), m: { ...mid, boxes, subs: n, ms: Math.round(performance.now() - t0) } };
};
window.sceneReady = true;
} catch (e) { window.sceneError = String(e && e.stack || e); }
