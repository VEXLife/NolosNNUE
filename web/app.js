// UI controller. Legality, rules and search all live in the Rust engine (WASM worker);
// this file mirrors the authoritative YXSTATUS and turns it into a scene for the renderers.
import { t, setLang, getLang, detectLang, translateDom, LANGS } from './i18n.js';
import { Board2D, drawBoard, winrateColor } from './board2d.js';

const $ = id => document.getElementById(id);
// Single-file build (scripts/build-web.sh --single) provides NOLOS_BUNDLE with blob URLs and embedded assets.
const bundle = globalThis.NOLOS_BUNDLE;
const worker = new Worker(bundle ? bundle.worker : new URL('worker.js', import.meta.url), { type: 'module' });

// ---------------------------------------------------------------- preferences
const DEFAULTS = { lang: null, theme: 'kaya', ui: 'dark', numbers: 'all', coords: true, hover: true, sound: true, anim: true, view: '3d' };
const prefs = (() => {
  try {
    const saved = { ...DEFAULTS, ...JSON.parse(localStorage.getItem('nolos.prefs') || '{}') };
    if (!['kaya', 'slate'].includes(saved.theme)) saved.theme = 'kaya';
    if (!['dark', 'light'].includes(saved.ui)) saved.ui = 'dark';
    return saved;
  }
  catch { return { ...DEFAULTS }; }
})();
function savePrefs() { try { localStorage.setItem('nolos.prefs', JSON.stringify(prefs)); } catch { /* private mode */ } }
setLang(detectLang(prefs.lang));

// ---------------------------------------------------------------- engine mirror
let ready = false, busy = false;
let state = { size: 15, rule: 0, next: 1, winner: 0, board: '0'.repeat(225), history: [] };
let forbids = new Set(), best = null, live = { p: null, winrate: null };
let started = 0, searchKind = null, searchSide = 1, searchPly = null;
let pendingAuto = false, pendingRecord = false, appliedRecord = null, requestId = 0;
let pendingShare = null, weightsInfo = null, vcfPlies = 0, evalShown = false;
// UI-only state.
let reviewAt = null, hoverCell = null, pvMoves = [], pvPreview = null, chart = [];
// Display transform: rotations/flips only affect display and notation; the engine always
// receives raw coordinates. p2s: raw point -> screen point, s2p: the inverse.
const view = { rot: 0, hflip: false, vflip: false, down: true, p2s: null, s2p: null };

// ---------------------------------------------------------------- helpers
const sideName = c => t(c === 1 ? 'black' : 'white');
function notice(message = '') { $('notice-text').textContent = message; $('notice').hidden = !message; }
function log(line) {
  const el = $('protocol-log');
  el.textContent = (el.textContent + line + '\n').split('\n').slice(-700).join('\n');
  el.scrollTop = el.scrollHeight;
}
function buildView() {
  const n = state.size, p2s = new Uint16Array(n * n), s2p = new Uint16Array(n * n);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const fx = view.hflip ? n - 1 - x : x, fy = view.vflip ? n - 1 - y : y;
    let sx, sy;
    if (view.rot === 1) { sx = n - 1 - fy; sy = fx; }
    else if (view.rot === 2) { sx = n - 1 - fx; sy = n - 1 - fy; }
    else if (view.rot === 3) { sx = fy; sy = n - 1 - fx; }
    else { sx = fx; sy = fy; }
    const p = y * n + x, s = sy * n + sx;
    p2s[p] = s; s2p[s] = p;
  }
  view.p2s = p2s; view.s2p = s2p;
}
function screenXY(p) { const n = state.size, s = view.p2s[p]; return [s % n, (s / n) | 0]; }
// Letters always run left to right on screen; row numbering direction is selectable.
function labelOf(p) { const n = state.size, [sx, sy] = screenXY(p); return String.fromCharCode(97 + sx) + (view.down ? sy + 1 : n - sy); }
function recordOf(history) { return history.map(([p]) => labelOf(p)).join(''); }
// Share links use raw coordinates so they do not depend on the viewer's transform.
function rawLabel(p, n) { return String.fromCharCode(97 + p % n) + (((p / n) | 0) + 1); }
function viewName() {
  const parts = [view.hflip ? t('view.hflip') : null, view.vflip ? t('view.vflip') : null, t('view.rot' + view.rot)].filter(Boolean);
  return t('view.name', { dir: t(view.down ? 'view.dirDown' : 'view.dirUp'), parts: parts.join(' + ') });
}
function parseMoves(text, toPoint) {
  const n = state.size, clean = String(text).toLowerCase().replace(/[\s,;、]+/g, ''), moves = [];
  if (!clean) throw Error(t('p.empty'));
  let i = 0;
  while (i < clean.length) {
    const k = moves.length + 1, sx = clean.charCodeAt(i) - 97;
    if (sx < 0 || sx > 25) throw Error(t('p.letter', { k, s: clean.slice(i, i + 4) }));
    if (sx >= n) throw Error(t('p.col', { k, c: clean[i].toUpperCase(), max: String.fromCharCode(96 + n) }));
    i++;
    let digits = '';
    while (i < clean.length && digits.length < 2 && clean[i] >= '0' && clean[i] <= '9') digits += clean[i++];
    if (!digits) throw Error(t('p.row', { k }));
    const row = Number(digits);
    if (row < 1 || row > n) throw Error(t('p.rowRange', { k, r: row, n }));
    const p = toPoint(sx, row);
    if (p === undefined) throw Error(t('p.map', { k }));
    moves.push(p);
  }
  const seen = new Set();
  moves.forEach((p, k) => { if (seen.has(p)) throw Error(t('p.dup', { k: k + 1, at: labelOf(p) })); seen.add(p); });
  return moves;
}
function parseRecord(text) {
  const n = state.size;
  return parseMoves(text, (sx, row) => view.s2p[(view.down ? row - 1 : n - row) * n + sx]);
}

