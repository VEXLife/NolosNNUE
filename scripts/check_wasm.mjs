// Verify the real WASM ABI and same protocol implementation, without a browser.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
const path = process.argv[2] || 'web/nolos_nnue.wasm';
const outputs = [], encoder = new TextEncoder(), decoder = new TextDecoder();
let wasm;
const { instance } = await WebAssembly.instantiate(readFileSync(path), { host: {
  now_ms: () => performance.now(),
  output: (p, n) => outputs.push(decoder.decode(new Uint8Array(wasm.memory.buffer, p, n))),
}});
wasm = instance.exports;
function bytes(b, fn) {
  const p = wasm.engine_alloc(b.length);
  try { new Uint8Array(wasm.memory.buffer, p, b.length).set(b); return fn(p, b.length); }
  finally { wasm.engine_free(p, b.length); }
}
function command(s) { bytes(encoder.encode(s), (p,n) => wasm.engine_command(p,n)); }
function take() { return outputs.splice(0); }
function drain() { let i=0; while(wasm.engine_tick(32)) { assert(++i<100000); } }
wasm.engine_init();
command('start 15\r\n'); assert.deepEqual(take(), ['OK']);
for (const s of ['yxboard','7,7,1','8,7,2','done']) command(s);
assert.deepEqual(take(), []);
command('YXSTATUS');
assert.deepEqual(JSON.parse(take()[0].slice(15)).history, [[112,1],[113,2]]);
for(const s of ['INFO max_depth 2','INFO max_node 512','INFO timeout_turn 60000','YXSUGGEST']) command(s);
drain(); assert(take().some(s=>s.startsWith('SUGGEST ')));
command('YXSTATUS'); assert.equal(JSON.parse(take()[0].slice(15)).history.length, 2);
for(const s of ['INFO max_depth 64','INFO max_node 100000000','YXGO']) command(s);
wasm.engine_tick(16); take(); command('YXSTOP');
assert.equal(take().filter(s=>/^\d+,\d+$/.test(s)).length, 1);
command('YXSTATUS'); assert.equal(JSON.parse(take()[0].slice(15)).history.length, 3);
for(const s of ['START 15','INFO rule 2','YXBOARD','6,7,1','0,0,2','8,7,1','1,0,2','7,6,1','2,0,2','7,8,1','3,0,2','DONE','YXSHOWFORBID']) command(s);
assert(take().some(s=>s.startsWith('FORBID ')&&s.includes('0707')&&s.endsWith('.')));
command('PLAY 7,7'); assert(take()[0].startsWith('ERROR'));
if(process.argv[3]) {
  const weights=readFileSync(process.argv[3]);
  assert.equal(bytes(weights,(p,n)=>wasm.engine_load_weights(p,n)),1); assert.deepEqual(take(),[]);
  weights[weights.length-1]^=1;
  assert.equal(bytes(weights,(p,n)=>wasm.engine_load_weights(p,n)),0); assert(take()[0].includes('checksum'));
  command('YXEVAL'); assert(take()[0].startsWith('MESSAGE EVAL '));
}
command('END'); command('ABOUT'); assert.deepEqual(take(), []);
console.log('WASM ABI, Yixin state, suggestion, interruption, forbidden moves and weights: PASS');
