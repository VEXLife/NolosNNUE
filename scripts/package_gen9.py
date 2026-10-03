"""Bundle current search trial code and the matching gen9 legacy model pair."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import tarfile
from trainer.bootstrap import initial_model

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/gomoku-search-gen9.tgz')
    args = parser.parse_args()
    initial_model(ROOT / 'artifacts/cloud-gen9.nnue')
    files = [ROOT / name for name in (
        'Cargo.toml', 'Cargo.lock', 'pyproject.toml', 'uv.lock', 'LICENSE',
        'AGENTS.md', 'README.md', 'README.zh-CN.md', 'docs/protocol.md',
        'artifacts/cloud-gen9.nnue', 'artifacts/cloud-gen9.pt',
        'docs/training.md', 'docs/network.md', 'docs/history.md',
        'artifacts/search-vcf-fixtures.json')]
    files.extend(path for path in sorted((ROOT / 'scripts').glob('*')) if path.is_file() and path.suffix in ('.py', '.sh', '.mjs'))
    for directory, pattern in [('src', '*.rs'), ('trainer', '*.py'),
                               ('tests', '*.py'), ('tests', '*.rs')]:
        files.extend(sorted((ROOT / directory).rglob(pattern)))
    files.extend(path for path in sorted((ROOT / 'web').glob('*')) if path.is_file())
    files.extend(sorted((ROOT / 'docs').glob('*.md')))
    files = sorted(set(files))
    checksums = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in files}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz') as archive:
        for path in files:
            archive.add(path, arcname='gomoku-next/' + str(path.relative_to(ROOT)))
        payload = (json.dumps(checksums, indent=2) + '\n').encode()
        info = tarfile.TarInfo('gomoku-next/upload-sha256.json')
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + '.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(args.output.resolve())
    print(f'{len(files)} files; includes current search trial and matching gen9 NNUE/checkpoint')


if __name__ == '__main__':
    main()