// ---------------------------------------------------------------- protocol
function send(lines) {
  if (!ready) return;
  if (typeof lines === 'string') lines = [lines];
  lines.forEach(x => log('→ ' + x));
  worker.postMessage({ type: 'commands', lines, requestId: ++requestId });
}
// Analysis has no time limit and runs until Stop; engine moves use the per-move time.
const NO_TIME_LIMIT = 2147483647;
function settings(infinite = false) {
  return [`INFO timeout_turn ${infinite ? NO_TIME_LIMIT : $('time').value}`,
    `INFO max_depth ${Math.max(1, Number($('max-depth').value) || 64)}`,
    `INFO max_node ${Math.max(1, Number($('max-nodes').value) || 100000000)}`];
}
function rows(history = state.history, own = state.next, size = state.size) {
  return history.map(([p, c]) => `${p % size},${Math.floor(p / size)},${c === own ? 1 : 2}`);
}
// YXBOARD rebuilds the engine board from the full history without thinking; BOARD also searches.
function sync(history = state.history, own = history.length % 2 + 1, thinking = false) {
  return [thinking ? 'BOARD' : 'YXBOARD', ...rows(history, own), 'DONE'];
}
const forbidCmd = () => Number($('rule').value) === 2 ? ['YXSHOWFORBID'] : [];
function status() { send(['YXSTATUS', ...forbidCmd()]); }
function humanTurn() { return $('mode').value === 'analysis' || state.next === ($('mode').value === 'black' ? 1 : 2); }

function search(suggest = false) {
  if (busy || pendingRecord || state.winner || state.history.length >= state.size ** 2) return;
  best = null; resetLive(); started = performance.now();
  searchKind = suggest ? 'suggest' : 'move'; searchSide = state.next; searchPly = state.history.length;
  setBusy(true);
  send([...settings(suggest), ...sync(state.history, state.next, !suggest), ...(suggest ? ['YXSUGGEST'] : [])]);
}
function newGame() {
  notice(); searchKind = null; setBusy(false); best = null; resetLive(); forbids.clear();
  reviewAt = null; chart = [];
  $('record').value = ''; $('record').classList.remove('dirty');
  pendingAuto = true;
  send([`START ${$('size').value}`, `INFO rule ${$('rule').value}`, 'YXSTATUS', ...forbidCmd()]);
}
// Changing mode only changes who moves: the board and record stay. YXBOARD restates the
// current position; if it is now the engine's turn it replies. Free play never auto-replies.
function changeMode() {
  notice(); best = null; resetLive(); forbids.clear(); searchKind = null;
  if (busy) send('YXSTOP');
  pendingAuto = true;
  send([...sync(state.history, state.next), 'YXSTATUS', ...forbidCmd()]);
  renderPlayers();
}
function play(x, y) {
  if (!ready || busy || pendingRecord || state.winner) return;
  notice(); best = null; pendingAuto = true;
  send([...sync(state.history, state.next), `PLAY ${x},${y}`, 'YXSTATUS', ...(state.rule === 2 ? ['YXSHOWFORBID'] : [])]);
}
function undo() {
  if (!ready || busy || pendingRecord || !state.history.length) return;
  best = null; reviewAt = null;
  const count = $('mode').value === 'analysis' ? 1 : humanTurn() && state.history.length > 1 ? 2 : 1;
  const history = state.history.slice(0, -count);
  send([...sync(history, history.length % 2 + 1), 'YXSTATUS', ...(state.rule === 2 ? ['YXSHOWFORBID'] : [])]);
}
// Branch from the reviewed position: same as undoing back to it, then let the engine reply if due.
function branch() {
  if (reviewAt === null || busy || pendingRecord) return;
  const history = state.history.slice(0, reviewAt);
  reviewAt = null; best = null; resetLive(); notice(); pendingAuto = true;
  send([...sync(history, history.length % 2 + 1), 'YXSTATUS', ...forbidCmd()]);
}
// Records are only applied on confirmation (Enter or blur) so a half-typed record is never played.
function applyRecord(text, quiet = false) {
  if (!ready) return;
  const value = String(text ?? '');
  if (pendingRecord && value === appliedRecord) return;   // same record still awaiting the engine
  if (busy) { if (!quiet) notice(t('n.busyRecord')); return; }
  if (!value.trim()) { if (!quiet) notice(t('n.empty')); syncRecord(true); return; }
  let moves;
  try { moves = parseRecord(value); }
  catch (e) { if (!quiet) { notice(t('n.badRecord', { msg: e.message })); syncRecord(true); } return; }
  const history = moves.map((p, k) => [p, k % 2 + 1]);
  if (history.length === state.history.length && history.every((m, k) => m[0] === state.history[k][0])) { if (!quiet) notice(); syncRecord(true); return; }
  loadHistory(history);
  appliedRecord = value;
  const field = $('record'); field.value = history.map(([p]) => labelOf(p)).join(''); field.classList.remove('dirty');
}
function loadHistory(history) {
  notice(); best = null; resetLive(); pendingAuto = true; pendingRecord = true; forbids.clear();
  reviewAt = null; chart = [];
  send(['START ' + state.size, `INFO rule ${$('rule').value}`, 'YXBOARD', ...rows(history, history.length % 2 + 1, state.size), 'DONE', 'YXSTATUS', ...forbidCmd()]);
}

