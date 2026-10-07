// Canvas 2D board renderer. Used as the flat view, the 3D board texture and PNG export.
// It is a pure view: it draws a scene description built by app.js and maps pointers back
// to screen intersections. Rules and legality live in the Rust engine.

// Win-rate scale shared by every view: 0% red -> 50% amber -> 100% green (searcher's view).
// Muted so it reads as ink on wood rather than a light source.
export function winrateColor(value) {
  const w = Math.max(0, Math.min(1, value));
  const hue = w < 0.5 ? 6 + 36 * (w / 0.5) : 42 + 98 * ((w - 0.5) / 0.5);
  return `hsl(${hue.toFixed(1)} 52% 42%)`;
}

export function starPoints(n) {
  if (n === 15) return [3, 7, 11];
  if (n === 9) return [2, 4, 6];
  if (n === 20) return [3, 16];
  return [];
}

export const ACCENT = '#d4472c';
const SANS = '"Inter", "Helvetica Neue", "PingFang SC", "Noto Sans SC", system-ui, sans-serif';

export const THEMES = {
  kaya: { base: ['#e6c793', '#d9b27a'], grain: '122,78,34', line: 'rgba(43,28,12,0.82)', star: '#2b1c0c', coord: 'rgba(60,40,18,0.7)' },
  slate: { base: ['#323538', '#26282b'], grain: '220,214,200', fibre: 0.18, line: 'rgba(236,230,218,0.5)', star: '#ece6da', coord: 'rgba(236,230,218,0.5)' },
};
export const themeOf = name => THEMES[name] || THEMES.kaya;

// Board geometry in CSS pixels for a square of side `width`.
export function layout(width, n) {
  const pad = width * 0.065;
  return { pad, step: (width - 2 * pad) / (n - 1) };
}

function rng(seed) { return () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296; }

// Straight-grained wood (or honed slate), deterministic so redraws never shimmer.
export function drawGrain(ctx, width, theme) {
  const bg = ctx.createLinearGradient(0, 0, width, width);
  bg.addColorStop(0, theme.base[0]); bg.addColorStop(1, theme.base[1]);
  ctx.fillStyle = bg; ctx.fillRect(0, 0, width, width);
  const rand = rng(7), u = width / 1000;
  for (let i = 0; i < 26; i++) {   // broad soft bands
    const x = rand() * width, w = (20 + rand() * 70) * u;
    ctx.fillStyle = `rgba(${theme.grain},${(0.025 + rand() * 0.035) * (theme.fibre ?? 1)})`;
    ctx.fillRect(x, 0, w, width);
  }
  for (let i = 0; i < 260; i++) {  // fine fibres
    const x0 = rand() * width, amp = (2 + rand() * 6) * u, freq = 1 + rand() * 3, phase = rand() * 6.3;
    ctx.strokeStyle = `rgba(${theme.grain},${(0.04 + rand() * 0.1) * (theme.fibre ?? 1)})`;
    ctx.lineWidth = (0.4 + rand() * 1.2) * u;
    ctx.beginPath();
    for (let y = 0; y <= width; y += width / 30) {
      const x = x0 + Math.sin((y / width) * freq * 6.28 + phase) * amp;
      y === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  const v = ctx.createRadialGradient(width / 2, width / 2, width * 0.3, width / 2, width / 2, width * 0.75);
  v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,0.12)');
  ctx.fillStyle = v; ctx.fillRect(0, 0, width, width);
}

// Surface, grid, star points and coordinates.
export function drawSurface(ctx, width, scene) {
  const { n } = scene, theme = themeOf(scene.theme);
  const { pad, step } = layout(width, n);
  drawGrain(ctx, width, theme);
  ctx.strokeStyle = theme.line; ctx.lineWidth = Math.max(1, width / 900);
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const p = pad + i * step;
    ctx.moveTo(p, pad); ctx.lineTo(p, width - pad);
    ctx.moveTo(pad, p); ctx.lineTo(width - pad, p);
  }
  ctx.stroke();
  ctx.lineWidth = Math.max(1.5, width / 450);
  ctx.strokeRect(pad, pad, (n - 1) * step, (n - 1) * step);
  ctx.fillStyle = theme.star;
  for (const x of starPoints(n)) for (const y of starPoints(n)) {
    ctx.beginPath(); ctx.arc(pad + x * step, pad + y * step, Math.max(2, step * 0.075), 0, Math.PI * 2); ctx.fill();
  }
  if (scene.coords) {
    ctx.font = `500 ${Math.max(9, step * 0.27)}px ${SANS}`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = theme.coord;
    for (let i = 0; i < n; i++) {
      ctx.fillText(scene.colLabels[i], pad + i * step, pad * 0.45);
      ctx.fillText(scene.rowLabels[i], pad * 0.45, pad + i * step);
    }
  }
  return { pad, step };
}

