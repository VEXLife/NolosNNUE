"""Fresh search labels, grouped mate thinning, gen9 fine tuning and independent gates."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from scripts.deep_gen9 import sha, save, passes
from scripts.match_external import Peer

ROOT = Path(__file__).resolve().parents[1]
MATE = 29500


REGRESSIONS = [
    ('h8g8i7g9g7i9h7f7h9h6j7k7i8g10j9', 'black'),
    ('h8i7g7i9h6f8i8g6j4i5h9h7i10j8g10', 'black'),
    ('h8g7i7g9h6j8g8h7j6i6k7k5l8i5k9j5l5k4', 'white'),
]


def heldout_boards():
    boards = set()
    for sequence, _ in REGRESSIONS:
        tokens = re.findall(r'[a-o](?:1[0-5]|[1-9])', sequence)
        for mirror in [False, True]:
            for turns in range(4):
                cells = ['0'] * 225
                for i, token in enumerate(tokens):
                    x, y = ord(token[0]) - ord('a'), int(token[1:]) - 1
                    if mirror: x = 14 - x
                    for _ in range(turns): x, y = 14 - y, x
                    cells[y * 15 + x] = str(i % 2 + 1)
                boards.add(''.join(cells))
    return boards


def thin_samples(samples):
    """Keep all ordinary positions and at most the first two of each mate run.

    Input is ordered by increasing occupancy within each immutable game group.
    Mate signs alternate by side, so runs are tracked by absolute winning color.
    """
    groups = defaultdict(list)
    for sample in samples:
        groups[(sample['seed'], sample['game'], sample['size'], sample['rule'])].append(sample)
    kept = []
    for _, game in sorted(groups.items()):
        run_color, count = None, 0
        for sample in sorted(game, key=lambda s: len(s['board']) - s['board'].count('0')):
            color = (sample['side'] if sample['score'] > 0 else 3 - sample['side']) if abs(sample['score']) >= MATE else None
            if color is None:
                run_color, count = None, 0
                kept.append(sample)
            else:
                count = count + 1 if color == run_color else 1
                run_color = color
                if count <= 2:
                    kept.append(sample)
    return kept


def read_samples(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def write_samples(path, samples):
    with path.open('w') as stream:
        for sample in samples:
            stream.write(json.dumps(sample, separators=(',', ':')) + '\n')


def board_rows(sample):
    # The protocol infers absolute colors from chronological relative-color rows.
    # Arbitrary cell order can accidentally alternate and invert the colors.
    black = [p for p, c in enumerate(sample['board']) if c == '1']
    white = [p for p, c in enumerate(sample['board']) if c == '2']
    if len(black) not in (len(white), len(white) + 1) or sample['side'] != (1 if len(black) == len(white) else 2):
        raise ValueError('invalid freestyle color counts/side')
    order = []
    for i, position in enumerate(black):
        order.append((position, 1))
        if i < len(white):
            order.append((white[i], 2))
    return [f'{p % 15},{p // 15},{1 if color == sample["side"] else 2}' for p, color in order]


def reanalyze(engine, weights, samples, nodes, threads):
    # One cold engine per worker; fixed TT size and default branch=16 match selfplay.
    def worker(chunk):
        peer = Peer([str(engine), '--weights', str(weights)])
        changed = 0
        try:
            peer.send('START 15')
            peer.receive(lambda line: line == 'OK', 10)
            for sample in chunk:
                peer.send('RESTART')
                peer.receive(lambda line: line == 'OK', 10)
                peer.send('INFO rule 0', 'INFO hash_size 16384', 'INFO max_depth 64',
                          f'INFO max_node {nodes}',
                          'INFO timeout_turn 600000', 'INFO show_detail 2', 'YXBOARD',
                          *board_rows(sample),
                          'DONE', 'YXSTATUS')
                status_lines = peer.receive(lambda line: line.startswith('MESSAGE STATUS '), 10)
                status = json.loads(status_lines[-1].removeprefix('MESSAGE STATUS '))
                if status['board'] != sample['board'] or status['next'] != sample['side']:
                    raise ValueError('reanalysis board/color roundtrip mismatch')
                peer.send('YXSUGGEST')
                lines = peer.receive(lambda line: line.startswith('SUGGEST '), 660)
                fields = {parts[1]: parts[2] for line in lines if line.startswith('INFO ')
                          and len(parts := line.split(maxsplit=2)) == 3}
                value = fields['EVAL']
                score = ((1 if value[0] == '+' else -1) * (30000 - int(value[2:]))) if re.fullmatch(r'[+-]M\d+', value) else int(value)
                x, y = map(int, lines[-1].split()[1].split(','))
                vcf = [int(m.group(1)) for line in lines if (m := re.search(r'VCF proof (\d+) plies', line))]
                depth = int(fields['DEPTH'])
                if depth <= 0 and not vcf:
                    raise ValueError('reanalysis did not produce a completed label')
                changed += (sample['score'] > 0) != (score > 0)
                sample.update(previous_score=sample['score'], score=score, depth=depth,
                              nodes=int(fields['NODES']), best_move=y * 15 + x,
                              vcf_depth=vcf[-1] if vcf else 0, reanalyzed=True)
        finally:
            peer.close()
        return changed
    with ThreadPoolExecutor(max_workers=threads) as pool:
        return sum(pool.map(worker, [samples[i::threads] for i in range(threads)]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--threads', type=int, default=6)
    p.add_argument('--device', default='cuda')
    p.add_argument('--games', type=int, default=256)
    p.add_argument('--selfplay-nodes', type=int, default=200000)
    p.add_argument('--reanalyze-nodes', type=int, default=800000)
    p.add_argument('--reanalyze-limit', type=int, default=256)
    p.add_argument('--epochs', type=int, default=6)
    p.add_argument('--screen-pairs', type=int, default=128)
    p.add_argument('--verify-pairs', type=int, default=512)
    p.add_argument('--arena-nodes', type=int, default=50000)
    p.add_argument('--arena-time-ms', type=int, default=100)
    p.add_argument('--seed', type=int, default=1030262001)
    p.add_argument('--prepare-only', action='store_true', help='build and prepare data without training/arena')
    p.add_argument('--replay', type=Path, nargs='*', default=[], help='optional immutable previous cohorts; mate thinning applied')
    args = p.parse_args()
    if min(args.threads, args.epochs, args.selfplay_nodes, args.reanalyze_nodes, args.arena_nodes, args.arena_time_ms) < 1 or args.games < 4 or min(args.screen_pairs, args.verify_pairs) < 32 or args.reanalyze_limit < 0 or args.threads > 256 or not 0 <= args.seed < 2**64 - 310000:
        p.error('positive limits, at least 4 games and 32 opening pairs required')
    from trainer.bootstrap import initial_model
    champion = ROOT / 'artifacts/cloud-gen9.nnue'
    initial_model(champion)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    target = Path(os.environ.get('CARGO_TARGET_DIR', str(output / 'target'))).resolve()
    report = {'schema': 1, 'promoted': False, 'configuration': {k: str(v) if isinstance(v, Path) else [str(x) for x in v] if k == 'replay' else v for k, v in vars(args).items()},
              'teacher_sha256': sha(champion), 'checkpoint_sha256': sha(champion.with_suffix('.pt')), 'trials': []}
    summary = output / 'summary.json'
    save(summary, report)

    def execute(command, folder, name):
        print(json.dumps({'stage': name, 'command': command}), flush=True)
        started = time.monotonic()
        with (folder / f'{name}.log').open('w') as log:
            proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for line in proc.stdout:
                    log.write(line); log.flush()
                    if '"results":' not in line:
                        print(line.rstrip(), flush=True)
                if proc.wait():
                    raise RuntimeError(f'{name} failed: {folder}')
            except BaseException:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
                raise
        return time.monotonic() - started

    execute(['cargo', 'build', '--release', '--bins', '--target-dir', str(target)], output, 'build')
    engine, arena = target / 'release/nolos-nnue', target / 'release/arena'
    report['engine_sha256'] = sha(engine)
    report['arena_sha256'] = sha(arena)
    report['source_sha256'] = {str(x.relative_to(ROOT)): sha(x) for folder, pattern in [('src', '*.rs'), ('trainer', '*.py'), ('scripts', '*.py'), ('scripts', '*.sh')] for x in sorted((ROOT / folder).rglob(pattern))}
    raw = output / 'raw.jsonl'
    seconds = execute([str(target / 'release/selfplay'), '--weights', str(champion), '--games', str(args.games),
                       '--nodes', str(args.selfplay_nodes), '--depth', '64', '--branch', '16', '--size', '15',
                       '--threads', str(args.threads), '--seed', str(args.seed), '--exploration', '.3', '--output', str(raw)], output, 'selfplay')
    samples = read_samples(raw)
    ordinary = [s for s in samples if abs(s['score']) < MATE]
    # Budget-limited ordinary positions first; round-robin games avoids one game's tail dominating.
    by_game = defaultdict(list)
    for s in sorted(ordinary, key=lambda s: (-s['nodes'], s['game'], s['board'])):
        by_game[s['game']].append(s)
    selected = []
    while by_game and len(selected) < args.reanalyze_limit:
        for game in list(sorted(by_game)):
            selected.append(by_game[game].pop(0))
            if not by_game[game]:
                del by_game[game]
            if len(selected) >= args.reanalyze_limit:
                break
    started = time.monotonic()
    changed = reanalyze(engine, champion, selected, args.reanalyze_nodes, args.threads) if selected else 0
    kept = thin_samples(samples)
    for replay in args.replay:
        kept.extend(thin_samples(read_samples(replay)))
    heldout = heldout_boards()
    excluded = {(s['seed'], s['game'], s['size'], s['rule']) for s in kept if s['board'] in heldout}
    kept = [s for s in kept if (s['seed'], s['game'], s['size'], s['rule']) not in excluded]
    data = output / 'training.jsonl' 
    write_samples(data, kept)
    report['data'] = {'raw_sha256': sha(raw), 'training_sha256': sha(data), 'raw_positions': len(samples),
                      'kept_positions': len(kept), 'excluded_regression_games': len(excluded), 'ordinary_positions': sum(abs(s['score']) < MATE for s in kept),
                      'selfplay_seconds': seconds, 'reanalyzed': len(selected), 'changed_sign': changed,
                      'reanalysis_seconds': time.monotonic() - started,
                      'replay': {str(x.resolve()): sha(x) for x in args.replay}}
    save(summary, report)
    if args.prepare_only:
        print(json.dumps({'prepared': str(summary)}), flush=True)
        return

    def match(candidate, folder, name, opponent, pairs, seed, timed=False):
        path = folder / f'{name}.json'
        command = [str(arena), '--candidate', str(candidate), '--baseline', str(opponent), '--pairs', str(pairs),
                   '--seed', str(seed), '--output', str(path), '--nodes', '1000000000' if timed else str(args.arena_nodes),
                   '--depth', '64', '--branch', '16', '--size', '15', '--threads', '1' if timed else str(args.threads)]
        if timed:
            command += ['--time-ms', str(args.arena_time_ms)]
        seconds = execute(command, folder, name)
        result = json.loads(path.read_text())
        return {k: v for k, v in result.items() if k != 'results'} | {'report': str(path), 'seconds': seconds, 'passed': passes(result) and result['complete_pairs'] == pairs, 'timed': timed}

    for name, outcome in [('search', 0), ('mixed', .3)]:
        folder = output / name; folder.mkdir()
        points = sorted({1, min(3, args.epochs), args.epochs})
        execute([sys.executable, '-m', 'trainer.train', '--data', str(data), '--output', str(folder / 'best.nnue'),
                 '--resume', str(champion.with_suffix('.pt')), '--architecture', 'legacy', '--epochs', str(args.epochs),
                 '--checkpoint-epochs', *map(str, points), '--lr', '.00003', '--outcome-weight', str(outcome),
                 '--policy-weight', '0', '--device', args.device, '--precision', 'fp32', '--deterministic',
                 '--threads', str(min(args.threads, 4)), '--workers', '0', '--batch-size', '256',
                 '--seed', str(args.seed + 1), '--split-seed', '42'], folder, 'train')
        seen = set()
        for candidate in [folder / f'epoch-{e:03d}.nnue' for e in points] + [folder / 'best.nnue']:
            digest = sha(candidate)
            if digest in seen:
                continue
            seen.add(digest); initial_model(candidate)
            regressions = []
            for i, (sequence, winner) in enumerate(REGRESSIONS):
                path = folder / f'{candidate.stem}-regression-{i}.json'
                execute([sys.executable, '-m', 'scripts.check_threat_regression', '--engine', str(engine),
                         '--weights', str(candidate), '--sequence', sequence, '--winner', winner,
                         '--defenses', '', '--skip-undo', '--allow-unresolved', '--nodes', '1000000',
                         '--output', str(path)], folder, f'{candidate.stem}-regression-{i}')
                regressions.append(all(r['found_mate'] for r in json.loads(path.read_text())['results']))
            if not all(regressions):
                report.setdefault('rejected_regressions', []).append({'candidate': str(candidate), 'passed': regressions})
                save(summary, report)
                continue
            trial = {'candidate': str(candidate), 'sha256': digest, 'checks': [],
                     'screen': match(candidate, folder, candidate.stem + '-screen', champion, args.screen_pairs, args.seed + 100000)}
            report['trials'].append(trial); save(summary, report)
    eligible = sorted((t for t in report['trials'] if t['screen']['paired_mean'] >= .5 and t['screen']['truncated'] == 0), key=lambda t: t['screen']['paired_mean'], reverse=True)
    # Select once on screening; independent seeds are never reused for candidate selection.
    if eligible:
        trial = eligible[0]; candidate = Path(trial['candidate']); approved = True
        for phase, offset in [('verify', 200000), ('confirm', 300000)]:
            for timed in [False, True]:
                for label, opponent in [('gen9', champion), ('hce', 'hce')]:
                    result = match(candidate, candidate.parent, f'{candidate.stem}-{phase}-{label}-{"time" if timed else "nodes"}', opponent, args.verify_pairs, args.seed + offset + (10000 if timed else 0), timed)
                    trial['checks'].append(result | {'phase': phase, 'opponent': label}); save(summary, report)
                    if not result['passed']:
                        approved = False; break
                if not approved: break
            if not approved: break
        if approved:
            for suffix in ['.nnue', '.pt']:
                shutil.copyfile(candidate.with_suffix(suffix), output / ('champion' + suffix))
            report.update(promoted=True, champion_sha256=sha(candidate))
    report['completed'] = True
    save(summary, report)
    print(json.dumps({'completed': str(summary), 'promoted': report['promoted']}), flush=True)


if __name__ == '__main__':
    main()