// ---------------------------------------------------------------- engine status UI
function setBusy(value) {
  busy = value;
  $('engine-status').textContent = t(busy ? 'engine.thinking' : ready ? 'engine.ready' : 'engine.loading');
  $('engine-pill').className = 'engine-pill ' + (busy ? 'thinking' : ready ? 'ready' : '');
  refreshControls();
}
function refreshControls() {
  const idle = ready && !busy, reviewing = reviewAt !== null;
  $('stop').disabled = !busy;
  for (const id of ['mode', 'rule', 'size', 'weights-file', 'record']) $(id).disabled = !idle;
  for (const id of ['new-game', 'use-hce', 'load-url']) $(id).disabled = !idle;
  $('undo').disabled = !idle || reviewing || !state.history.length;
  $('analyze').disabled = !idle || reviewing || !!state.winner;
  $('play-best').disabled = !idle || reviewing || !best;
  $('branch').hidden = !reviewing;
  $('branch').disabled = !idle;
  $('file-drop').classList.toggle('disabled', !idle);
  const len = state.history.length, at = reviewAt ?? len;
  $('nav-first').disabled = $('nav-prev').disabled = at === 0;
  $('nav-next').disabled = $('nav-last').disabled = at === len;
  $('nav-slider').max = len; $('nav-slider').value = at;
  $('nav-slider').style.setProperty('--fill', len ? `${(at / len) * 100}%` : '0%');
}
// The board marker belongs to one position; the numbers stay until the next search starts.
function clearMarker() { live.p = null; pvPreview = null; }
function resetLive() {
  live = { p: null, winrate: null }; vcfPlies = 0; pvPreview = null;
  $('vcf-tag').hidden = true;
  for (const id of ['eval-value', 'depth', 'nodes', 'elapsed', 'nps']) $(id).textContent = '—';
  evalShown = false; $('eval-caption').textContent = t('eval.wait');
  pvMoves = []; setPV([]);
  $('winrate').textContent = '—'; $('winrate').style.color = '';
  $('balance-fill').style.width = '50%'; $('balance-fill').style.background = '';
  $('gauge-fill').style.strokeDashoffset = String(GAUGE_LEN); $('gauge-fill').style.stroke = '';
}
const GAUGE_LEN = 2 * Math.PI * 50;
function showWinrate(value) {
  const w = Math.max(0, Math.min(1, value)), color = winrateColor(w);
  live.winrate = w;
  $('winrate').textContent = `${(w * 100).toFixed(1)}%`; $('winrate').style.color = color;
  $('balance-fill').style.width = `${w * 100}%`; $('balance-fill').style.background = color;
  $('gauge-fill').style.strokeDashoffset = String(GAUGE_LEN * (1 - w)); $('gauge-fill').style.stroke = color;
  if (searchPly !== null) { chart[searchPly] = searchSide === 1 ? w : 1 - w; drawChart(); }
}
function setPV(items) {
  pvMoves = items.map(item => {
    const [x, y] = item.split(',').map(Number);
    return Number.isFinite(x) && Number.isFinite(y) ? y * state.size + x : null;
  });
  const side = searchSide;
  $('pv').replaceChildren(...items.map((item, i) => {
    const el = document.createElement('button');
    const p = pvMoves[i];
    el.className = 'pv-move ' + ((i % 2 === 0) === (side === 1) ? 'b' : 'w');
    el.textContent = p === null ? item : labelOf(p).toUpperCase();
    el.type = 'button';
    const show = () => { pvPreview = i; render(); };
    const hide = () => { pvPreview = null; render(); };
    el.addEventListener('mouseenter', show); el.addEventListener('focus', show);
    el.addEventListener('mouseleave', hide); el.addEventListener('blur', hide);
    return el;
  }));
  if (!items.length) $('pv').innerHTML = `<span class="muted">${t('eval.pvEmpty')}</span>`;
}
function drawChart() {
  const svg = $('chart'), pts = [];
  const len = Math.max(state.history.length, chart.length - 1, 1);
  chart.forEach((w, k) => { if (w !== undefined) pts.push([(k / len) * 300, 4 + (1 - w) * 62]); });
  $('chart-empty').hidden = pts.length > 0;
  if (!pts.length) { svg.innerHTML = ''; return; }
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
  const area = `${line}L${pts.at(-1)[0].toFixed(1)},35L${pts[0][0].toFixed(1)},35Z`;
  const last = pts.at(-1);
  svg.innerHTML = `<line x1="0" y1="35" x2="300" y2="35" class="mid"/><path d="${area}" class="ar"/><path d="${line}" class="ln"/>`
    + `<circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" class="dotc"/>`;
}

