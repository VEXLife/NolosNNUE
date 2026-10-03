"""Generate deeper-search data and test conservative legacy updates with independent verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def passes(result):
    return (result['complete_pairs'] >= 32 and result['truncated'] == 0
            and result['paired_mean'] >= .52 and result['paired_ci95'][0] > .5)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--threads', type=int, default=6)
    p.add_argument('--device', default='cuda')
    p.add_argument('--epochs', type=int, default=10)
    p.add_argument('--screen-pairs', type=int, default=128)
    p.add_argument('--verify-pairs', type=int, default=512)
    p.add_argument('--nodes', type=int, default=50000)
    args = p.parse_args()
    if min(args.threads, args.epochs, args.nodes) < 1 or min(args.screen_pairs, args.verify_pairs) < 32:
        p.error('positive limits and at least 32 opening pairs required')
    root, source, output = args.root.resolve(), args.source_run.resolve(), args.output.resolve()
    sys.path.insert(0, str(root))
    champion = root / 'artifacts/cloud-gen9.nnue'
    config = json.loads((source / 'config.json').read_text())
    data = []
    for i in range(2):
        folder = source / f'generation-{i:03d}'
        manifest = json.loads((folder / 'manifest.json').read_text())
        path = folder / 'selfplay.jsonl'
        if sha(path) != manifest['data_sha256']:
            raise ValueError(f'input data checksum mismatch: {path}')
        data.append(path)
    learner = source / 'generation-001/candidate.pt'
    marker = json.loads((source / 'generation-001/stage-train.json').read_text())
    expected = marker['outputs'][str(Path(config['run_dir']) / 'generation-001/candidate.pt')]
    if sha(learner) != expected or sha(champion) != config['initial_model_sha256']['nnue']:
        raise ValueError('input teacher or learner checksum mismatch')
    from trainer.bootstrap import initial_model
    initial_model(champion)
    output.mkdir(parents=True, exist_ok=False)
    target = Path(os.environ.get('CARGO_TARGET_DIR', str(output / 'target'))).resolve()
    subprocess.run(['cargo', 'build', '--release', '--bins', '--target-dir', str(target)], cwd=root, check=True)
    arena = target / 'release/arena'
    report = {'schema': 1, 'purpose': 'candidate selection followed by independent verification',
              'source_run': str(source), 'teacher_sha256': sha(champion),
              'data': {str(x): sha(x) for x in data}, 'configuration': vars(args) | {'root': str(root), 'source_run': str(source), 'output': str(output)},
              'trials': [], 'promoted': False}
    report['configuration'] = {k: str(v) if isinstance(v, Path) else v for k, v in report['configuration'].items()}
    summary = output / 'summary.json'

    def execute(command, folder, name):
        started = time.monotonic()
        print(json.dumps({'stage': name, 'folder': str(folder), 'command': command}), flush=True)
        with (folder / f'{name}.log').open('w') as log:
            proc = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for line in proc.stdout:
                    log.write(line)
                    log.flush()
                    # Arena emits an enormous per-pair JSON report; retain it in the log.
                    if not ('"results":' in line):
                        print(line.rstrip(), flush=True)
                if proc.wait():
                    raise RuntimeError(f'{name} failed; see {folder}')
            except BaseException:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise
        return time.monotonic() - started

    def match(candidate, folder, name, opponent, pairs, seed):
        path = folder / f'{name}.json'
        seconds = execute([str(arena), '--candidate', str(candidate), '--baseline', str(opponent),
                           '--pairs', str(pairs), '--seed', str(seed), '--output', str(path),
                           '--nodes', str(args.nodes), '--depth', '64', '--branch', '16',
                           '--size', '15', '--threads', str(args.threads)], folder, name)
        result = json.loads(path.read_text())
        value = {k: v for k, v in result.items() if k != 'results'}
        value.update(report=str(path), seconds=seconds, passed=passes(result))
        return value

    fresh = output / 'deep-selfplay.jsonl'
    execute([str(target / 'release/selfplay'), '--weights', str(champion),
             '--games', '512', '--nodes', '800000', '--depth', '64', '--branch', '16',
             '--size', '15', '--threads', str(args.threads), '--seed', '1030261203',
             '--exploration', '.15', '--output', str(fresh)], output, 'deep-selfplay')
    data = [fresh]
    report['fresh_data'] = {'path': str(fresh), 'sha256': sha(fresh),
                            'games': 512, 'nodes': 800000}
    save(summary, report)
    for name, architecture, resume, outcome, policy in [
        ('deep-search', 'legacy', champion.with_suffix('.pt'), 0, 0),
        ('deep-mixed', 'legacy', champion.with_suffix('.pt'), .3, 0),
    ]:
        folder = output / name
        folder.mkdir()
        candidate = folder / 'candidate.nnue'
        command = [sys.executable, '-m', 'trainer.train', '--data', *map(str, data),
                   '--output', str(candidate), '--resume', str(resume), '--architecture', architecture,
                   '--epochs', str(args.epochs), '--lr', '.00003', '--outcome-weight', str(outcome),
                   '--policy-weight', str(policy), '--device', args.device, '--precision', 'fp32',
                   '--threads', str(min(args.threads, 4)), '--workers', '2',
                   '--batch-size', '256',
                   '--seed', '930261203', '--split-seed', str(config['seed'])]
        seconds = execute(command, folder, 'train')
        initial_model(candidate)
        trial = {'name': name, 'candidate': str(candidate), 'sha256': sha(candidate),
                 'train_seconds': seconds, 'train_command': command, 'checks': []}
        trial['screen'] = match(candidate, folder, 'screen-gen9', champion, args.screen_pairs, 1930261203)
        report['trials'].append(trial)
        save(summary, report)

    # Screening is selection data, never promotion evidence. Fresh seeds below.
    eligible = sorted((t for t in report['trials'] if t['screen']['paired_mean'] >= .5
                       and t['screen']['truncated'] == 0), key=lambda t: t['screen']['paired_mean'], reverse=True)
    for trial in eligible:
        candidate = Path(trial['candidate'])
        folder = candidate.parent
        approved = True
        for phase, seed in [('verify', 2930261219), ('confirm', 3930261241)]:
            for opponent_name, opponent in [('gen9', champion), ('hce', 'hce')]:
                result = match(candidate, folder, f'{phase}-{opponent_name}', opponent, args.verify_pairs, seed)
                trial['checks'].append(result | {'phase': phase, 'opponent': str(opponent)})
                save(summary, report)
                if not result['passed']:
                    approved = False
                    break
            if not approved:
                break
        if approved:
            report.update(promoted=True, champion=str(candidate), champion_sha256=sha(candidate))
            shutil.copyfile(candidate, output / 'champion.nnue')
            shutil.copyfile(candidate.with_suffix('.pt'), output / 'champion.pt')
            save(summary, report)
            break
    save(summary, report)
    print(json.dumps({'completed': str(summary), 'promoted': report['promoted']}), flush=True)


if __name__ == '__main__':
    main()
