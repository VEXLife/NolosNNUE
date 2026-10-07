// three.js board: a thick kaya goban on four legs, lit like a still-life photograph —
// one soft key light, a dim fill and a faint environment for reflections on the stones.
// No glow or neon; motion is limited to a short, weighted stone placement and the camera.
// Flat details (grid, coordinates, markers, move numbers) are painted with the shared 2D
// helpers into textures so both views always agree.
import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { RoomEnvironment } from './vendor/three/RoomEnvironment.js';
import { RoundedBoxGeometry } from './vendor/three/RoundedBoxGeometry.js';
import {
  layout, bindPointer, drawSurface, drawGrain, drawForbid, drawBestRing, drawLive, drawLabel,
  drawWinRing, labelColor, themeOf, ACCENT,
} from './board2d.js';

const TEX = 2048;
const HOME = { theta: 0, phi: 0.6, radius: 2.75 };
const INTRO = { theta: -0.55, phi: 0.95, radius: 3.2 };
const THICK = 0.17;          // goban body height relative to a 1.0 playing surface
const LEG = 0.11;
const TOP_X = 1.03, TOP_Z = 1.07;
const BODY = { kaya: 0xb98548, slate: 0x2c2e31 };
const easeOut = k => 1 - Math.pow(1 - k, 3);
const easeInOut = k => k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;

function canvasTexture(canvas, renderer) {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return tex;
}

// Side grain for the body of the goban, multiplied with the body colour.
function sideTexture(theme, renderer) {
  const c = Object.assign(document.createElement('canvas'), { width: 1024, height: 256 }), ctx = c.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1024, 256);
  let seed = 11;
  const rand = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296;
  for (let i = 0; i < 140; i++) {
    const y0 = rand() * 256, amp = 2 + rand() * 6, ph = rand() * 6.3;
    ctx.strokeStyle = `rgba(${theme.grain},${0.06 + rand() * 0.14})`; ctx.lineWidth = 0.6 + rand() * 1.6;
    ctx.beginPath();
    for (let x = 0; x <= 1024; x += 32) { const y = y0 + Math.sin(x / 140 + ph) * amp; x ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.stroke();
  }
  return canvasTexture(c, renderer);
}

