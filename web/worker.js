// Transport only. Yixin parsing, search, evaluation and rules live in Rust.
let wasm, memory, pumping = false, pumpTimer = null, requestId = 0, lastBusy = null, lastBusyRequest = -1;
const decoder = new TextDecoder(), encoder = new TextEncoder();
function output(ptr, len) {
  postMessage({ type: 'line', line: decoder.decode(new Uint8Array(memory.buffer, ptr, len)) });
}
function withBytes(bytes, fn) {
  const ptr = wasm.engine_alloc(bytes.length);
  try { new Uint8Array(memory.buffer, ptr, bytes.length).set(bytes); return fn(ptr, bytes.length); }
  finally { wasm.engine_free(ptr, bytes.length); }
}
function pump() {
  pumpTimer = null;
  if (!wasm) return;
  try {
    // Short work slices let queued YXSTOP messages run without shared memory,
    // COOP/COEP headers, or browser-specific thread support.
    const deadline = performance.now() + 8;
    let busy = false;
    do { busy = !!wasm.engine_tick(16); } while (busy && performance.now() < deadline);
    pumping = busy;
    if (busy !== lastBusy || requestId !== lastBusyRequest) {
      postMessage({ type: 'busy', busy, requestId });
      lastBusy = busy; lastBusyRequest = requestId;
    }
    if (busy) pumpTimer = setTimeout(pump, 0);
    else postMessage({ type: 'idle', requestId });
  } catch (e) { pumping = false; postMessage({ type: 'error', error: String(e) }); }
}
onmessage = async ({ data }) => {
  try {
    if (data.type === 'init') {
      const response = await fetch(new URL('nolos_nnue.wasm', import.meta.url));
      if (!response.ok) throw Error(`WASM download failed: ${response.status}`);
      const instance = await WebAssembly.instantiate(await response.arrayBuffer(), { host: { output, now_ms: () => performance.now() } });
      wasm = instance.instance.exports; memory = wasm.memory;
      wasm.engine_init(); postMessage({ type: 'ready' });
    } else if (data.type === 'commands') {
      if (!wasm) throw Error('Engine is not ready');
      requestId = data.requestId;
      for (const line of data.lines) withBytes(encoder.encode(line), (ptr, len) => wasm.engine_command(ptr, len));
      if (pumpTimer !== null) clearTimeout(pumpTimer);
      pump();
    } else if (data.type === 'weights') {
      if (!wasm) throw Error('Engine is not ready');
      if (pumping) throw Error('Stop the search before loading weights');
      const ok = withBytes(new Uint8Array(data.bytes), (ptr, len) => wasm.engine_load_weights(ptr, len));
      postMessage({ type: 'weights', ok: !!ok, name: data.name, hash: data.hash });
    }
  } catch (e) { postMessage({ type: 'error', error: String(e) }); }
};
