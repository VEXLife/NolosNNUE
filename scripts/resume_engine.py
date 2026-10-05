"""Resume an existing bootstrap run after an explicitly accepted Rust engine update."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for base, pattern in [('src', '*.rs'), ('trainer', '*.py'), ('scripts', '*.sh')]
            for path in sorted((root / base).rglob(pattern))}


def prepare(run, accept_update=False, root=ROOT, python=sys.executable, threads=None):
    path = run / 'config.json'
    saved = json.loads(path.read_text())
    if Path(saved['run_dir']).resolve() != run.resolve():
        raise ValueError('run-dir must retain the original absolute path from config.json')
    current = source_hashes(root)
    before = saved['source_sha256']
    changed = sorted(k for k in before.keys() | current.keys() if before.get(k) != current.get(k))
    incompatible = [k for k in changed if not (k.startswith('src/') and k.endswith('.rs'))]
    if incompatible:
        raise ValueError('non-engine source changes are not accepted: ' + ', '.join(incompatible))
    if changed and not accept_update:
        raise ValueError('Rust engine changed; pass --accept-engine-update to record and accept it')
    command = [python, '-m', 'trainer.bootstrap', '--resume-run']
    if threads is not None:
        if not 1 <= threads <= 256:
            raise ValueError('threads must be between 1 and 256')
        command += ['--worker-threads', str(threads)]
    for key, value in saved.items():
        if key.endswith('sha256') or value is None:
            continue
        flag = '--' + key.replace('_', '-')
        if isinstance(value, bool):
            if value:
                command.append(flag)
        else:
            command.extend([flag, str(value)])
    updated = saved | {'source_sha256': current}
    return saved, updated, changed, command


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--accept-engine-update', action='store_true')
    p.add_argument('--threads', type=int, help='execution workers only; defaults to saved config')
    p.add_argument('--dry-run', action='store_true', help='validate and show command without changing or running anything')
    args = p.parse_args()
    try:
        saved, updated, changed, command = prepare(args.run_dir.resolve(), args.accept_engine_update,
                                                   threads=args.threads)
    except (ValueError, OSError, KeyError) as e:
        p.error(str(e))
    print(json.dumps({'changed_engine_sources': changed, 'command': command}, indent=2), flush=True)
    if args.dry_run:
        return
    if changed:
        audit_dir = args.run_dir / 'engine-updates'
        audit_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        audit = {'utc': stamp, 'before_config': saved, 'after_config': updated,
                 'changed_sources': changed, 'command': command,
                 'precision': 'fp32; selfplay/arena keep their default evaluator'}
        atomic_json(audit_dir / f'{stamp}.json', audit)
        atomic_json(args.run_dir / 'config.json', updated)
        print(f'Accepted Rust engine update; original config recorded in {audit_dir}', flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