// ---------------------------------------------------------------- scene + rendering
let renderer = null, rendererKind = null;
const stoneBorn = new Map();
function displayHistory() { return reviewAt === null ? state.history : state.history.slice(0, reviewAt); }
function winLine(history) {
  const n = state.size, last = history.at(-1);
  if (!last || !state.winner || reviewAt !== null || last[1] !== state.winner) return null;
  const [p, c] = last, x0 = p % n, y0 = (p / n) | 0, board = state.board;
  for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
    const line = [p];
    for (const sgn of [-1, 1]) {
      let x = x0 + dx * sgn, y = y0 + dy * sgn;
      while (x >= 0 && y >= 0 && x < n && y < n && Number(board[y * n + x]) === c) {
        sgn < 0 ? line.unshift(y * n + x) : line.push(y * n + x);
        x += dx * sgn; y += dy * sgn;
      }
    }
    if (line.length >= 5) return line;
  }
  return null;
}
function buildScene(forExport = false) {
  const n = state.size, history = displayHistory(), reviewing = reviewAt !== null;
  const numbers = forExport ? 'all' : prefs.numbers, from = numbers === 'recent' ? history.length - 10 : 0;
  const stones = history.map(([p, c], k) => ({
    s: view.p2s[p], c, last: k === history.length - 1,
    label: numbers !== 'off' && k >= from ? String(k + 1) : null,
  }));
  const scene = {
    n, theme: prefs.theme, coords: prefs.coords || forExport, anim: prefs.anim,
    colLabels: Array.from({ length: n }, (_, i) => String.fromCharCode(65 + i)),
    rowLabels: Array.from({ length: n }, (_, i) => String(view.down ? i + 1 : n - i)),
    stones, forbids: [], preview: [], hover: null, best: null, live: null, winLine: null,
  };
  if (forExport) return scene;
  if (!reviewing && state.next === 1) scene.forbids = [...forbids].map(p => view.p2s[p]);
  const line = winLine(history);
  if (line) scene.winLine = line.map(p => view.p2s[p]);
  if (!reviewing) {
    if (best && !busy) scene.best = view.p2s[best[1] * n + best[0]];
    if (live.p !== null && live.winrate !== null) scene.live = { s: view.p2s[live.p], w: live.winrate, busy };
    if (pvPreview !== null) {
      const occupied = new Set(history.map(([p]) => p));
      pvMoves.slice(0, pvPreview + 1).forEach((p, i) => {
        if (p === null || occupied.has(p)) return;
        scene.preview.push({ s: view.p2s[p], c: i % 2 === 0 ? searchSide : 3 - searchSide, label: String(i + 1) });
      });
      scene.live = null;
    }
    if (prefs.hover && hoverCell && ready && !busy && !pendingRecord && !state.winner && humanTurn()) {
      const s = hoverCell[1] * n + hoverCell[0], p = view.s2p[s];
      if (state.board[p] === '0' && !(state.next === 1 && forbids.has(p))) scene.hover = { s, c: state.next };
    }
  }
  return scene;
}
function render() {
  if (renderer) renderer.render(buildScene());
  renderHud();
}
function renderHud() {
  const n = state.size, len = state.history.length, reviewing = reviewAt !== null;
  const full = len === n * n && !state.winner;
  $('turn-text').textContent = state.winner ? t('turn.win', { side: sideName(state.winner) }) : full ? t('turn.full') : t('turn.move', { side: sideName(state.next) });
  $('move-counter').textContent = t('move.count', { n: reviewing ? reviewAt : len });
  $('position-status').textContent = reviewing ? t('status.review', { k: reviewAt, n: len })
    : state.winner ? t('status.over') : full ? t('status.full') : busy ? t('status.search') : humanTurn() ? t('status.click') : t('status.wait');
  $('board-frame').classList.toggle('reviewing', reviewing);
  renderPlayers();
  refreshControls();
}
function renderPlayers() {
  const mode = $('mode').value;
  const who = c => mode === 'analysis' ? t('player.free') : (mode === 'black') === (c === 1) ? t('player.you') : t('player.engine');
  for (const c of [1, 2]) {
    const el = $(c === 1 ? 'player-black' : 'player-white');
    $(c === 1 ? 'player-black-who' : 'player-white-who').textContent = who(c);
    el.classList.toggle('active', !state.winner && state.next === c && reviewAt === null);
    el.classList.toggle('thinking', busy && searchSide === c);
    el.classList.toggle('winner', state.winner === c);
  }
}

