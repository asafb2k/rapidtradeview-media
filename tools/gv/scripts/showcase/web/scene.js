// SHOWCASE by RapidTradeView: one app feature filmed in a generic 3D phone. The phone screen is the recorded take,
// frame by frame, as an unlit texture (no tone mapping, no bloom, no grain, no grade): the app's own pixels. A dark
// plinth (a dock the phone stands in) hides everything below the logged window; captions sit on its front face. Brand
// pill, headline and end text are a 2D layer that never covers the screen. window.renderFrame(i) draws frame i and
// returns what QA needs (projected screen window, plinth edge, keep-out visibility, text boxes, visible app text).
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { Reflector } from "three/addons/objects/Reflector.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const R = await (await fetch("/run/render.json")).json();
const W = R.W, H = R.H, FPS = R.fps, T = R.T, SS = R.supersample;
const SRC_W = R.src.w, SRC_H = R.src.h, VP = R.window.v_plinth;
const C = { cyan: "#3BE8FF", white: "#FFFFFF", accent: R.accent || "#6EE7A8" };
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, k) => a + (b - a) * k;
const prog = (t, a, b) => clamp((t - a) / (b - a));
const easeIO = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
const easeO = x => 1 - Math.pow(1 - x, 3);
const easeOutBack = (x, s = 1.6) => { x -= 1; return 1 + (s + 1) * x * x * x + s * x * x; };
const EASE = { io: easeIO, o: easeO, lin: x => x, i: x => x * x * x };
const deg = THREE.MathUtils.degToRad;

await Promise.all(['400 100px "Archivo Black"', '900 100px InterV', '800 100px InterV', '600 100px InterV'].map(f => document.fonts.load(f)));

// ------------------------------------------------------------------------------------------------ brand mark tile
function makeMark(size) {
  const cv = document.createElement("canvas"); cv.width = cv.height = size;
  const g = cv.getContext("2d"); const k = size / R.mark.viewBox; g.scale(k, k);
  const bg = g.createLinearGradient(R.mark.bg.x1, R.mark.bg.y1, R.mark.bg.x2, R.mark.bg.y2);
  for (const s of R.mark.bg.stops) bg.addColorStop(s.offset, s.color);
  g.fillStyle = bg; g.beginPath(); g.roundRect(0, 0, 1024, 1024, R.mark.tileRadius * 1024); g.fill();
  const b = R.mark.bbox; const mg = g.createLinearGradient(b.x, b.y + b.h, b.x + b.w, b.y);
  for (const s of R.mark.mark.stops) mg.addColorStop(s.offset, s.color);
  g.fillStyle = mg; g.fill(new Path2D(R.mark.path), "evenodd");
  return cv;
}
const MARK = makeMark(512);

