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
  uniforms: { lift: { value: 1.0 }, glow: { value: 0.0 } },
  vertexShader: `varying vec3 wp; void main(){ vec4 w = modelMatrix*vec4(position,1.0); wp = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }`,
  fragmentShader: `varying vec3 wp; uniform float lift, glow; void main(){
    float r = length((wp.xy - vec2(-0.25, 0.9)) * vec2(1.0, 0.8));
    vec3 c = mix(vec3(0.0105,0.0130,0.0190), vec3(0.0017,0.0020,0.0030), smoothstep(0.3, 4.6, r));   // linear: graphite void
    c += vec3(0.0016,0.0019,0.0026) * lift * exp(-r*r*0.35);
    float g = length((wp.xy - vec2(0.9, 0.2)) * vec2(0.8, 1.0));                                     // a low accent glow, right
    c += vec3(0.0010,0.0050,0.0026) * (0.5 + 1.4 * glow) * exp(-g*g*0.3);
    gl_FragColor = vec4(c, 1.0);
    #include <colorspace_fragment>
  }`
}));
bg.position.z = -5; scene.add(bg);

// lights: one soft key (upper left), a cool rim (behind right); both animate a little on each beat
scene.add(new THREE.AmbientLight(0xffffff, 0.12));
const key = new THREE.DirectionalLight(0xfff6ea, 2.4); scene.add(key); scene.add(key.target);
const rim = new THREE.DirectionalLight(0xdfeaff, 1.6); rim.position.set(4, 3, -4); scene.add(rim);
const rimL = new THREE.DirectionalLight(0xe8f0ff, 1.1); rimL.position.set(-5, 2.5, -2.5); scene.add(rimL);   // left edge light
const ACC = new THREE.Color(C.accent);
const rimG = new THREE.DirectionalLight(ACC, 1.3); rimG.position.set(5, 1.5, -1.5); scene.add(rimG);   // accent rim (right edge)

