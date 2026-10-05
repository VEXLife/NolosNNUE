"""Package the HCE bootstrap without pretrained weights or old datasets."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/gomoku-hce-evolution.zip')
    args = parser.parse_args()
    names = ['Cargo.toml', 'Cargo.lock', 'pyproject.toml', 'uv.lock', 'LICENSE',
             'AGENTS.md', 'README.md', 'README.zh-CN.md',
             'scripts/train_hce.sh', 'scripts/resume_hce.py', 'scripts/resume_engine.py', 'scripts/package_hce.py', 'scripts/build-web.sh',
             'scripts/check_protocol.py', 'scripts/check_wasm.mjs', 'scripts/check_network.py',
             'scripts/check_threat_regression.py', 'scripts/match_external.py']
    files = {ROOT / name for name in names}
    for directory, pattern in [('src', '*.rs'), ('trainer', '*.py'), ('tests', '*.py'),
                               ('tests', '*.rs'), ('docs', '*.md'), ('web', '*')]:
        files.update(p for p in (ROOT / directory).rglob(pattern) if p.is_file())
    files = sorted(files)
    checksums = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.mkdir('gomoku-next/')
        for path in files:
            archive.write(path, 'gomoku-next/' + str(path.relative_to(ROOT)))
        archive.writestr('gomoku-next/upload-sha256.json', json.dumps(checksums, indent=2) + '\n')
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.zip.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(f'{args.output.resolve()} ({len(files)} files, no weights or datasets)')


if __name__ == '__main__':
    main()