// Soft contact shadow under the whole goban, independent of the shadow map.
function floorShadow() {
  const c = Object.assign(document.createElement('canvas'), { width: 256, height: 256 }), ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(128, 128, 30, 128, 128, 128);
  g.addColorStop(0, 'rgba(0,0,0,0.5)'); g.addColorStop(0.6, 'rgba(0,0,0,0.18)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

export class Board3D {
  constructor(host) {
    this.host = host;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.NeutralToneMapping;
    renderer.toneMappingExposure = 0.92;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.domElement.className = 'board-canvas gl';
    host.appendChild(renderer.domElement);
    this.renderer = renderer; this.canvas = renderer.domElement;

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environmentIntensity = 0.32;
    pmrem.dispose();
    this.scene3 = scene;

    this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 30);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.target.set(0, -0.09, 0);
    this.camera.position.setFromSpherical(new THREE.Spherical(INTRO.radius, INTRO.phi, INTRO.theta)).add(this.controls.target);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.09, enablePan: false, minDistance: 1.4, maxDistance: 4.2, maxPolarAngle: 1.25, rotateSpeed: 0.6 });
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    this.controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_ROTATE };
    this.controls.addEventListener('start', () => { this.camAnim = null; });
    this.controls.addEventListener('change', () => { this.dirty = true; });
    this.camAnim = { from: { ...INTRO }, to: { ...HOME }, t0: performance.now(), dur: 1800 };

    // One soft key light from the upper left, a cool dim fill from the right.
    const key = new THREE.DirectionalLight(0xfff4e6, 2.4);
    key.position.set(-1.2, 2.6, -0.5);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -1, right: 1, top: 1, bottom: -1, near: 0.5, far: 6 });
    key.shadow.radius = 3; key.shadow.bias = -0.0003; key.shadow.normalBias = 0.003;
    const fill = new THREE.DirectionalLight(0xdfe8f2, 0.35);
    fill.position.set(1.5, 1.0, 1.4);
    scene.add(key, fill, new THREE.HemisphereLight(0xf4efe6, 0x2a2420, 0.25));

    // Goban: rounded body with side grain, painted top, label overlay and four legs.
    this.boardCanvas = Object.assign(document.createElement('canvas'), { width: TEX, height: TEX });
    this.overlayCanvas = Object.assign(document.createElement('canvas'), { width: TEX, height: TEX });
    this.boardTex = canvasTexture(this.boardCanvas, renderer);
    this.overlayTex = canvasTexture(this.overlayCanvas, renderer);
    this.sideTex = {};
    this.bodyMat = new THREE.MeshStandardMaterial({ color: BODY.kaya, roughness: 0.72 });
    const body = new THREE.Mesh(new RoundedBoxGeometry(TOP_X + 0.03, THICK, TOP_Z + 0.03, 5, 0.012), this.bodyMat);
    body.position.y = -THICK / 2 - 0.0005;
    body.castShadow = true; body.receiveShadow = true;
    const top = new THREE.Mesh(new THREE.PlaneGeometry(TOP_X, TOP_Z).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ map: this.boardTex, roughness: 0.78 }));
    top.receiveShadow = true;
    this.overlay = new THREE.Mesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: this.overlayTex, transparent: true, depthWrite: false, toneMapped: false }));
    this.overlay.renderOrder = 3;
    this.legMat = new THREE.MeshStandardMaterial({ color: BODY.kaya, roughness: 0.75 });
    const legGeo = new THREE.CylinderGeometry(0.06, 0.042, LEG, 32);
    for (const [x, z] of [[-0.36, -0.38], [0.36, -0.38], [-0.36, 0.38], [0.36, 0.38]]) {
      const leg = new THREE.Mesh(legGeo, this.legMat);
      leg.position.set(x, -THICK - LEG / 2, z);
      leg.castShadow = true;
      scene.add(leg);
    }
    const floor = this.floor = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.2).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: floorShadow(), color: 0x000000, transparent: true, opacity: 0.9, depthWrite: false }));
    floor.position.set(0.12, -THICK - LEG - 0.001, 0.08);
    scene.add(body, top, this.overlay, floor);

    // Stones: flattened spheres (biconvex) with a satin finish.
    this.stoneGeo = new THREE.SphereGeometry(1, 64, 32);
    this.stoneMat = {
      1: new THREE.MeshPhysicalMaterial({ color: 0x141517, roughness: 0.42, clearcoat: 0.55, clearcoatRoughness: 0.32 }),
      2: new THREE.MeshPhysicalMaterial({ color: 0xf6f4ee, roughness: 0.5, clearcoat: 0.35, clearcoatRoughness: 0.4 }),
    };
    this.ghostMat = {};
    for (const c of [1, 2]) this.ghostMat[c] = Object.assign(this.stoneMat[c].clone(), { transparent: true, depthWrite: false });
    this.stones = new Map();   // screen index -> mesh
    this.ghosts = new THREE.Group(); scene.add(this.ghosts);

    this.state = null; this.boardKey = ''; this.overlayKey = ''; this.themeName = '';
    this.born = new Map();
    this.dirty = true; this.onTap = null; this.onHover = null;
    this.raycaster = new THREE.Raycaster();
    bindPointer(this.canvas, this);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.clock = performance.now();
    renderer.setAnimationLoop(t => this.tick(t));
  }

  geometry(n) {
    const { pad, step } = layout(1, n), r = step * 0.47, h = r * 0.38;
    return { pad, step, r, h, xz: s => [pad + (s % n) * step - 0.5, pad + Math.floor(s / n) * step - 0.5] };
  }

  // ------------------------------------------------------------ scene input
  render(scene) {
    const now = performance.now(), prev = this.state;
    if (prev && prev.n === scene.n && scene.anim) {
      const known = new Set(prev.stones.map(st => st.s * 3 + st.c));
      const fresh = scene.stones.filter(st => !known.has(st.s * 3 + st.c));
      if (fresh.length <= 2) for (const st of fresh) this.born.set(st.s, now);
    } else this.born.clear();
    this.state = scene;
    const geo = this.geometry(scene.n);

    const want = new Map(scene.stones.map(st => [st.s, st.c]));
    for (const [s, mesh] of this.stones) if (want.get(s) !== mesh.userData.c) { this.scene3.remove(mesh); this.stones.delete(s); this.born.delete(s); }
    for (const [s, c] of want) {
      let mesh = this.stones.get(s);
      if (!mesh) {
        mesh = new THREE.Mesh(this.stoneGeo, this.stoneMat[c]);
        mesh.castShadow = true; mesh.receiveShadow = true; mesh.userData.c = c;
        mesh.rotation.y = (s * 2.399) % 6.283;
        this.stones.set(s, mesh); this.scene3.add(mesh);
      }
      const [x, z] = geo.xz(s);
      mesh.scale.set(geo.r, geo.h, geo.r);
      mesh.position.set(x, geo.h, z);
    }

    this.ghosts.clear();
    const ghosts = [...scene.preview.map(g => [g.s, g.c, 0.5]), ...(scene.hover ? [[scene.hover.s, scene.hover.c, 0.35]] : [])];
    for (const [s, c, a] of ghosts) {
      const mat = this.ghostMat[c].clone(); mat.opacity = a;
      const mesh = new THREE.Mesh(this.stoneGeo, mat), [x, z] = geo.xz(s);
      mesh.scale.set(geo.r, geo.h, geo.r); mesh.position.set(x, geo.h, z);
      this.ghosts.add(mesh);
    }

    if (scene.theme !== this.themeName) {
      this.themeName = scene.theme;
      const color = BODY[scene.theme] ?? BODY.kaya;
      this.sideTex[scene.theme] ||= sideTexture(themeOf(scene.theme), this.renderer);
      this.bodyMat.map = this.sideTex[scene.theme]; this.bodyMat.color.setHex(color); this.bodyMat.needsUpdate = true;
      this.legMat.color.setHex(color);
    }
    // Softer contact shadow when the page UI is light.
    const light = document.body.dataset.ui === 'light';
    this.floor.material.opacity = light ? 0.35 : 0.9;
    this.overlay.position.y = geo.h * 2 + 0.0008;
    this.paintBoard();
    this.paintOverlay();
    this.dirty = true;
  }

  paintBoard() {
    const scene = this.state, n = scene.n;
    const key = JSON.stringify([n, scene.theme, scene.coords, scene.forbids, scene.best, scene.live && [scene.live.s, Math.round(scene.live.w * 100)]]);
    if (key === this.boardKey) return;
    this.boardKey = key;
    // The top plane is slightly larger than the playing square; paint the margin, then map
    // the square into the middle so grid coordinates match the 3D geometry.
    const ctx = this.boardCanvas.getContext('2d'), sx = 1 / TOP_X, sz = 1 / TOP_Z;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    drawGrain(ctx, TEX, themeOf(scene.theme));
    ctx.setTransform(sx, 0, 0, sz, TEX * (1 - sx) / 2, TEX * (1 - sz) / 2);
    const { pad, step } = drawSurface(ctx, TEX, scene);
    const at = s => [pad + (s % n) * step, pad + Math.floor(s / n) * step];
    for (const s of scene.forbids) drawForbid(ctx, ...at(s), step);
    if (scene.best !== null) drawBestRing(ctx, ...at(scene.best), step * 0.44, Math.max(3, step * 0.06));
    if (scene.live) drawLive(ctx, ...at(scene.live.s), step, scene.live.w);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.boardTex.needsUpdate = true;
  }

  // Move numbers, last-move dot and the winning line sit on the stone tops.
  paintOverlay() {
    const scene = this.state, n = scene.n;
    const key = JSON.stringify([n, scene.stones, scene.winLine, scene.preview, [...this.born.keys()]]);
    if (key === this.overlayKey) return;
    this.overlayKey = key;
    const ctx = this.overlayCanvas.getContext('2d'), { pad, step } = layout(TEX, n);
    const at = s => [pad + (s % n) * step, pad + Math.floor(s / n) * step];
    ctx.clearRect(0, 0, TEX, TEX);
    const r = step * 0.47, winning = new Set(scene.winLine || []);
    for (const st of scene.stones) {
      if (this.born.has(st.s)) continue;   // shown once the stone has settled
      const [x, y] = at(st.s);
      if (winning.has(st.s)) drawWinRing(ctx, x, y, r * 0.85);
      if (st.label) drawLabel(ctx, x, y, st.label, labelColor(st), r);
      else if (st.last) { ctx.fillStyle = ACCENT; ctx.beginPath(); ctx.arc(x, y, step * 0.1, 0, Math.PI * 2); ctx.fill(); }
    }
    for (const g of scene.preview) if (g.label) drawLabel(ctx, ...at(g.s), g.label, g.c === 1 ? '#ece8e0' : '#1a1a1a', r);
    this.overlayTex.needsUpdate = true;
  }

  // ------------------------------------------------------------ camera + picking
  resetCamera() {
    const sp = new THREE.Spherical().setFromVector3(this.camera.position.clone().sub(this.controls.target));
    this.camAnim = { from: { theta: sp.theta, phi: sp.phi, radius: sp.radius }, to: { ...HOME }, t0: performance.now(), dur: 800 };
  }

  pick(clientX, clientY) {
    if (!this.state) return null;
    const rect = this.canvas.getBoundingClientRect(), n = this.state.n, geo = this.geometry(n);
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, 1 - ((clientY - rect.top) / rect.height) * 2);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -geo.h), new THREE.Vector3());
    if (!hit) return null;
    const sx = Math.round((hit.x + 0.5 - geo.pad) / geo.step), sy = Math.round((hit.z + 0.5 - geo.pad) / geo.step);
    return sx < 0 || sy < 0 || sx >= n || sy >= n ? null : [sx, sy];
  }

  resize() {
    const w = this.host.clientWidth || 600, h = this.host.clientHeight || w;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  // ------------------------------------------------------------ frame loop
  tick(now) {
    const dt = Math.min(0.05, (now - this.clock) / 1000);
    this.clock = now;
    let active = this.controls.update(dt);

    if (this.camAnim) {
      const { from, to, t0, dur } = this.camAnim, k = Math.min(1, (now - t0) / dur), e = easeInOut(k);
      const lerp = key => from[key] + (to[key] - from[key]) * e;
      this.camera.position.setFromSpherical(new THREE.Spherical(lerp('radius'), lerp('phi'), lerp('theta'))).add(this.controls.target);
      this.camera.lookAt(this.controls.target);
      if (k >= 1) this.camAnim = null;
      active = true;
    }

    // Placement: the stone is lowered onto the board and settles with a slight slide.
    if (this.state && this.born.size) {
      const geo = this.geometry(this.state.n);
      let settled = false;
      for (const [s, t0] of this.born) {
        const mesh = this.stones.get(s);
        if (!mesh) { this.born.delete(s); continue; }
        const k = Math.max(0, (now - t0) / 260), [x, z] = geo.xz(s);
        if (k >= 1) { this.born.delete(s); mesh.position.set(x, geo.h, z); settled = true; continue; }
        const e = easeOut(k);
        mesh.position.set(x - (1 - e) * geo.step * 0.12, geo.h + (1 - e) * geo.h * 2.2, z - (1 - e) * geo.step * 0.08);
        active = true;
      }
      if (settled) { this.paintOverlay(); this.dirty = true; }
    }

    if (active || this.dirty) {
      this.renderer.render(this.scene3, this.camera);
      this.dirty = false;
    }
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.ro.disconnect();
    this.controls.dispose();
    this.scene3.traverse(o => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); });
    this.scene3.environment?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.canvas.remove();
  }
}