// the phone: generic graphite slab, no maker marks
function roundRectShape(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
}
const phone = new THREE.Group(); scene.add(phone);
const bodyMat = new THREE.MeshPhysicalMaterial({ color: 0x8e95a2, metalness: 0.92, roughness: 0.2, clearcoat: 0.7, clearcoatRoughness: 0.15, envMapIntensity: 2.2 });
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
// side buttons (generic: a power key right, two volume keys left), above the dock line
for (const [x, y, h] of [[1, 0.62, 0.20], [-1, 0.78, 0.13], [-1, 0.56, 0.13]]) {
  const bt = new THREE.Mesh(new RoundedBoxGeometry(0.014, h, PD * 0.42, 3, 0.006), bodyMat);
  bt.position.set(x * (SW / 2 + BZ + 0.004), y, 0); phone.add(bt);
}
// a thin bright rim on the frame edge: always faintly lit (the phone silhouette); on the two light events a band of
// light runs once around it. It sits on the bezel, outside the screen.
const OW = SW + 2 * BZ, OH = SH + 2 * BZ, RW = 0.0075;
const ringShape = roundRectShape(OW - 0.002, OH - 0.002, R.phone.radius - 0.001);
ringShape.holes.push(roundRectShape(OW - 0.002 - 2 * RW, OH - 0.002 - 2 * RW, R.phone.radius - 0.001 - RW));
const ringMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  uniforms: { p: { value: 0 }, a: { value: 0 }, base: { value: 0.5 }, acc: { value: ACC } },
  vertexShader: `varying vec2 lp; void main(){ lp = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 lp; uniform float p, a, base; uniform vec3 acc; void main(){
    float ang = atan(lp.y, lp.x * ${(OH / OW).toFixed(4)}) / 6.28318 + 0.5;            // 0..1 around the frame
    float d = abs(fract(ang - p + 0.5) - 0.5);
    float band = exp(-d*d*260.0) * a;
    vec3 c = vec3(0.75, 0.8, 0.86) * base + mix(vec3(1.0), acc, 0.55) * band * 2.2;
    gl_FragColor = vec4(c, 1.0); }`
});
const ring = new THREE.Mesh(new THREE.ShapeGeometry(ringShape, 24), ringMat); ring.position.z = PD / 2 + 0.0012; phone.add(ring);
// a soft accent glow behind the phone (never in front of the screen): faint always, blooming on the light events
const haloMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  uniforms: { a: { value: 0.0 }, acc: { value: ACC } },
  vertexShader: `varying vec2 lp; void main(){ lp = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 lp; uniform float a; uniform vec3 acc; void main(){
    vec2 hb = vec2(${(OW / 2).toFixed(4)}, ${(OH / 2).toFixed(4)}) - ${R.phone.radius.toFixed(4)};
    vec2 q = abs(lp) - hb; float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - ${R.phone.radius.toFixed(4)};
    float g = d < 0.0 ? 1.0 : exp(-d * 5.5);
    gl_FragColor = vec4(acc * g * a, 1.0);
    #include <colorspace_fragment>
  }`
});
const halo = new THREE.Mesh(new THREE.PlaneGeometry(OW + 2.4, OH + 2.4), haloMat); halo.position.z = -PD / 2 - 0.03; phone.add(halo);

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
    vec3 r = vec3(0.0); for (int i=-2;i<=2;i++) for (int j=-2;j<=2;j++){ vec4 q = vUv; q.xy += vec2(float(i),float(j))*0.0032*vUv.w; r += texture2DProj(tDiffuse, q).rgb; } r /= 25.0;
    vec3 base = vec3(0.0035,0.0040,0.0052);
    float fade = smoothstep(0.0, ${(PL.d / 2 - 0.1).toFixed(3)}, -lp.y);           // the reflection fades toward the viewer
    gl_FragColor = vec4(base + r*mixk*(1.0 - 0.7*fade), 1.0);
    #include <colorspace_fragment>
  }`
};
const top = new Reflector(new THREE.PlaneGeometry(PL.w - 0.06, PL.d - 0.06), { textureWidth: 1080, textureHeight: 512, clipBias: 0.002, shader: TopShader, multisample: 4 });
top.rotation.x = -Math.PI / 2; top.position.set(0, YP + 0.0006, 0); scene.add(top);
// a hairline highlight along the front top edge; a soft light sweep travels along it on the beats
const edgeMat = new THREE.ShaderMaterial({ toneMapped: false, uniforms: { sx: { value: -9 }, base: { value: 0.12 } },
  vertexShader: `varying float lx; void main(){ lx = position.x; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying float lx; uniform float sx, base; void main(){ float k = base + 0.55*exp(-pow((lx - sx)/0.35, 2.0)); gl_FragColor = vec4(mix(vec3(0.85,0.9,1.0), vec3(0.45,0.95,0.65), 0.35)*k, 1.0);
    #include <colorspace_fragment>
  }` });
const edge = new THREE.Mesh(new THREE.BoxGeometry(PL.w - 0.07, 0.005, 0.005), edgeMat);
edge.position.set(0, YP - 0.0035, PL.d / 2 - 0.004); scene.add(edge);
// the dock's front face: a soft vertical gradient (lit near the top edge), not a flat slab
const faceMat = new THREE.ShaderMaterial({ toneMapped: false, uniforms: { acc: { value: ACC }, k: { value: 0.0 } },
  vertexShader: `varying vec2 lp; void main(){ lp = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
  fragmentShader: `varying vec2 lp; uniform vec3 acc; uniform float k; void main(){
    float y = ${(PL.h / 2).toFixed(3)} - lp.y;                                  // depth below the top edge
    vec3 c = mix(vec3(0.0105,0.0115,0.0140), vec3(0.0016,0.0018,0.0022), smoothstep(0.0, 1.1, y));
    c += acc * 0.010 * exp(-y * 28.0) * (1.0 + k);
    float sx = lp.x / ${(PL.w / 2).toFixed(3)}; c *= 1.0 - 0.35 * sx * sx;
    gl_FragColor = vec4(c, 1.0);
    #include <colorspace_fragment>
  }` });
const face = new THREE.Mesh(new THREE.PlaneGeometry(PL.w - 0.04, PL.h - 0.04), faceMat);
face.position.set(0, YP - PL.h / 2, PL.d / 2 + 0.0015); scene.add(face);