export function drawForbid(ctx, x, y, step) {
  const d = step * 0.15;
  ctx.strokeStyle = ACCENT; ctx.lineWidth = Math.max(1.5, step * 0.06); ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(x - d, y - d); ctx.lineTo(x + d, y + d); ctx.moveTo(x + d, y - d); ctx.lineTo(x - d, y + d); ctx.stroke();
}

export function drawBestRing(ctx, x, y, r, width) {
  ctx.strokeStyle = ACCENT; ctx.lineWidth = width;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
}

// The engine's current candidate: a flat ink disc in the win-rate colour with its percentage.
export function drawLive(ctx, x, y, step, w) {
  const rr = step * 0.34;
  ctx.fillStyle = winrateColor(w);
  ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.fill();
  ctx.font = `600 ${Math.max(9, step * 0.27)}px ${SANS}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fbf8f2';
  ctx.fillText(`${Math.round(w * 100)}`, x, y + step * 0.01);
}

export function drawStone(ctx, x, y, r, c, alpha = 1) {
  ctx.save();
  ctx.globalAlpha = alpha;
  // Contact shadow, then the stone body with a soft top-left key light.
  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  ctx.beginPath(); ctx.ellipse(x + r * 0.1, y + r * 0.14, r * 0.98, r * 0.98, 0, 0, Math.PI * 2); ctx.fill();
  const g = ctx.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.05, x, y, r * 1.02);
  if (c === 1) { g.addColorStop(0, '#5a5c60'); g.addColorStop(0.35, '#26282b'); g.addColorStop(1, '#0b0c0d'); }
  else { g.addColorStop(0, '#ffffff'); g.addColorStop(0.55, '#f2eee6'); g.addColorStop(1, '#cdc6b8'); }
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

// Move number on a stone; `radius` is the stone radius in pixels.
export function drawLabel(ctx, x, y, text, color, radius) {
  const size = radius * (text.length <= 2 ? 0.86 : text.length === 3 ? 0.7 : 0.56);
  ctx.font = `600 ${size}px ${SANS}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = color;
  ctx.fillText(text, x, y + size * 0.05);
}

export const labelColor = st => st.last ? ACCENT : st.c === 1 ? '#ece8e0' : '#1a1a1a';

// Winning stones get a fine vermilion ring inset on the stone face.
export function drawWinRing(ctx, x, y, r) {
  ctx.strokeStyle = ACCENT; ctx.lineWidth = Math.max(1.5, r * 0.09);
  ctx.beginPath(); ctx.arc(x, y, r * 0.8, 0, Math.PI * 2); ctx.stroke();
}