async function useRenderer(kind) {
  let next = null;
  if (kind === '3d') {
    try { const { Board3D } = await import('./board3d.js'); next = new Board3D($('board-host')); }
    catch (e) { console.warn('WebGL view unavailable, using 2D', e); kind = '2d'; }
  }
  if (!next) next = new Board2D($('board-host'));
  if (renderer) renderer.dispose();
  renderer = next; rendererKind = kind;
  renderer.onTap = onBoardTap;
  renderer.onHover = onBoardHover;
  for (const b of $('view-seg').querySelectorAll('button')) b.classList.toggle('on', b.dataset.value === kind);
  $('reset-camera').hidden = kind !== '3d';
  render();
}
function onBoardTap(sx, sy) {
  if (reviewAt !== null) { notice(t('n.reviewing')); return; }
  if (!humanTurn()) return;
  const n = state.size, p = view.s2p[sy * n + sx];
  play(p % n, Math.floor(p / n));
}
function onBoardHover(hit) {
  const prev = hoverCell;
  hoverCell = hit;
  if (prev?.[0] === hit?.[0] && prev?.[1] === hit?.[1]) return;
  $('hover-coord').textContent = hit ? labelOf(view.s2p[hit[1] * state.size + hit[0]]).toUpperCase() : '';
  render();
}

// ---------------------------------------------------------------- record + move list
function recordDraft() { const el = $('record'); el.classList.toggle('dirty', el.value !== recordOf(state.history)); }
function syncRecord(force = false) {
  const el = $('record');
  if (force || document.activeElement !== el) el.value = recordOf(state.history);
  recordDraft();
  $('record-count').textContent = t('moves.n', { n: state.history.length });
  $('view-state').textContent = viewName();
  renderMoveList();
}
function renderMoveList() {
  const list = $('move-list'), at = reviewAt ?? state.history.length;
  if (!state.history.length) { list.innerHTML = `<li class="muted">${t('rec.listEmpty')}</li>`; return; }
  list.replaceChildren(...state.history.map(([p, c], k) => {
    const li = document.createElement('li'), b = document.createElement('button');
    b.type = 'button';
    b.className = (c === 1 ? 'b' : 'w') + (k + 1 === at ? ' current' : '');
    b.innerHTML = `<i>${k + 1}</i>${labelOf(p).toUpperCase()}`;
    b.onclick = () => setReview(k + 1);
    li.appendChild(b);
    return li;
  }));
  // Scroll inside the list only; scrollIntoView would also move the page.
  const cur = list.querySelector('.current');
  if (cur) {
    const top = cur.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top + cur.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = top - list.clientHeight / 2;
  }
}
function setReview(k) {
  const len = state.history.length;
  k = Math.max(0, Math.min(len, k));
  reviewAt = k >= len ? null : k;
  renderMoveList();
  render();
}

// ---------------------------------------------------------------- sound, export
let audio = null;
function clack(color) {
  if (!prefs.sound) return;
  try {
    audio ||= new AudioContext();
    const t0 = audio.currentTime, len = 0.07, rate = audio.sampleRate;
    const buf = audio.createBuffer(1, Math.floor(rate * len), rate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / d.length, 7);
    const src = audio.createBufferSource(); src.buffer = buf;
    const bp = audio.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = color === 1 ? 2100 : 2700; bp.Q.value = 1.4;
    const g = audio.createGain(); g.gain.value = 0.7;
    src.connect(bp).connect(g).connect(audio.destination); src.start(t0);
    const osc = audio.createOscillator(), og = audio.createGain();
    osc.frequency.setValueAtTime(180, t0); osc.frequency.exponentialRampToValueAtTime(70, t0 + 0.09);
    og.gain.setValueAtTime(0.22, t0); og.gain.exponentialRampToValueAtTime(0.001, t0 + 0.11);
    osc.connect(og).connect(audio.destination); osc.start(t0); osc.stop(t0 + 0.12);
  } catch { /* audio is optional */ }
}
function exportPng() {
  const size = 1400, c = document.createElement('canvas');
  c.width = c.height = size;
  drawBoard(c.getContext('2d'), size, buildScene(true));
  c.toBlob(blob => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nolos-${state.size}x${state.size}-${state.history.length}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }, 'image/png');
}
async function copyText(text, okMessage) {
  try { await navigator.clipboard.writeText(text); notice(okMessage); }
  catch { $('record').select(); notice(t('n.clipboard')); }
}
function shareUrl() {
  const n = state.size, moves = state.history.map(([p]) => rawLabel(p, n)).join('');
  return `${location.origin}${location.pathname}#size=${n}&rule=${state.rule}&moves=${moves}`;
}
function readShare() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.has('moves')) return null;
  const size = ['9', '15', '20'].includes(params.get('size')) ? params.get('size') : '15';
  const rule = ['0', '1', '2'].includes(params.get('rule')) ? params.get('rule') : '0';
  return { size, rule, moves: params.get('moves') };
}
function applyShare(share) {
  $('size').value = share.size; $('rule').value = share.rule; $('mode').value = 'analysis';
  state = { ...state, size: Number(share.size) };
  buildView();
  try {
    const n = state.size, moves = parseMoves(share.moves, (sx, row) => (row - 1) * n + sx);
    loadHistory(moves.map((p, k) => [p, k % 2 + 1]));
    pendingShare = moves.length;
  } catch (e) { notice(t('n.badRecord', { msg: e.message })); newGame(); }
}