// ------------------------------------------------------------------------------------------------ pattern beams
// Two light beams far behind the phone continue the app's two pattern lines out past the phone's edges. Each is laid
// along the ray from the frame-0 camera through the real line (at frame 0 it projects exactly onto the line's
// extension); it grows, flares and fades with the app's real draw-ons: R.beam[i] = [seconds since the measured
// draw-on start, seconds since the measured Hide], read through the app's own timeline (PATTERN_TIMELINE, cubic ease).
const BM = R.beams, PM = R.pattern_ms;
const easeOut3 = x => 1 - Math.pow(1 - clamp(x), 3);
const beamMats = [];
function buildBeams(C0) {
  const L2 = R.lines.map(([u0, v0, u1, v1]) => [uv2w(u0, v0), uv2w(u1, v1)]);
  const kz = (C0.z - BM.depth) / (C0.z - ZS);
  const push = P => C0.clone().add(P.clone().sub(C0).multiplyScalar((C0.z - BM.depth) / (C0.z - P.z)));
  const [a1, b1] = L2[0], [a2, b2] = L2[1];                       // where the two lines meet (line units of each)
  const d1 = b1.clone().sub(a1), d2 = b2.clone().sub(a2), den = d1.x * d2.y - d1.y * d2.x;
  let ap = [1.25, 1.25];
  if (Math.abs(den) > 1e-6) {
    const w = a2.clone().sub(a1); const s1 = (w.x * d2.y - w.y * d2.x) / den, s2 = (w.x * d1.y - w.y * d1.x) / den;
    if (s1 > 1 && s2 > 1 && s1 < 4 && s2 < 4) ap = [s1, s2];
  }
  L2.forEach(([A, B], j) => {
    const A2 = push(A), B2 = push(B), dir = B2.clone().sub(A2), len = dir.length(); dir.normalize();
    const nrm = new THREE.Vector3(-dir.y, dir.x, 0);
    const E = BM.ext_left * kz / len, half = BM.glow * kz * 3.0;
    const pos = [], lx = [], ld = [];
    for (const x of [-E, ap[j] + 0.02]) for (const sd of [-1, 1]) {
      const P = A2.clone().add(dir.clone().multiplyScalar(x * len)).add(nrm.clone().multiplyScalar(sd * half));
      pos.push(P.x, P.y, P.z); lx.push(x); ld.push(sd);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("lx", new THREE.Float32BufferAttribute(lx, 1)); g.setAttribute("ld", new THREE.Float32BufferAttribute(ld, 1));
    g.setIndex([0, 1, 2, 2, 1, 3]);
    const m = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false, side: THREE.DoubleSide,
      uniforms: { head: { value: 0 }, tail: { value: 0 }, amp: { value: 0 }, hot: { value: 0 }, acc: { value: ACC },
                  core: { value: BM.core / (BM.glow * 3.0) }, apex: { value: ap[j] }, len: { value: len } },
      vertexShader: `attribute float lx, ld; varying float vx, vd; void main(){ vx = lx; vd = ld; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
      fragmentShader: `varying float vx, vd; uniform float head, tail, amp, hot, core, apex, len; uniform vec3 acc; void main(){
        float d = abs(vd);
        float prof = exp(-d*d/(core*core)) + exp(-d*d*9.0) * 0.32;
        float soft = 0.025 / len;
        float on = smoothstep(tail - soft, tail + soft, vx) * (1.0 - smoothstep(head - soft, head + soft, vx));
        float tipH = exp(-pow((vx - head) * len / 0.05, 2.0)) * hot, tipT = exp(-pow((vx - tail) * len / 0.07, 2.0)) * hot;
        float far = exp(-max(0.0, -vx) * len * 0.32);
        float i = (on * amp * far + (tipH + tipT) * on * 1.4) * prof;
        vec3 c = mix(acc, vec3(1.0), clamp(prof - 0.55, 0.0, 0.45)) * i;
        gl_FragColor = vec4(c, 1.0); }`
    });
    const mesh = new THREE.Mesh(g, m); mesh.renderOrder = -1; scene.add(mesh); beamMats.push(m);
  });
}
function beamState(i) {
  // [app seconds since the draw-on start, seconds since Hide, measured upper-line progress, measured lower-line progress]
  const [a, hid, pU, pL] = R.beam[i];
  const tA = a < 0 ? 9 : a, lab = PM.label[0] / 1000;
  const pf = easeOut3((tA - PM.lines[1] / 1000) / ((PM.fill_end - PM.lines[1]) / 1000));   // after the lines: to the apex
  const flare = tA >= lab ? BM.flare * Math.exp(-(tA - lab) * 4.5) * Math.min(1, (tA - lab) / 0.04) : 0;
  return beamMats.map((m, j) => {
    const p = a < 0 ? 1 : (j === 0 ? pU : pL);
    let amp = BM.on * Math.min(1, p * 2.0) + flare, hot = tA < lab ? (p < 1 ? 1.0 : 0.5) * (1 - 0.6 * pf) : 0.25 * Math.exp(-(tA - lab) * 6);
    if (a < 0) { const f = 1 - clamp(hid / 0.16); amp *= f; hot *= f; }
    const head = p + pf * (m.uniforms.apex.value - 1);
    m.uniforms.head.value = head; m.uniforms.tail.value = -9 * p; m.uniforms.amp.value = amp; m.uniforms.hot.value = hot;
    return { head: +head.toFixed(3), amp: +amp.toFixed(3) };
  });
}

// the floor: a dark, light-catching surface under the dock: a soft reflection (beams, rim, halo) and a light pool
const FL = R.floor, YF = YP - PL.h;
const FloorShader = {
  name: "Floor",
  uniforms: { color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null }, mixk: { value: FL.reflect },
              pool: { value: FL.pool }, acc: { value: ACC }, k: { value: 0 } },
  vertexShader: `uniform mat4 textureMatrix; varying vec4 vUv; varying vec2 lp; void main(){ vUv = textureMatrix*vec4(position,1.0); lp = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float mixk, pool, k; uniform vec3 acc; varying vec4 vUv; varying vec2 lp; void main(){
    vec3 r = vec3(0.0); for (int i=-2;i<=2;i++) for (int j=-2;j<=2;j++){ vec4 q = vUv; q.xy += vec2(float(i),float(j))*0.0045*vUv.w; r += texture2DProj(tDiffuse, q).rgb; } r /= 25.0;
    vec2 c = (lp - vec2(0.0, ${(-(PL.d / 2 + 0.7 - 1.05)).toFixed(3)})) * vec2(0.55, 1.1);
    vec3 base = vec3(0.0030,0.0034,0.0044) + acc * pool * exp(-dot(c, c)) * (1.0 + 1.5*k);
    gl_FragColor = vec4(base + r*mixk, 1.0);
    #include <colorspace_fragment>
  }`
};
const floor = new Reflector(new THREE.PlaneGeometry(30, 11.9), { textureWidth: 1080, textureHeight: 960, clipBias: 0.003, shader: FloorShader, multisample: 4 });
floor.rotation.x = -Math.PI / 2; floor.position.set(0, YF, 1.05); scene.add(floor);

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
function drawPill(t, logoH) {
  const base = R.pill.tile + 2 * R.pill.pad;
  const g = Math.max(1 + (R.pill.grow - 1) * easeIO(endA(t)), logoH ? R.pill.logo_ratio * logoH / base : 1);
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
  if (t < T.url0) return;
  // the URL appears once, on the dock face, with one quick pop as the captions stop; the disclaimer comes under it
  const full = R.text.site, a = prog(t, T.url0, T.url0 + 0.14), sc = 1 + 0.12 * (1 - easeO(prog(t, T.url0, T.url0 + 0.22)));
  const fs = R.end.site_size, f2 = `800 ${fs}px InterV`, w2 = textW(full, f2);
  const yDock = Math.min(edgeY + R.end.site_below_edge, R.end.site_max_base);
  ctx.save(); ctx.globalAlpha = a; ctx.translate(CX, yDock - fs * 0.36); ctx.scale(sc, sc); ctx.translate(-CX, -(yDock - fs * 0.36));
  ctx.font = f2; ctx.textBaseline = "alphabetic"; ctx.lineJoin = "round";
  ctx.lineWidth = 10; ctx.strokeStyle = "rgba(4,5,8,0.95)"; ctx.strokeText(full, CX - w2 / 2, yDock); ctx.fillStyle = C.cyan; ctx.fillText(full, CX - w2 / 2, yDock);
  ctx.restore(); rec("end_site", CX - w2 * sc / 2, yDock - fs * 0.36 - fs * 0.42 * sc, w2 * sc, fs * 0.98 * sc, fs);
  const da = prog(t, T.disclaim + 0.05, T.disclaim + 0.3);
  if (da > 0) {
    const f3 = `700 ${R.end.disc_size}px InterV`, w3 = textW(R.text.disclaimer, f3), y3 = yDock + R.end.disc_gap;
    ctx.save(); ctx.globalAlpha = da; ctx.font = f3; ctx.lineJoin = "round"; ctx.lineWidth = 9; ctx.strokeStyle = "rgba(4,5,8,0.95)";
    ctx.strokeText(R.text.disclaimer, CX - w3 / 2, y3); ctx.fillStyle = "#ffffff"; ctx.fillText(R.text.disclaimer, CX - w3 / 2, y3);
    ctx.restore(); rec("end_disclaimer", CX - w3 / 2, y3 - R.end.disc_size * 0.76, w3, R.end.disc_size * 0.98, R.end.disc_size);
  }
}
function drawRipples(t) {
  for (const tp of R.taps) {
    // short: the fill disc is gone in 70 ms (the app answers a tap in ~45 ms), the ring expands away and is gone in
    // 0.26 s, so it never sits on the app's new state (the last tap's ring ends before the last frame)
    const k = prog(t, tp.t, tp.t + 0.26); if (t < tp.t || k >= 1) continue;
    const [x, y] = projUV(tp.u, tp.v);
    ctx.save();
    ctx.globalAlpha = 0.34 * (1 - prog(t, tp.t, tp.t + 0.07)); ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, 22, 0, 6.2832); ctx.fill();
    ctx.globalAlpha = 0.95 * (1 - k); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 + 3 * (1 - k); ctx.shadowColor = "rgba(255,255,255,0.8)"; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(x, y, 20 + 70 * easeO(k), 0, 6.2832); ctx.stroke();
    ctx.restore();
    rec("ripple", x - 92, y - 92, 184, 184, 0);
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

function heroState() {
  return R.hero.map(h => { const [u0, v0, u1, v1] = h.src; return { id: h.id, zone: h.zone || null, skip_t: h.skip_t || null, quad: [projUV(u0, v0), projUV(u1, v0), projUV(u1, v1), projUV(u0, v1)] }; });
}
// the two light events: the hook's label pop and the one impact; a rim band runs once around the frame
function flashAt(t) {
  for (const t0 of [T.flash0, T.flash1]) { const k = prog(t, t0 - 0.02, t0 + 0.75); if (t >= t0 - 0.02 && k < 1) return k; }
  return -1;
}
function frame2D(t, i) {
  const edgeY = plinthEdgeY();
  const logo = R.logo_src ? [projUV(R.logo_src[0], R.logo_src[1]), projUV(R.logo_src[2], R.logo_src[3])] : null;
  const logoH = logo ? Math.abs(logo[1][1] - logo[0][1]) : null;
  drawRipples(t);
  drawHeadline(t);
  const pill = drawPill(t, logoH);
  drawCaption(t, edgeY[1]);
  drawEnd(t, edgeY[1], pill);
  const win = [projUV(0, 0), projUV(SRC_W, 0), projUV(SRC_W, VP), projUV(0, VP)];
  return { pill, edgeY, logoH, win };
}
applyPose(poseAt(0)); buildBeams(camera.position.clone());
window.renderFrame = async (i) => {
  const t = i / FPS; TEXTS = [];
  await setShot(R.track[i]);
  const p = poseAt(t); applyPose(p);
  const bst = beamState(i);
  const fk = flashAt(t);
  ringMat.uniforms.p.value = fk < 0 ? 0 : 0.62 + 1.0 * easeO(fk); ringMat.uniforms.a.value = fk < 0 ? 0 : Math.sin(Math.PI * Math.min(1, fk * 1.15));
  const bloom = fk < 0 ? 0 : Math.exp(-fk * 4.0) * (fk < 0.06 ? fk / 0.06 : 1);
  haloMat.uniforms.a.value = 0.014 + 0.30 * bloom; bg.material.uniforms.glow.value = bloom;
  rimG.intensity = 1.3 + 2.5 * bloom; faceMat.uniforms.k.value = 2.0 * bloom; floor.material.uniforms.k.value = bloom;
  renderer.render(scene, camera);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(glc, 0, 0, W, H);
  const f = frame2D(t, i);
  return { t, src: R.track[i], pose: p, pill: f.pill, texts: TEXTS, window_quad: f.win, plinth_edge_y: f.edgeY,
           logo_px_h: f.logoH, keepout: keepoutState(), hero: heroState(),
           page_texts_visible: i % 10 === 0 ? visibleTexts() : null, flash: fk >= 0, beams: bst };
};
// framing only (no GL render, no screen texture): the build gates the camera before any pixel is rendered
window.probeFrame = (i) => {
  const t = i / FPS; TEXTS = [];
  const p = poseAt(t); applyPose(p);
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
  const f = frame2D(t, i);
  return { i, t, pose: p, pill: f.pill, texts: TEXTS, window_quad: f.win, logo_px_h: f.logoH, keepout: keepoutState(), hero: heroState() };
};
window.sceneReady = true;
