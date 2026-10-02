"""HCE -> self-play -> NNUE -> paired promotion tests -> repeat."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def relay_output(stream, log, output):
    """Keep complete logs while refreshing self-play progress on terminals."""
    interactive = output.isatty()
    progress_visible = False
    try:
        for line in stream:
            log.write(line)
            log.flush()
            if interactive and line.startswith('selfplay '):
                output.write('\r' + line.rstrip('\r\n'))
                progress_visible = True
            else:
                if progress_visible:
                    output.write('\n')
                    progress_visible = False
                output.write(line)
            output.flush()
    finally:
        if progress_visible:
            output.write('\n')
            output.flush()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--resume-run', action='store_true', help='resume the same directory and configuration')
    p.add_argument('--generations', type=int, default=5)
    p.add_argument('--games', type=int, default=512)
    p.add_argument('--epochs', type=int, default=40)
    p.add_argument('--pairs', type=int, default=128)
    p.add_argument('--nodes', type=int, default=4000)
    p.add_argument('--depth', type=int, default=4)
    p.add_argument('--branch', type=int, default=12)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--size', type=int, default=15)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--promotion-score', type=float, default=0.55)
    p.add_argument('--replay-generations', type=int, default=3)
    p.add_argument('--train-device', default='cpu')
    p.add_argument('--train-batch-size', type=int, help='default: 128 on CPU, 4096 on CUDA')
    p.add_argument('--train-workers', type=int, default=4, help='CUDA data-loading workers; CPU sparse training ignores this')
    p.add_argument('--train-precision', choices=['auto', 'fp32', 'bf16', 'fp16'], default='auto')
    p.add_argument('--train-deterministic', action='store_true', help='use strict reproducibility rather than CUDA throughput optimizations')
    args = p.parse_args()
    if min(args.generations, args.games, args.epochs, args.pairs, args.nodes, args.depth, args.branch, args.threads, args.replay_generations) < 1 or not 5 <= args.size <= 20 or not 0.5 < args.promotion_score < 1:
        p.error('invalid experiment configuration')
    if args.train_workers < 0 or args.train_batch_size is not None and args.train_batch_size < 1:
        p.error('invalid training batch size or worker count')
    try:
        import torch
    except ImportError:
        p.error('Install PyTorch with uv sync --extra cpu or uv sync --extra cu128; use the same extra for uv run')
    device = torch.device(args.train_device)
    if device.type == 'cuda':
        if not torch.cuda.is_available():
            p.error('CUDA is unavailable: select the cu128 extra and check the NVIDIA driver before generating data')
        if device.index is not None and device.index >= torch.cuda.device_count():
            p.error('requested CUDA device does not exist')
    run_dir = args.run_dir.resolve()
    config = vars(args) | {'run_dir': str(run_dir)}
    config.pop('resume_run')
    config['source_sha256'] = {
        str(path.relative_to(ROOT)): digest(path)
        for base, extension in [('src', '*.rs'), ('trainer', '*.py')]
        for path in sorted((ROOT / base).rglob(extension))
    }
    if args.resume_run:
        if json.loads((run_dir / 'config.json').read_text()) != config:
            p.error('resume requires exactly the original configuration')
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(run_dir / 'config.json', config)
    subprocess.run(['cargo', 'build', '--release', '--bins'], cwd=ROOT, check=True)
    champion, checkpoint = 'hce', None
    replay, reports = [], []
    limits = ['--nodes', str(args.nodes), '--depth', str(args.depth), '--branch', str(args.branch), '--size', str(args.size), '--threads', str(args.threads)]

    def save_summary():
        atomic_json(run_dir / 'summary.json', {'external_data': False, 'external_weights': False, 'champion': champion, 'generations': reports})

    for generation in range(args.generations):
        folder = run_dir / f'generation-{generation:03d}'
        folder.mkdir(exist_ok=args.resume_run)
        data = folder / 'selfplay.jsonl'
        candidate = folder / 'candidate.nnue'
        manifest = folder / 'manifest.json'
        if args.resume_run and manifest.exists():
            report = json.loads(manifest.read_text())
            # Check every stage's outputs, including .pt checkpoints and arena
            # reports, before trusting a completed generation as a teacher.
            for marker in folder.glob('stage-*.json'):
                stage = json.loads(marker.read_text())
                for output, checksum in stage['outputs'].items():
                    if not Path(output).exists() or digest(output) != checksum:
                        raise RuntimeError(f'Completed generation {generation} stage output checksum mismatch: {output}')
            if digest(data) != report['data_sha256'] or digest(candidate) != report['candidate_sha256']:
                raise RuntimeError(f'Completed generation {generation} checksum mismatch')
            replay.append(data)
            if report['promoted']:
                champion, checkpoint = str(candidate), candidate.with_suffix('.pt')
                if not checkpoint.exists():
                    raise RuntimeError('Missing champion training checkpoint')
            reports.append(report)
            save_summary()
            print(f'generation {generation}: already complete, promoted={report["promoted"]}', flush=True)
            continue
        selfplay_seed = args.seed + generation * 100003
        arena_seed = args.seed + 1_000_000_007 + generation * 100019
        commands = []

        def execute(command, name, output_paths):
            commands.append(command)
            marker = folder / f'stage-{name}.json'
            if args.resume_run and marker.exists():
                done = json.loads(marker.read_text())
                if done['command'] != command:
                    raise RuntimeError(f'{name}: command changed since checkpoint')
                if all(path.exists() and digest(path) == done['outputs'].get(str(path)) for path in output_paths):
                    print(f'{name}: verified and reused completed stage', flush=True)
                    return
                raise RuntimeError(f'{name}: checkpoint outputs missing or modified')
            with (folder / f'{name}.log').open('w') as log:
                proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                try:
                    relay_output(proc.stdout, log, sys.stdout)
                    if proc.wait() != 0:
                        raise RuntimeError(f'{name} failed; see {folder / (name + ".log")}')
                except BaseException:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                    raise
            atomic_json(marker, {'command': command, 'outputs': {str(path): digest(path) for path in output_paths}})

        execute([str(ROOT / 'target/release/selfplay'), '--games', str(args.games), '--weights', champion,
                 '--seed', str(selfplay_seed), '--output', str(data), *limits], 'selfplay', [data])
        replay.append(data)
        command = [sys.executable, '-m', 'trainer.train', '--data', *map(str, replay[-args.replay_generations:]),
                   '--output', str(candidate), '--epochs', str(args.epochs), '--seed', str(args.seed + generation),
                   '--split-seed', str(args.seed), '--device', args.train_device, '--threads', str(min(args.threads, 4)),
                   '--workers', str(args.train_workers), '--precision', args.train_precision]
        if args.train_batch_size is not None: command += ['--batch-size', str(args.train_batch_size)]
        if args.train_deterministic: command += ['--deterministic']
        if checkpoint: command += ['--resume', str(checkpoint)]
        execute(command, 'train', [candidate, candidate.with_suffix('.pt'), candidate.with_suffix('.training.json')])
        checks = []
        for i, opponent in enumerate(dict.fromkeys([champion, 'hce'])):
            result_path = folder / f'arena-{i}.json'
            execute([str(ROOT / 'target/release/arena'), '--candidate', str(candidate), '--baseline', opponent,
                     '--pairs', str(args.pairs), '--seed', str(arena_seed), '--output', str(result_path), *limits], f'arena-{i}', [result_path])
            result = json.loads(result_path.read_text())
            passed = (result['complete_pairs'] >= 32 and result['truncated'] == 0
                      and result['paired_mean'] >= args.promotion_score and result['paired_ci95'][0] > 0.5)
            checks.append({'opponent': opponent, 'report': str(result_path), 'passed': passed,
                           'score': result['score'], 'paired_ci95': result['paired_ci95']})
        promoted = all(c['passed'] for c in checks)
        teacher = champion
        if promoted:
            champion, checkpoint = str(candidate), candidate.with_suffix('.pt')
            shutil.copyfile(candidate, run_dir / 'champion.nnue')
            shutil.copyfile(checkpoint, run_dir / 'champion.pt')
        report = {'generation': generation, 'teacher': teacher, 'candidate': str(candidate),
                  'data_sha256': digest(data), 'candidate_sha256': digest(candidate),
                  'promoted': promoted, 'checks': checks, 'commands': commands}
        atomic_json(manifest, report)
        reports.append(report)
        save_summary()
        print(f'generation {generation}: promoted={promoted}, champion={champion}', flush=True)
    if checkpoint:
        shutil.copyfile(champion, run_dir / 'champion.nnue')
        shutil.copyfile(checkpoint, run_dir / 'champion.pt')
    print(f'Experiment saved to {run_dir}. A rejected candidate never becomes the next teacher.')


if __name__ == '__main__':
    main()