// ---------------------------------------------------------------- worker messages
worker.onmessage = ({ data }) => {
  if (data.type === 'ready') {
    ready = true; setBusy(false);
    if (bundle?.nnue) weights(bundle.nnue.slice().buffer, bundle.nnueName).catch(e => notice(e.message));
    const share = readShare();
    if (share) applyShare(share); else newGame();
    return;
  }
  if (data.type === 'error') {
    notice(data.error); searchKind = null; pendingRecord = false; setBusy(false);
    if (!ready) { $('engine-status').textContent = t('engine.failed'); $('engine-pill').className = 'engine-pill error'; }
    return;
  }
  if (data.type === 'weights') {
    if (data.ok) { weightsInfo = { name: data.name, hash: data.hash }; renderWeights(); notice(); }
    else notice(t('n.badWeights'));
    return;
  }
  if (data.type === 'busy') {
    if (data.requestId === requestId) { setBusy(data.busy); if (!data.busy) searchKind = null; render(); }
    return;
  }
  if (data.type === 'idle') { render(); return; }
  if (data.type !== 'line') return;
  const line = data.line;
  log('← ' + line);
  if (line.startsWith('ERROR ')) {
    notice(line.slice(6)); pendingAuto = false; pendingRecord = false;
    if (searchKind) { searchKind = null; setBusy(false); }
    resetLive(); render();
  }
  if (line.startsWith('MESSAGE STATUS ')) {
    try {
      const prevLen = state.history.length;
      state = JSON.parse(line.slice(15));
      $('size').value = state.size; $('rule').value = state.rule;
      forbids.clear(); pendingRecord = false; clearMarker(); buildView();
      if (reviewAt !== null && reviewAt >= state.history.length) reviewAt = null;
      chart.length = Math.min(chart.length, state.history.length + 1);
      if (state.history.length === prevLen + 1) clack(state.history.at(-1)[1]);
      if (pendingShare !== null) { notice(t('n.linkLoaded', { n: pendingShare })); pendingShare = null; }
      syncRecord(); drawChart(); render();
      if (pendingAuto) { pendingAuto = false; if (!humanTurn() && !state.winner) search(); }
    } catch (e) { notice(t('n.statusParse', { msg: e })); }
    return;
  }
  if (line.startsWith('FORBID ')) {
    forbids.clear();
    const s = line.slice(7).replace(/\.$/, '');
    for (let i = 0; i + 3 < s.length; i += 4) forbids.add(Number(s.slice(i + 2, i + 4)) * state.size + Number(s.slice(i, i + 2)));
    render();
    return;
  }
  const move = line.match(/^(SUGGEST )?(\d+),(\d+)$/);
  if (move) {
    if (move[1]) { best = [+move[2], +move[3]]; searchKind = null; setBusy(false); render(); }
    else if (searchKind === 'move') { setBusy(false); searchKind = null; status(); }
    return;
  }
  if (line.startsWith('MESSAGE REALTIME BEST ')) {
    const [x, y] = line.slice(22).split(',').map(Number);
    if (Number.isFinite(x) && Number.isFinite(y)) { live.p = y * state.size + x; render(); }
    return;
  }
  if (line.startsWith('MESSAGE VCF proof ')) {
    vcfPlies = Number(line.split(' ')[3]) || 0;
    if (vcfPlies) { $('vcf-tag').textContent = t('eval.vcf', { n: vcfPlies }); $('vcf-tag').hidden = false; }
    return;
  }
  if (line.startsWith('INFO ')) {
    const [, key, ...tail] = line.split(' '), v = tail.join(' ');
    if (key === 'DEPTH') $('depth').textContent = v;
    if (key === 'NODES') {
      const nodes = Number(v), secs = (performance.now() - started) / 1000;
      $('nodes').textContent = compact(nodes);
      $('nps').textContent = secs > 0.05 ? compact(nodes / secs) + '/s' : '—';
    }
    if (key === 'EVAL') { $('eval-value').textContent = v; evalShown = true; $('eval-caption').textContent = t('eval.side', { side: sideName(searchSide) }); }
    if (key === 'WINRATE' && Number.isFinite(Number(v))) showWinrate(Number(v));
    if (key === 'BESTLINE') {
      const pv = v.split(/\s+/).filter(Boolean);
      setPV(pv);
      // The first PV move is the current best candidate; it carries this iteration's WINRATE.
      live.p = pvMoves[0] ?? null;
      render();
    }
    $('elapsed').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`;
  }
};
function compact(x) {
  if (!Number.isFinite(x)) return '—';
  if (x >= 1e9) return (x / 1e9).toFixed(2) + 'G';
  if (x >= 1e6) return (x / 1e6).toFixed(2) + 'M';
  if (x >= 1e4) return (x / 1e3).toFixed(1) + 'k';
  return Math.round(x).toLocaleString();
}

// ---------------------------------------------------------------- weights
function renderWeights() {
  const tag = t(weightsInfo ? 'eval.nnue' : 'eval.hce');
  $('evaluator-tag').textContent = tag; $('evaluator-tag-2').textContent = tag;
  $('weights-name').textContent = weightsInfo ? t('net.current.loaded', weightsInfo) : t('net.current.hce');
}
async function weights(bytes, name) {
  if (!ready || busy) throw Error(t('n.waitEngine'));
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(x => x.toString(16).padStart(2, '0')).join('');
  worker.postMessage({ type: 'weights', bytes, name, hash }, [bytes]);
}
async function loadWeightsFile(file) {
  try { if (file) await weights(await file.arrayBuffer(), file.name); }
  catch (err) { notice(err.message); }
}

// ---------------------------------------------------------------- language
function applyLanguage() {
  translateDom();
  for (const o of $('time').options) o.textContent = t('sec', { n: Number(o.value) / 1000 });
  $('lang-label').textContent = LANGS[getLang()];
  $('lang-seg').replaceChildren(...Object.entries(LANGS).map(([code, name]) => {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = name; b.dataset.value = code;
    b.classList.toggle('on', code === getLang());
    b.onclick = () => switchLang(code);
    return b;
  }));
  $('keys-list').replaceChildren(...t('keys.list').flatMap(([k, d]) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.innerHTML = k.split(' ').map(x => `<kbd>${x}</kbd>`).join(' '); dd.textContent = d;
    return [dt, dd];
  }));
  $('eval-caption').textContent = evalShown ? t('eval.side', { side: sideName(searchSide) }) : t('eval.wait');
  renderWeights();
  setBusy(busy);
  if (!pvMoves.length) setPV([]);
  syncRecord();
  renderHud();
}
function switchLang(code) { setLang(code); prefs.lang = code; savePrefs(); applyLanguage(); }

// ---------------------------------------------------------------- wiring
$('new-game').onclick = newGame;
for (const id of ['rule', 'size']) $(id).onchange = () => { if (busy) send('YXSTOP'); newGame(); };
$('mode').onchange = changeMode;
$('stop').onclick = () => send('YXSTOP');
$('analyze').onclick = () => search(true);
$('play-best').onclick = () => { if (best) play(...best); };
$('undo').onclick = undo;
$('branch').onclick = branch;
$('notice-close').onclick = () => notice();

$('nav-first').onclick = () => setReview(0);
$('nav-prev').onclick = () => setReview((reviewAt ?? state.history.length) - 1);
$('nav-next').onclick = () => setReview((reviewAt ?? state.history.length) + 1);
$('nav-last').onclick = () => setReview(state.history.length);
$('nav-slider').oninput = e => setReview(Number(e.target.value));

$('record').addEventListener('input', () => {
  const el = $('record');
  if (/[\r\n]/.test(el.value)) {
    const before = el.value, at = el.selectionStart;
    el.value = before.replace(/[\r\n]+/g, '');
    const caret = Math.max(0, at - (before.length - el.value.length));
    try { el.setSelectionRange(caret, caret); } catch { /* not focused */ }
  }
  recordDraft();
});
$('record').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  applyRecord($('record').value);
});
$('record').addEventListener('change', () => applyRecord($('record').value));
$('record-copy').onclick = () => { const text = recordOf(state.history); copyText(text, text ? t('n.copied', { text }) : t('n.copiedEmpty')); };
$('share-link').onclick = () => copyText(shareUrl(), t('n.linkCopied'));
$('export-png').onclick = exportPng;

function applyView() {
  if (view.hflip && view.vflip) { view.hflip = false; view.vflip = false; view.rot = (view.rot + 2) % 4; }
  buildView(); syncRecord(true); render();
}
$('rotate-cw').onclick = () => { view.rot = (view.rot + 1) % 4; applyView(); };
$('rotate-ccw').onclick = () => { view.rot = (view.rot + 3) % 4; applyView(); };
$('flip-horizontal').onclick = () => { view.hflip = !view.hflip; applyView(); };
$('flip-vertical').onclick = () => { view.vflip = !view.vflip; applyView(); };
$('reset-view').onclick = () => { view.rot = 0; view.hflip = false; view.vflip = false; applyView(); };
$('row-direction').onchange = e => { view.down = e.target.value === 'down'; applyView(); };

$('weights-file').onchange = async e => { await loadWeightsFile(e.target.files[0]); e.target.value = ''; };
const drop = $('file-drop');
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); loadWeightsFile(e.dataTransfer.files[0]); });
$('load-url').onclick = async () => {
  try {
    if (busy) throw Error(t('n.stopFirst'));
    const url = new URL($('weights-url').value, location.href);
    if (!['https:', 'http:'].includes(url.protocol)) throw Error(t('n.httpOnly'));
    const response = await fetch(url);
    if (!response.ok) throw Error(t('n.download', { status: response.status }));
    await weights(await response.arrayBuffer(), url.pathname.split('/').at(-1) || url.hostname);
  } catch (e) { notice(t('n.loadFail', { msg: e.message })); }
};
$('use-hce').onclick = () => { send('YXUNLOADNNUE'); weightsInfo = null; renderWeights(); notice(); };

$('command-form').onsubmit = e => {
  e.preventDefault();
  const value = $('command-input').value.trim();
  if (!value) return;
  if (/^(BEGIN|BOARD|YXGO|TURN|YXSUGGEST)\b/i.test(value)) {
    searchKind = /^YXSUGGEST\b/i.test(value) ? 'suggest' : 'move';
    searchSide = state.next; searchPly = null;
    started = performance.now(); setBusy(true);
  }
  send(value.split('\n'));
  $('command-input').value = '';
  if (!busy) status();
};
$('clear-log').onclick = () => { $('protocol-log').textContent = ''; };

// Tabs.
function selectTab(name) {
  for (const b of document.querySelectorAll('[data-tab]')) {
    const on = b.dataset.tab === name;
    b.classList.toggle('active', on); b.setAttribute('aria-selected', on);
    if (on) { const ink = $('tab-ink'); ink.style.left = b.offsetLeft + 'px'; ink.style.width = b.offsetWidth + 'px'; }
  }
  for (const p of document.querySelectorAll('[data-panel]')) p.classList.toggle('active', p.dataset.panel === name);
}
for (const b of document.querySelectorAll('[data-tab]')) b.onclick = () => selectTab(b.dataset.tab);

// Display preferences.
function bindSeg(id, key, after) {
  const seg = $(id);
  const paint = () => { for (const b of seg.querySelectorAll('button')) b.classList.toggle('on', b.dataset.value === prefs[key]); };
  for (const b of seg.querySelectorAll('button')) { b.type = 'button'; b.onclick = () => { prefs[key] = b.dataset.value; savePrefs(); paint(); after(); }; }
  paint();
  return paint;
}
function applyUi() {
  document.body.dataset.ui = prefs.ui;
  document.documentElement.style.colorScheme = prefs.ui;
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', prefs.ui === 'light' ? '#f3faf6' : '#141210');
}
$('ui-toggle').onclick = () => {
  prefs.ui = prefs.ui === 'light' ? 'dark' : 'light';
  savePrefs(); applyUi(); render();
};
const paintTheme = bindSeg('theme-seg', 'theme', () => { document.body.dataset.theme = prefs.theme; render(); });
const paintNumbers = bindSeg('numbers-seg', 'numbers', render);
for (const [id, key] of [['opt-coords', 'coords'], ['opt-hover', 'hover'], ['opt-sound', 'sound'], ['opt-anim', 'anim']]) {
  $(id).checked = prefs[key];
  $(id).onchange = e => { prefs[key] = e.target.checked; savePrefs(); document.body.classList.toggle('no-anim', !prefs.anim); render(); };
}
for (const b of $('view-seg').querySelectorAll('button')) b.onclick = () => { prefs.view = b.dataset.value; savePrefs(); useRenderer(prefs.view); };
$('reset-camera').onclick = () => renderer?.resetCamera?.();
$('lang-toggle').onclick = () => { const codes = Object.keys(LANGS); switchLang(codes[(codes.indexOf(getLang()) + 1) % codes.length]); };
for (const id of ['help-open', 'help-open-2']) $(id).onclick = () => $('help-dialog').showModal();

// Keyboard shortcuts.
document.addEventListener('keydown', e => {
  if ($('help-dialog').open) return;
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const key = e.key, click = id => { if (!$(id).disabled) $(id).click(); };
  if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === 'z') { e.preventDefault(); click('undo'); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (key === 'n' || key === 'N') click('new-game');
  else if (key === 'u' || key === 'U') click('undo');
  else if (key === 'a' || key === 'A') click('analyze');
  else if (key === 'p' || key === 'P') click('play-best');
  else if (key === 'Escape') click('stop');
  else if (key === 'ArrowLeft') { e.preventDefault(); $('nav-prev').click(); }
  else if (key === 'ArrowRight') { e.preventDefault(); $('nav-next').click(); }
  else if (key === 'Home') { e.preventDefault(); setReview(0); }
  else if (key === 'End') { e.preventDefault(); setReview(state.history.length); }
  else if (key === 'm' || key === 'M') {
    const order = ['all', 'recent', 'off'];
    prefs.numbers = order[(order.indexOf(prefs.numbers) + 1) % 3]; savePrefs(); paintNumbers(); render();
  } else if (key === '?') $('help-dialog').showModal();
});
window.addEventListener('hashchange', () => { const share = readShare(); if (share && ready && !busy) applyShare(share); });
window.addEventListener('resize', () => selectTab(document.querySelector('[data-tab].active').dataset.tab));

// ---------------------------------------------------------------- boot
document.body.dataset.theme = prefs.theme;
applyUi();
document.body.classList.toggle('no-anim', !prefs.anim);
paintTheme();
$('row-direction').value = view.down ? 'down' : 'up';
buildView();
applyLanguage();
resetLive();
drawChart();
selectTab('game');
useRenderer(prefs.view);
worker.postMessage({ type: 'init', wasm: bundle?.wasm });
