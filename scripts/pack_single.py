#!/usr/bin/env python3
"""Pack web/ + a .nnue network + the WASM engine into one self-contained HTML file.

Every asset is gzip+base64 encoded; a tiny loader decodes them with DecompressionStream,
turns the JS modules into blob URLs wired together by an import map, and starts the app.
Usage: pack_single.py [--model models/x.nnue] [--out dist/nolos.html]
"""
import argparse, base64, gzip, json, re, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument('--model', default=str(root / 'models/hce-local-003.nnue'))
ap.add_argument('--out', default=str(root / 'dist/nolos.html'))
args = ap.parse_args()
web = root / 'web'

def enc(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data, 9, mtime=0)).decode()

# Rewrite relative imports to bare names the import map resolves to blob URLs.
def bare(src: str) -> str:
    return re.sub(r"""((?:from|import)\s*\(?\s*)(['"])\./(?:vendor/three/)?([\w.]+?)(?:\.js)\2""",
                  lambda m: f"{m[1]}{m[2]}nolos:{m[3]}{m[2]}", src)

mods = {'i18n': 'i18n.js', 'board2d': 'board2d.js', 'board3d': 'board3d.js',
        'three.module': 'vendor/three/three.module.js', 'three.core': 'vendor/three/three.core.js',
        'OrbitControls': 'vendor/three/OrbitControls.js', 'RoomEnvironment': 'vendor/three/RoomEnvironment.js',
        'RoundedBoxGeometry': 'vendor/three/RoundedBoxGeometry.js'}
assets = {f'nolos:{k}': enc(bare((web / v).read_text('utf8')).encode()) for k, v in mods.items()}
assets['app'] = enc(bare((web / 'app.js').read_text('utf8')).encode())
assets['worker'] = enc((web / 'worker.js').read_bytes())
assets['wasm'] = enc((web / 'nolos_nnue.wasm').read_bytes())
model = Path(args.model)
assets['nnue'] = enc(model.read_bytes())

html = (web / 'index.html').read_text('utf8')
css = (web / 'style.css').read_text('utf8')
icon = 'data:image/svg+xml;base64,' + base64.b64encode((web / 'icon.svg').read_bytes()).decode()
html = html.replace('<link rel="stylesheet" href="style.css">', f'<style>\n{css}\n</style>')
html = html.replace('href="icon.svg"', f'href="{icon}"').replace('src="icon.svg"', f'src="{icon}"')
loader = """<script>
(async () => {
  const A = %s;
  const unz = async b64 => new Uint8Array(await new Response(new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))])
    .stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
  const url = (bytes, type = 'text/javascript') => URL.createObjectURL(new Blob([bytes], { type }));
  const raw = {};
  await Promise.all(Object.entries(A).map(async ([k, v]) => { raw[k] = await unz(v); }));
  const imports = {};
  for (const k of Object.keys(raw)) if (k.startsWith('nolos:')) imports[k] = url(raw[k]);
  const map = document.createElement('script');
  map.type = 'importmap'; map.textContent = JSON.stringify({ imports });
  document.head.append(map);
  globalThis.NOLOS_BUNDLE = { worker: url(raw.worker), wasm: raw.wasm, nnue: raw.nnue, nnueName: %s };
  const app = document.createElement('script');
  app.type = 'module'; app.src = url(raw.app);
  document.body.append(app);
})();
</script>""" % (json.dumps(assets), json.dumps(model.name))
html = html.replace('<script type="module" src="app.js"></script>', loader)
out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, 'utf8')
print(f'Single-file site: {out} ({out.stat().st_size / 1e6:.2f} MB, model {model.name})')
