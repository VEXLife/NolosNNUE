"""Restore an HCE run and continue with tactical gates removed."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-run', type=Path, help='mounted previous output; copied only if run-dir does not exist')
    parser.add_argument('--accept-first-generation', action='store_true', help='promote generation-000 using its completed arena')
    args = parser.parse_args()
    worker_threads = None
    if 'THREADS' in os.environ:
        try:
            worker_threads = int(os.environ['THREADS'])
        except ValueError:
            parser.error('THREADS must be an integer between 1 and 256')
        if not 1 <= worker_threads <= 256:
            parser.error('THREADS must be between 1 and 256')
    run = args.run_dir.resolve()
    if not run.exists():
        source = args.source_run
        if source is None:
            matches = []
            for base in (Path('/gemini/pretrain'), Path('/gemini/pretrain2')):
                if not base.exists(): continue
                for path in base.rglob('config.json'):
                    saved = json.loads(path.read_text())
                    if saved.get('run_dir') == str(run): matches.append(path.parent)
            if len(matches) != 1:
                parser.error('mount the previous output, or pass --source-run pointing to its config.json directory')
            source = matches[0]
        config = json.loads((source / 'config.json').read_text())
        if Path(config['run_dir']).resolve() != run:
            parser.error('run-dir must retain the original path stored in config.json')
        shutil.copytree(source, run)
        print(f'Restored previous output from {source} to {run}', flush=True)
    config = json.loads((run / 'config.json').read_text())
    config.update(pairs=128, confirm_pairs=0, arena_time_ms=0, promotion_score=.52, promotion_policy='score', tactical_regressions=False)
    if args.accept_first_generation: config['accept_first_generation'] = True
    command = [sys.executable, '-m', 'trainer.bootstrap', '--resume-run', '--migrate-score-policy']
    if worker_threads is not None:
        command += ['--worker-threads', str(worker_threads)]
    for key, value in config.items():
        if key.endswith('sha256') or key == 'tactical_regressions' or value is None:
            continue
        flag = '--' + key.replace('_', '-')
        if isinstance(value, bool):
            if value: command.append(flag)
        else:
            command.extend([flag, str(value)])
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