// Draws a full flat board. `pop` maps a screen index to an appear-animation progress in [0,1].
export function drawBoard(ctx, width, scene, pop = null) {
  const n = scene.n, { pad, step } = drawSurface(ctx, width, scene);
  const at = s => [pad + (s % n) * step, pad + Math.floor(s / n) * step];
  const r = step * 0.47;
  for (const s of scene.forbids) drawForbid(ctx, ...at(s), step);
  const winning = new Set(scene.winLine || []);
  for (const st of scene.stones) {
    const [x, y] = at(st.s), k = pop ? pop(st.s) : 1, ease = 1 - Math.pow(1 - k, 3);
    drawStone(ctx, x, y, r * (1.12 - 0.12 * ease), st.c, ease);
    if (k < 1) continue;
    if (winning.has(st.s)) drawWinRing(ctx, x, y, r);
    if (st.label) drawLabel(ctx, x, y, st.label, labelColor(st), r);
    else if (st.last) { ctx.fillStyle = ACCENT; ctx.beginPath(); ctx.arc(x, y, step * 0.09, 0, Math.PI * 2); ctx.fill(); }
  }
  for (const g of scene.preview) {
    const [x, y] = at(g.s);
    drawStone(ctx, x, y, r, g.c, 0.5);
    if (g.label) drawLabel(ctx, x, y, g.label, g.c === 1 ? '#ece8e0' : '#1a1a1a', r);
  }
  if (scene.hover) drawStone(ctx, ...at(scene.hover.s), r, scene.hover.c, 0.38);
  if (scene.best !== null) drawBestRing(ctx, ...at(scene.best), r * 0.9, Math.max(2, step * 0.06));
  if (scene.live) drawLive(ctx, ...at(scene.live.s), step, scene.live.w);
  return { pad, step };
}

// Shared pointer handling: a short press without movement is a tap; anything else is a drag.
export function bindPointer(el, view) {
  let down = null;
  el.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY, id: e.pointerId, button: e.button }; });
  el.addEventListener('pointerup', e => {
    if (!down || down.id !== e.pointerId) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y), button = down.button;
    down = null;
    if (moved > 6 || button > 0) return;
    const hit = view.pick(e.clientX, e.clientY);
    if (hit && view.onTap) view.onTap(hit[0], hit[1]);
  });
  el.addEventListener('pointercancel', () => { down = null; });
  el.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse' || !view.onHover) return;
    view.onHover(down ? null : view.pick(e.clientX, e.clientY));
  });
  el.addEventListener('pointerleave', () => view.onHover && view.onHover(null));
}

export class Board2D {
  constructor(host) {
    this.host = host;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'board-canvas flat';
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.scene = null;
    this.born = new Map();   // screen index -> appear timestamp
    this.raf = 0;
    this.onTap = null; this.onHover = null;
    bindPointer(this.canvas, this);
    this.ro = new ResizeObserver(() => this.draw());
    this.ro.observe(host);
  }

  render(scene) {
    const now = performance.now(), prev = this.scene;
    if (scene.anim && prev && prev.n === scene.n) {
      const known = new Set(prev.stones.map(st => st.s * 3 + st.c));
      const fresh = scene.stones.filter(st => !known.has(st.s * 3 + st.c));
      if (fresh.length <= 2) for (const st of fresh) this.born.set(st.s, now);
    }
    this.scene = scene;
    this.draw();
  }

  draw() {
    cancelAnimationFrame(this.raf);
    if (!this.scene) return;
    const width = Math.min(this.host.clientWidth, this.host.clientHeight) || 600, dpr = Math.min(window.devicePixelRatio || 1, 3);
    this.canvas.style.width = this.canvas.style.height = width + 'px';
    if (this.canvas.width !== Math.round(width * dpr)) this.canvas.width = this.canvas.height = Math.round(width * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const now = performance.now();
    let animating = false;
    const pop = s => {
      const t0 = this.born.get(s);
      if (t0 === undefined) return 1;
      const k = (now - t0) / 160;
      if (k >= 1) { this.born.delete(s); return 1; }
      animating = true;
      return Math.max(0, k);
    };
    drawBoard(this.ctx, width, this.scene, pop);
    if (animating) this.raf = requestAnimationFrame(() => this.draw());
  }

  pick(clientX, clientY) {
    if (!this.scene) return null;
    const rect = this.canvas.getBoundingClientRect(), n = this.scene.n;
    const { pad, step } = layout(rect.width, n);
    const sx = Math.round((clientX - rect.left - pad) / step), sy = Math.round((clientY - rect.top - pad) / step);
    return sx < 0 || sy < 0 || sx >= n || sy >= n ? null : [sx, sy];
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.canvas.remove();
  }
}