// ------------------------------------------------------------------------------------------------ renderer + scene
const glc = document.getElementById("gl");
const renderer = new THREE.WebGLRenderer({ canvas: glc, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
renderer.setPixelRatio(SS); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NoToneMapping;          // the screen keeps the app's own colours
const dbg = renderer.getContext().getExtension("WEBGL_debug_renderer_info");
window.glRenderer = dbg ? renderer.getContext().getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "?";
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(R.fov, W / H, 0.05, 200);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;   // reflections on the metal frame only
scene.environmentIntensity = 0.32;

// units: 1 = 1000 source px; the screen centre is the origin; source (u, v) -> world (x, y) on the screen plane
const SW = SRC_W / 1000, SH = SRC_H / 1000, BZ = R.phone.bezel, PD = R.phone.depth;
const ZS = PD / 2 + 0.0012;
const uv2w = (u, v, z = ZS) => new THREE.Vector3((u - SRC_W / 2) / 1000, (SRC_H / 2 - v) / 1000, z);
const YP = (SRC_H / 2 - VP) / 1000;                    // plinth top (world y): screen rows v >= VP are inside the dock

// background: graphite void, a soft lift behind the phone
const bg = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShaderMaterial({
  depthWrite: false,
  uniforms: { lift: { value: 1.0 } },
  vertexShader: `varying vec3 wp; void main(){ vec4 w = modelMatrix*vec4(position,1.0); wp = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }`,
  fragmentShader: `varying vec3 wp; uniform float lift; void main(){
    float r = length((wp.xy - vec2(-0.25, 0.9)) * vec2(1.0, 0.8));
    vec3 c = mix(vec3(0.0080,0.0100,0.0150), vec3(0.0017,0.0020,0.0030), smoothstep(0.3, 4.2, r));   // linear: #151922 -> #06070A
    c += vec3(0.0016,0.0019,0.0026) * lift * exp(-r*r*0.35);
    gl_FragColor = vec4(c, 1.0);
    #include <colorspace_fragment>
  }`
}));
bg.position.z = -5; scene.add(bg);

// lights: one soft key (upper left), a cool rim (behind right); both animate a little on each beat
scene.add(new THREE.AmbientLight(0xffffff, 0.12));
const key = new THREE.DirectionalLight(0xfff6ea, 1.6); scene.add(key); scene.add(key.target);
const rim = new THREE.DirectionalLight(0xdfeaff, 0.9); rim.position.set(4, 3, -4); scene.add(rim);

// the phone: generic graphite slab, no maker marks
function roundRectShape(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
}
const phone = new THREE.Group(); scene.add(phone);
const bodyMat = new THREE.MeshPhysicalMaterial({ color: 0x6a707c, metalness: 0.92, roughness: 0.26, clearcoat: 0.6, clearcoatRoughness: 0.15, envMapIntensity: 1.6 });
const body = new THREE.Mesh(new RoundedBoxGeometry(SW + 2 * BZ, SH + 2 * BZ, PD, 8, R.phone.radius), bodyMat); phone.add(body);
const glassMat = new THREE.MeshStandardMaterial({ color: 0x030304, roughness: 0.18, metalness: 0.0, envMapIntensity: 0.5 });
const glass = new THREE.Mesh(new THREE.ShapeGeometry(roundRectShape(SW + 2 * BZ - 0.012, SH + 2 * BZ - 0.012, R.phone.radius - 0.006), 24), glassMat);
glass.position.z = PD / 2 + 0.0006; phone.add(glass);
const slot = new THREE.Mesh(new THREE.ShapeGeometry(roundRectShape(0.16, 0.012, 0.006), 8), new THREE.MeshBasicMaterial({ color: 0x15171b }));
slot.position.set(0, SH / 2 + BZ * 0.5, PD / 2 + 0.0009); phone.add(slot);      // earpiece slot in the top bezel (not on the screen)
const screenGeo = new THREE.ShapeGeometry(roundRectShape(SW, SH, R.phone.screen_radius), 32);
{ const p = screenGeo.attributes.position, uv = screenGeo.attributes.uv;
  for (let i = 0; i < p.count; i++) uv.setXY(i, (p.getX(i) + SW / 2) / SW, (p.getY(i) + SH / 2) / SH); uv.needsUpdate = true; }
const shotImg = new Image();
const screenTex = new THREE.Texture(); screenTex.colorSpace = THREE.SRGBColorSpace; screenTex.generateMipmaps = false;
screenTex.minFilter = THREE.LinearFilter; screenTex.magFilter = THREE.LinearFilter; screenTex.anisotropy = 16;
const screenMat = new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false });
const screen = new THREE.Mesh(screenGeo, screenMat); screen.position.z = ZS; phone.add(screen);
// the single light streak (impact only): additive, clipped to the screen shape
const streakMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  uniforms: { p: { value: -1 }, a: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 vUv; uniform float p, a; void main(){
    float d = (vUv.x * 0.46 + (1.0 - vUv.y) * 0.54) - p; float band = exp(-d*d*900.0) + 0.35*exp(-d*d*120.0);
    gl_FragColor = vec4(vec3(1.0, 0.99, 0.96) * band * a, 1.0); }`
});
const streak = new THREE.Mesh(screenGeo, streakMat); streak.position.z = ZS + 0.0015; streak.renderOrder = 5; phone.add(streak);

// the plinth: a dark dock the phone stands in; its top face carries a faint reflection, its front face the captions
const PL = R.plinth;
const plMat = new THREE.MeshPhysicalMaterial({ color: 0x0a0b0e, metalness: 0.2, roughness: 0.42, clearcoat: 0.4, clearcoatRoughness: 0.3, envMapIntensity: 0.3 });
const plinth = new THREE.Mesh(new RoundedBoxGeometry(PL.w, PL.h, PL.d, 4, 0.03), plMat);
plinth.position.set(0, YP - PL.h / 2, 0); scene.add(plinth);
const TopShader = {
  name: "PlinthTop",
  uniforms: { color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null }, mixk: { value: PL.reflect } },
  vertexShader: `uniform mat4 textureMatrix; varying vec4 vUv; varying vec2 lp; void main(){ vUv = textureMatrix*vec4(position,1.0); lp = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float mixk; varying vec4 vUv; varying vec2 lp; void main(){
    vec3 r = vec3(0.0); for (int i=-1;i<=1;i++) for (int j=-1;j<=1;j++){ vec4 q = vUv; q.xy += vec2(float(i),float(j))*0.0025*vUv.w; r += texture2DProj(tDiffuse, q).rgb; } r /= 9.0;
    vec3 base = vec3(0.0035,0.0040,0.0052);
    gl_FragColor = vec4(base + r*mixk, 1.0);
    #include <colorspace_fragment>
  }`
};
const top = new Reflector(new THREE.PlaneGeometry(PL.w - 0.06, PL.d - 0.06), { textureWidth: 1080, textureHeight: 512, clipBias: 0.002, shader: TopShader, multisample: 4 });
top.rotation.x = -Math.PI / 2; top.position.set(0, YP + 0.0006, 0); scene.add(top);
// a hairline highlight along the front top edge; a soft light sweep travels along it on the beats
const edgeMat = new THREE.ShaderMaterial({ toneMapped: false, uniforms: { sx: { value: -9 }, base: { value: 0.12 } },
  vertexShader: `varying float lx; void main(){ lx = position.x; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying float lx; uniform float sx, base; void main(){ float k = base + 0.55*exp(-pow((lx - sx)/0.35, 2.0)); gl_FragColor = vec4(vec3(0.85,0.9,1.0)*k, 1.0);
    #include <colorspace_fragment>
  }` });
const edge = new THREE.Mesh(new THREE.BoxGeometry(PL.w - 0.07, 0.005, 0.005), edgeMat);
edge.position.set(0, YP - 0.0035, PL.d / 2 - 0.004); scene.add(edge);

// ------------------------------------------------------------------------------------------------ camera
function interp(keys, t) {
  if (t <= keys[0].t) return { ...keys[0] };
  for (let k = 1; k < keys.length; k++) {
    const a = keys[k - 1], b = keys[k];
    if (t <= b.t) {
      const e = (EASE[b.ease] || easeIO)(prog(t, a.t, b.t)); const o = {};
      for (const f of ["uf", "vf", "fx", "fy", "s", "yaw", "pitch", "key", "sweep"]) o[f] = lerp(a[f] ?? 0, b[f] ?? 0, e);
      return o;
    }
  }
  return { ...keys[keys.length - 1] };
}
function poseAt(t) {
  const p = interp(R.cam, t);
  if (t >= T.impact && t < T.impact + 0.6) p.s *= 1 + R.punch * Math.exp(-(t - T.impact) * 9) * Math.sin(prog(t, T.impact, T.impact + 0.6) * Math.PI * 0.5 + 0.5);
  return p;
}
function applyPose(p) {
  const P = uv2w(p.uf, p.vf);
  const d = H / (2 * Math.tan(deg(R.fov / 2)) * p.s * 1000);
  const yw = deg(p.yaw), pt = deg(p.pitch);
  camera.position.set(P.x + d * Math.sin(yw) * Math.cos(pt), P.y + d * Math.sin(pt), P.z + d * Math.cos(yw) * Math.cos(pt));
  camera.up.set(0, 1, 0); camera.lookAt(P);
  camera.setViewOffset(W, H, W / 2 - p.fx, H / 2 - p.fy, W, H);
  camera.updateProjectionMatrix(); camera.updateMatrixWorld();
  key.position.set(P.x - 3.2 + p.key * 1.2, P.y + 4.0, P.z + 5.0); key.target.position.copy(P); key.target.updateMatrixWorld();
  edgeMat.uniforms.sx.value = p.sweep;
}
const proj = v => { const q = v.clone().project(camera); return [(q.x + 1) / 2 * W, (1 - q.y) / 2 * H]; };
const projUV = (u, v) => proj(uv2w(u, v));

// ------------------------------------------------------------------------------------------------ screen frames
let loadedN = -1;
async function setShot(n) {
  if (n === loadedN) return;
  const im = new Image(); im.src = `/take/${String(n).padStart(5, "0")}.png`; await im.decode();
  screenTex.image = im; screenTex.needsUpdate = true; loadedN = n;
}

// ------------------------------------------------------------------------------------------------ 2D layer
const out = document.getElementById("out"); const ctx = out.getContext("2d");
let TEXTS = [];
const rec = (role, x, y, w, h, size) => TEXTS.push({ role, box: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)], size });
const textW = (s, font) => { ctx.font = font; return ctx.measureText(s).width; };
function fitFont(lines, fam, max, min, width) { for (let s = max; s >= min; s -= 1) if (lines.every(l => textW(l, fam.replace("{s}", s)) <= width)) return s; return min; }
const CX = R.safe_cx;

const endA = t => t < T.brand_big ? 0 : prog(t, T.brand_big, T.brand_big + 0.35) * (1 - prog(t, T.loop0, T.loop1));
function drawPill(t) {
  const g = 1 + (R.pill.grow - 1) * easeIO(endA(t));
  const tile = R.pill.tile * g, pad = R.pill.pad * g, fs = R.pill.font * g, font = `900 ${fs}px InterV`;
  const tw = textW("RapidTradeView", font);
  const bw = pad + tile + 18 * g + tw + 30 * g, bh = tile + 2 * pad;
  const x = CX - bw / 2, y = R.pill.top;
  ctx.save();
  ctx.fillStyle = "rgba(10,11,15,0.88)"; ctx.strokeStyle = "rgba(255,255,255,0.16)"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.roundRect(x, y, bw, bh, bh / 2); ctx.fill(); ctx.stroke();
  ctx.drawImage(MARK, x + pad, y + pad, tile, tile);
  ctx.font = font; ctx.fillStyle = "#fff"; ctx.textBaseline = "middle"; ctx.fillText("RapidTradeView", x + pad + tile + 18 * g, y + bh / 2 + 2 * g);
  ctx.restore();
  rec("pill", x, y, bw, bh, fs);
  return [x, y, bw, bh];
}
const textOut = t => 1 - prog(t, T.loop0, T.loop0 + 0.2);       // end text leaves first, then the headline returns
function headlineA(t) { return t < T.loop0 ? 1 - prog(t, T.head_out0, T.head_out1) : prog(t, T.loop0 + 0.22, T.loop1); }
function drawHeadline(t) {
  const a = headlineA(t); if (a <= 0.001) return;
  const L = R.text.headline, fs = fitFont(L, '400 {s}px "Archivo Black"', R.headline.max, R.headline.min, 840);
  const font = `400 ${fs}px "Archivo Black"`; const lift = t < T.loop0 ? -18 * (1 - a) : 14 * (1 - a);
  ctx.save(); ctx.globalAlpha = a; ctx.font = font; ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round";
  L.forEach((ln, i) => {
    const y = R.headline.top + fs * 0.8 + i * fs * 1.06 + lift; const tot = textW(ln, font); let x = CX - tot / 2;
    for (const wd of ln.split(" ")) {
      ctx.lineWidth = 12; ctx.strokeStyle = "rgba(4,5,8,0.95)"; ctx.strokeText(wd, x, y);
      ctx.fillStyle = wd.replace(/[^A-Z]/g, "") === R.text.headline_accent ? C.accent : C.white; ctx.fillText(wd, x, y);
      x += textW(wd + " ", font);
    }
    rec("headline", CX - tot / 2, y - fs * 0.76, tot, fs * 0.8, fs);
  });
  ctx.restore();
}
function plinthEdgeY() {
  const a = proj(new THREE.Vector3(-0.8, YP, PL.d / 2)), b = proj(new THREE.Vector3(0, YP, PL.d / 2)), c = proj(new THREE.Vector3(0.8, YP, PL.d / 2));
  return [a[1], b[1], c[1]];
}
function drawCaption(t, edgeY) {
  if (t >= T.caption_stop) return;
  const cap = R.captions.find(c => t >= c.t0 && t < c.t1); if (!cap) return;
  const txt = cap.parts.map(p => p.text).join(" ");
  const fs = fitFont([txt], "900 {s}px InterV", R.caption.size, R.caption.min, R.caption.max_w); const f = `900 ${fs}px InterV`;
  const w = textW(txt, f); const pop = 1 + 0.07 * (1 - easeO(prog(t, cap.t0, cap.t0 + 0.12)));
  const base = Math.min(edgeY + R.caption.below_edge, R.caption.max_base);   // on the plinth face, inside the safe zone
  ctx.save(); ctx.translate(CX, base - fs * 0.36); ctx.scale(pop, pop); ctx.translate(-CX, -(base - fs * 0.36));
  ctx.font = f; ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round"; let x = CX - w / 2;
  for (const p of cap.parts) {
    ctx.lineWidth = 14; ctx.strokeStyle = "#040507"; ctx.strokeText(p.text, x, base);
    ctx.fillStyle = p.color === "cyan" ? C.cyan : C.white; ctx.fillText(p.text, x, base); x += textW(p.text + " ", f);
  }
  ctx.restore();
  rec("caption", CX - w * pop / 2 - 7, base - fs * 0.74 * pop - 7, w * pop + 14, fs * 0.74 * pop + 14 + fs * 0.2, fs);
}
function drawEnd(t, edgeY, pill) {
  const a = Math.min(endA(t) > 0 ? 1 : 0, prog(t, T.brand_big, T.brand_big + 0.35)) * textOut(t); if (a <= 0) return;
  const f2 = `800 ${R.end.site_size}px InterV`, full = R.text.site, w2 = textW(full, f2);
  const n = Math.round(full.length * prog(t, T.brand_big + 0.1, T.brand_big + 0.7));
  if (n > 0) {
    const s = full.slice(0, n), y = pill[1] + pill[3] + R.end.site_gap + R.end.site_size * 0.78;
    ctx.save(); ctx.globalAlpha = a; ctx.font = f2; ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round";
    ctx.lineWidth = 10; ctx.strokeStyle = "rgba(4,5,8,0.95)"; ctx.strokeText(s, CX - w2 / 2, y); ctx.fillStyle = C.cyan; ctx.fillText(s, CX - w2 / 2, y);
    ctx.restore(); rec("end_site", CX - w2 / 2, y - R.end.site_size * 0.78, w2, R.end.site_size * 0.98, R.end.site_size);
  }
  const da = prog(t, T.disclaim - 0.1, T.disclaim + 0.2) * textOut(t);
  if (da > 0) {
    const f3 = `700 ${R.end.disc_size}px InterV`, w3 = textW(R.text.disclaimer, f3), y = Math.min(edgeY + R.caption.below_edge, R.caption.max_base);
    ctx.save(); ctx.globalAlpha = da; ctx.font = f3; ctx.lineJoin = "round"; ctx.lineWidth = 10; ctx.strokeStyle = "rgba(4,5,8,0.95)";
    ctx.strokeText(R.text.disclaimer, CX - w3 / 2, y); ctx.fillStyle = "rgba(255,255,255,0.94)"; ctx.fillText(R.text.disclaimer, CX - w3 / 2, y);
    ctx.restore(); rec("end_disclaimer", CX - w3 / 2, y - R.end.disc_size * 0.76, w3, R.end.disc_size * 0.98, R.end.disc_size);
  }
}
function drawRipples(t) {
  for (const tp of R.taps) {
    const k = prog(t, tp.t, tp.t + 0.42); if (t < tp.t || k >= 1) continue;
    const [x, y] = projUV(tp.u, tp.v);
    ctx.save();
    ctx.globalAlpha = 0.34 * (1 - prog(t, tp.t, tp.t + 0.18)); ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, 22, 0, 6.2832); ctx.fill();
    ctx.globalAlpha = 0.95 * (1 - k); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 + 3 * (1 - k); ctx.shadowColor = "rgba(255,255,255,0.8)"; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(x, y, 16 + 58 * easeO(k), 0, 6.2832); ctx.stroke();
    ctx.restore();
    rec("ripple", x - 74, y - 74, 148, 148, 0);
  }
}

// ------------------------------------------------------------------------------------------------ frame
function keepoutState() {
  const res = [];
  for (const k of R.keepout) {
    let [u0, v0, u1, v1] = k.src;
    let why = null, visible = false, quad = null;
    if (v0 >= VP) why = "below the plinth line";
    else {
      v1 = Math.min(v1, VP);
      quad = [projUV(u0, v0), projUV(u1, v0), projUV(u1, v1), projUV(u0, v1)];
      const xs = quad.map(p => p[0]), ys = quad.map(p => p[1]);
      visible = Math.max(...xs) > 0 && Math.min(...xs) < W && Math.max(...ys) > 0 && Math.min(...ys) < H;
      why = visible ? "IN FRAME" : "outside the frame";
    }
    res.push({ id: k.id, visible, why });
  }
  return res;
}
function visibleTexts() {
  const outT = [];
  for (const tx of R.page_texts) {
    const [u0, v0, u1, v1] = tx.src; if (v0 >= VP) continue;
    const q = [projUV(u0, v0), projUV(u1, Math.min(v1, VP))];
    if (Math.max(q[0][0], q[1][0]) > 0 && Math.min(q[0][0], q[1][0]) < W && Math.max(q[0][1], q[1][1]) > 0 && Math.min(q[0][1], q[1][1]) < H) outT.push(tx.text);
  }
  return outT;
}

window.renderFrame = async (i) => {
  const t = i / FPS; TEXTS = [];
  await setShot(R.track[i]);
  const p = poseAt(t); applyPose(p);
  const sk = T.streak0 <= t && t < T.streak1 ? prog(t, T.streak0, T.streak1) : -1;
  streakMat.uniforms.p.value = sk < 0 ? -2 : lerp(-0.25, 1.25, easeO(sk)); streakMat.uniforms.a.value = sk < 0 ? 0 : 0.2 * Math.sin(Math.PI * sk);
  streak.visible = sk >= 0;
  renderer.render(scene, camera);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(glc, 0, 0, W, H);
  drawRipples(t);
  const edgeY = plinthEdgeY();
  drawHeadline(t);
  const pill = drawPill(t);
  drawCaption(t, edgeY[1]);
  drawEnd(t, edgeY[1], pill);
  const win = [projUV(0, 0), projUV(SRC_W, 0), projUV(SRC_W, VP), projUV(0, VP)];
  const logo = R.logo_src ? [projUV(R.logo_src[0], R.logo_src[1]), projUV(R.logo_src[2], R.logo_src[3])] : null;
  return { t, src: R.track[i], pose: p, pill, texts: TEXTS, window_quad: win, plinth_edge_y: edgeY,
           logo_px_h: logo ? Math.abs(logo[1][1] - logo[0][1]) : null, keepout: keepoutState(),
           page_texts_visible: i % 10 === 0 ? visibleTexts() : null, streak: sk >= 0 };
};
window.sceneReady = true;
