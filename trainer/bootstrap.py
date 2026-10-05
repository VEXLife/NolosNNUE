"""HCE -> self-play -> NNUE -> paired promotion tests -> repeat."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from trainer.checksum import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def cargo_target_dir():
    """Cargo output root, honouring CARGO_TARGET_DIR so a read-only checkout can build elsewhere."""
    configured = os.environ.get('CARGO_TARGET_DIR')
    if not configured:
        return ROOT / 'target'
    path = Path(configured).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


def digest(path):
    return sha256_file(path)


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def promotion_check(result, threshold, expected_pairs=None, policy="strict"):
    reasons = []
    if result['complete_pairs'] < 32: reasons.append('fewer than 32 complete opening pairs')
    if expected_pairs is not None and result['complete_pairs'] != expected_pairs: reasons.append('requested opening pairs incomplete')
    if result['truncated'] != 0: reasons.append('truncated games')
    if result['paired_mean'] < threshold: reasons.append('score below promotion threshold')
    if policy == 'strict' and result['paired_ci95'][0] <= 0.5: reasons.append('improvement not statistically resolved')
    return reasons


def initial_model(weights):
    """Require matching inference/training files before starting a new run."""
    import torch
    from trainer.model import model_from_checkpoint
    weights = weights.resolve()
    checkpoint = weights.with_suffix('.pt')
    if not weights.is_file() or not checkpoint.is_file():
        raise ValueError('--initial-weights requires an NNUE file and its matching .pt checkpoint')
    model = model_from_checkpoint(torch.load(checkpoint, map_location='cpu', weights_only=True))
    if any(not torch.isfinite(parameter).all() or (parameter.abs() > 1000).any()
           for parameter in model.parameters()):
        raise ValueError('initial model has non-finite or out-of-range parameters')
    with tempfile.TemporaryDirectory(prefix='gomoku-initial-model-') as folder:
        exported = Path(folder) / 'initial.nnue'
        model.export(exported)
        if exported.read_bytes() != weights.read_bytes():
            raise ValueError('initial NNUE and .pt checkpoint do not match')
    return str(weights), checkpoint


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
    p.add_argument('--initial-weights', type=Path, help='start from an existing NNUE and adjacent .pt instead of HCE')
    p.add_argument('--architecture', choices=['legacy', 'spatial'], default='legacy')
    p.add_argument('--initial-candidate', type=Path, help='matching NNUE/.pt learner seed; independent of teacher')
    p.add_argument('--policy-weight', type=float, default=0.5)
    p.add_argument('--resume-run', action='store_true', help='resume the same directory and configuration')
    p.add_argument('--generations', type=int, default=5)
    p.add_argument('--games', type=int, default=512)
    p.add_argument('--epochs', type=int, default=40)
    p.add_argument('--pairs', type=int, default=512)
    p.add_argument('--nodes', type=int, default=4000)
    p.add_argument('--depth', type=int, default=4)
    p.add_argument('--branch', type=int, default=12)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--size', type=int, default=15)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--promotion-score', type=float, default=0.52)
    p.add_argument('--confirm-pairs', type=int, default=0,
                   help='repeat passed promotion tests on independent openings before promotion')
    p.add_argument('--max-rejections', type=int, default=0,
                   help='stop after this many consecutive rejected generations; 0 disables')
    p.add_argument('--selfplay-nodes', type=int, help='teacher search budget; defaults to --nodes')
    p.add_argument('--selfplay-depth', type=int, help='teacher search depth; defaults to --depth')
    p.add_argument('--exploration', type=float, default=0.10)
    p.add_argument('--data-score-limit', type=float, default=0.0)
    p.add_argument('--train-label-smoothing', type=float, default=0.0)
    p.add_argument('--train-early-stop-patience', type=int, default=0)
    p.add_argument('--train-early-stop-min-delta', type=float, default=0.0001)
    p.add_argument('--train-lr', type=float, default=0.003)
    p.add_argument('--train-init-scale', type=float, default=0.05)
    p.add_argument('--train-revive-flat-units', action='store_true')
    p.add_argument('--outcome-weight', type=float, default=0.30)
    p.add_argument('--train-resume', choices=['champion', 'candidate'], default='champion',
                   help='candidate carries training forward even after arena rejection; teacher stays champion')
    p.add_argument('--replay-generations', type=int, default=3)
    p.add_argument('--train-device', default='cpu')
    p.add_argument('--train-batch-size', type=int, help='default: 128 on CPU, 4096 on CUDA')
    p.add_argument('--train-workers', type=int, default=4, help='CUDA data-loading workers; CPU sparse training ignores this')
    p.add_argument('--train-precision', choices=['auto', 'fp32', 'bf16', 'fp16'], default='auto')
    p.add_argument('--train-deterministic', action='store_true', help='use strict reproducibility rather than CUDA throughput optimizations')
    p.add_argument('--thin-mates', action='store_true')
    p.add_argument('--continue-final', action='store_true', help='continue final learner separately from validation-best candidate')
    p.add_argument('--arena-time-ms', type=int, default=0, help='also require equal-time arenas; 0 disables')
    p.add_argument('--tactical-regressions', action='store_true', help='optional tactical diagnostics; never gates promotion')
    p.add_argument('--migrate-tactical-gate', action='store_true', help='resume the previous HCE package without tactical gates')
    p.add_argument('--promotion-policy', choices=['strict', 'score'], default='strict')
    p.add_argument('--migrate-score-policy', action='store_true')
    p.add_argument('--accept-first-generation', action='store_true', help='accept generation-000 using its completed arena and skip remaining checks')
    p.add_argument('--worker-threads', type=int, help='override selfplay/arena workers without changing training configuration')
    args = p.parse_args()
    if args.data_score_limit and not args.thin_mates:
        p.error('data-score-limit requires --thin-mates dataset preprocessing')
    if not 0 <= args.data_score_limit <= 12000:
        p.error("data-score-limit must be finite and between 0 and 12000")
    if args.worker_threads is not None and not 1 <= args.worker_threads <= 256:
        p.error('--worker-threads must be between 1 and 256')
    if not 0 <= args.train_label_smoothing < 0.5 or args.train_early_stop_patience < 0 or not 0 <= args.train_early_stop_min_delta < float("inf"):
        p.error("invalid smoothing or early stopping configuration")
    if args.architecture != "legacy" and (args.train_label_smoothing or args.train_early_stop_patience):
        p.error("smoothing and early stopping require legacy architecture")
    worker_threads = args.worker_threads if args.worker_threads is not None else args.threads
    if (args.migrate_score_policy or args.accept_first_generation) and not args.resume_run:
        p.error('policy migration and first-generation acceptance require --resume-run')
    if args.promotion_policy == 'score' and (args.confirm_pairs or args.arena_time_ms):
        p.error('score policy requires confirmation and timed arenas disabled')
    if args.migrate_tactical_gate and not args.resume_run:
        p.error('--migrate-tactical-gate requires --resume-run')
    if args.continue_final and (args.architecture != 'legacy' or args.train_resume != 'candidate'):
        p.error('--continue-final requires legacy and --train-resume candidate')
    if args.games < 4 or args.pairs < 32 or args.arena_time_ms < 0:
        p.error('requires 4 games, 32 pairs and nonnegative time limit')
    if args.confirm_pairs < 0 or args.max_rejections < 0:
        p.error('confirmation pairs and rejection limit must be nonnegative')
    if 0 < args.confirm_pairs < 32:
        p.error('confirmation requires at least 32 opening pairs')
    if min(args.generations, args.games, args.epochs, args.pairs, args.nodes, args.depth, args.branch, args.threads, args.replay_generations) < 1 or not 5 <= args.size <= 20 or not 0.5 <= args.promotion_score < 1:
        p.error('invalid experiment configuration')
    if (args.selfplay_nodes is not None and args.selfplay_nodes < 1
        or args.selfplay_depth is not None and not 1 <= args.selfplay_depth <= 64
        or not 0 <= args.exploration <= 1 or not 0 <= args.outcome_weight <= 1
        or not 0 < args.train_lr < float('inf') or not 0 < args.train_init_scale < float('inf')):
        p.error('invalid self-play or training configuration')
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
    initial_champion, initial_checkpoint = 'hce', None
    if args.initial_weights:
        try:
            initial_champion, initial_checkpoint = initial_model(args.initial_weights)
        except (ValueError, RuntimeError, OSError) as error:
            p.error(str(error))
        args.initial_weights = Path(initial_champion)
    candidate_checkpoint = None
    if args.initial_candidate:
        try:
            candidate_weights, candidate_checkpoint = initial_model(args.initial_candidate)
            args.initial_candidate = Path(candidate_weights)
        except (ValueError, RuntimeError, OSError) as error:
            p.error(str(error))
    expected_magic = b'NOLOS002' if args.architecture == 'spatial' else b'NOLOS001'
    for path in ([args.initial_candidate] if args.initial_candidate else
                 [args.initial_weights] if args.initial_weights and args.architecture == 'legacy' else []):
        if path.read_bytes()[:8] != expected_magic:
            p.error('initial learner architecture differs from --architecture')
    if args.initial_candidate and args.train_resume != 'candidate':
        p.error('--initial-candidate requires --train-resume candidate')
    if not 0 <= args.policy_weight < float('inf'):
        p.error('invalid policy weight')
    run_dir = args.run_dir.resolve()
    config = vars(args) | {'run_dir': str(run_dir)}
    config['initial_weights'] = str(args.initial_weights) if args.initial_weights else None
    config['initial_model_sha256'] = ({'nnue': digest(initial_champion), 'pt': digest(initial_checkpoint)}
                                     if initial_checkpoint else None)
    config['initial_candidate'] = str(args.initial_candidate) if args.initial_candidate else None
    config['initial_candidate_sha256'] = ({'nnue': digest(args.initial_candidate), 'pt': digest(candidate_checkpoint)} if candidate_checkpoint else None)
    config.pop('resume_run')
    config.pop('migrate_tactical_gate')
    config.pop('migrate_score_policy')
    config.pop('accept_first_generation')
    config.pop('worker_threads')
    config['source_sha256'] = {
        str(path.relative_to(ROOT)): digest(path)
        for base, extension in [('src', '*.rs'), ('trainer', '*.py'), ('scripts', '*.sh')]
        for path in sorted((ROOT / base).rglob(extension))
    }
    if args.resume_run:
        previous = json.loads((run_dir / 'config.json').read_text())
        if previous != config:
            allowed = {'trainer/bootstrap.py': {'c7fc057c7ea4ba29352bbb50f5ce46eb4d1b3f5d34cdf4806f2c288fed4d9272', '04b038a9e72edae705ddcc9c822342354c65920407e4a3a5039ebdfb139ce46e', '86c1c486a7826ae744d0799456021e6ba6393dd063fc6580b5cbe743481efa82'},
                       'scripts/train_hce.sh': {'5bade16e27c2beee76092d8e7e6f7b7b5207517217d9a7b3d343fe9a631d5837', '7d5f95bd7eb5d485c60736675668685458e7f465dbc00cfab666999640825c97'}}
            ignored = {'source_sha256', 'tactical_regressions'}
            if args.migrate_score_policy:
                ignored |= {'pairs', 'confirm_pairs', 'arena_time_ms', 'promotion_score', 'promotion_policy'}
            before = {k: v for k, v in previous.items() if k not in ignored}
            after = {k: v for k, v in config.items() if k not in ignored}
            old_sources, new_sources = previous['source_sha256'], config['source_sha256']
            changed = {k for k in old_sources.keys() | new_sources.keys() if old_sources.get(k) != new_sources.get(k)}
            compatible = ((args.migrate_tactical_gate or args.migrate_score_policy) and before == after and changed <= allowed.keys()
                          and all(old_sources.get(k) in allowed[k] for k in changed)
                          and not config['tactical_regressions']
                          and (not args.migrate_score_policy or (args.promotion_policy == 'score' and args.pairs == 128 and args.promotion_score == .52)))
            if not compatible:
                p.error('resume requires original configuration; gate migration only accepts the previous HCE package')
            backup = run_dir / ('config.before-score-migration.json' if args.migrate_score_policy else 'config.before-tactical-migration.json')
            if not backup.exists(): atomic_json(backup, previous)
            atomic_json(run_dir / 'config.json', config)
            print('Migrated promotion policy; sampling, training and engine configuration unchanged.', flush=True)
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(run_dir / 'config.json', config)
    target_dir = cargo_target_dir()
    binaries = target_dir / 'release'
    subprocess.run(['cargo', 'build', '--release', '--bins', '--target-dir', str(target_dir)], cwd=ROOT, check=True)
    champion, checkpoint, learner_checkpoint = initial_champion, initial_checkpoint, initial_checkpoint
    learner_checkpoint = candidate_checkpoint or (initial_checkpoint if not args.initial_weights or args.initial_weights.read_bytes()[:8] == expected_magic else None)
    rejections = 0
    replay, reports = [], []
    print(f'Execution workers: {worker_threads}; training CPU threads: {min(args.threads, 4)}', flush=True)
    limits = ['--nodes', str(args.nodes), '--depth', str(args.depth), '--branch', str(args.branch), '--size', str(args.size), '--threads', str(worker_threads)]
    selfplay_limits = ['--nodes', str(args.selfplay_nodes or args.nodes),
                      '--depth', str(args.selfplay_depth or args.depth),
                      '--branch', str(args.branch), '--size', str(args.size), '--threads', str(worker_threads)]

    def save_summary():
        atomic_json(run_dir / 'summary.json', {'external_data': False, 'external_weights': bool(args.initial_weights),
                    'initial_champion': initial_champion, 'champion': champion, 'generations': reports})

    for generation in range(args.generations):
        folder = run_dir / f'generation-{generation:03d}'
        folder.mkdir(exist_ok=args.resume_run)
        raw = folder / 'selfplay.jsonl'
        data = folder / ('training.jsonl' if args.thin_mates else 'selfplay.jsonl')
        candidate = folder / 'candidate.nnue'
        manifest = folder / 'manifest.json'
        if args.resume_run and args.accept_first_generation and generation == 0:
            previous_report = json.loads(manifest.read_text()) if manifest.exists() else None
            if not previous_report or not previous_report.get('first_generation_accepted'):
                train_marker = folder / 'stage-train.json'
                arena_marker = folder / 'stage-arena-0.json'
                if not train_marker.exists() or not arena_marker.exists():
                    raise RuntimeError('First-generation acceptance requires completed training and arena-0 stages')
                for marker in folder.glob('stage-*.json'):
                    for path, checksum in json.loads(marker.read_text())['outputs'].items():
                        if not Path(path).is_file() or digest(path) != checksum:
                            raise RuntimeError(f'First-generation stage checksum mismatch: {path}')
                initial_model(candidate)
                result = json.loads((folder / 'arena-0.json').read_text())
                arena_command = json.loads(arena_marker.read_text())['command']
                requested = int(arena_command[arena_command.index('--pairs') + 1])
                reasons = promotion_check(result, .52, requested, 'score')
                if reasons: raise RuntimeError(f'First-generation completed arena failed: {reasons}')
                if previous_report:
                    backup = folder / 'manifest.before-score-migration.json'
                    if not backup.exists(): atomic_json(backup, previous_report)
                report = {'generation': 0, 'teacher': initial_champion, 'candidate': str(candidate),
                          'data_sha256': digest(data), 'candidate_sha256': digest(candidate),
                          'promoted': True, 'first_generation_accepted': True, 'promotion_policy': 'score',
                          'checks': [{'opponent': initial_champion, 'report': str(folder / 'arena-0.json'),
                                      'passed': True, 'score': result['score'], 'paired_ci95': result['paired_ci95'],
                                      'reasons': [], 'accepted_completed_arena': True}],
                          'commands': [json.loads(m.read_text())['command'] for m in sorted(folder.glob('stage-*.json'))]}
                atomic_json(manifest, report)
                print('generation 0: accepted completed arena; remaining confirmation/time checks skipped', flush=True)
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
            review = ((args.migrate_tactical_gate or args.migrate_score_policy) and not report['promoted']
                      and any('tactical' in c and not c['passed'] for c in report['checks'])
                      and not any('opponent' in c for c in report['checks']))
            if review:
                backup = folder / 'manifest.before-tactical-migration.json'
                if not backup.exists(): atomic_json(backup, report)
                print(f'generation {generation}: reusing training and completing skipped arenas', flush=True)
            else:
                replay.append(data)
                learner_checkpoint = (folder / 'last.pt') if args.continue_final else candidate.with_suffix('.pt')
                if report['promoted']:
                    champion, checkpoint = str(candidate), candidate.with_suffix('.pt')
                    if not checkpoint.exists():
                        raise RuntimeError('Missing champion training checkpoint')
                    shutil.copyfile(champion, run_dir / 'champion.nnue')
                    shutil.copyfile(checkpoint, run_dir / 'champion.pt')
                reports.append(report)
                save_summary()
                print(f'generation {generation}: already complete, promoted={report["promoted"]}', flush=True)
                rejections = 0 if report['promoted'] else rejections + 1
                if args.max_rejections and rejections >= args.max_rejections:
                    print('Stopping: consecutive rejection limit reached.', flush=True)
                    break
                continue
        selfplay_seed = args.seed + generation * 100003
        arena_seed = args.seed + 1_000_000_007 + generation * 100019
        commands = []

        def execute(command, name, output_paths):
            commands.append(command)
            marker = folder / f'stage-{name}.json'
            if args.resume_run and marker.exists():
                done = json.loads(marker.read_text())
                def comparison(value):
                    value = list(value)
                    if Path(value[0]).name in ('selfplay', 'arena') and '--threads' in value:
                        index = value.index('--threads')
                        del value[index:index + 2]
                    return value
                if comparison(done['command']) != comparison(command):
                    raise RuntimeError(f'{name}: command changed since checkpoint')
                if all(path.exists() and digest(path) == done['outputs'].get(str(path)) for path in output_paths):
                    commands[-1] = done['command']
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

        teacher = champion
        existing_selfplay = folder / 'stage-selfplay.json'
        if args.resume_run and existing_selfplay.exists():
            previous_command = json.loads(existing_selfplay.read_text())['command']
            teacher = previous_command[previous_command.index('--weights') + 1]
        execute([str(binaries / 'selfplay'), '--games', str(args.games), '--weights', teacher,
                 '--seed', str(selfplay_seed), '--output', str(raw), '--exploration', str(args.exploration),
                 *selfplay_limits], 'selfplay', [raw])
        if args.thin_mates:
            execute([sys.executable, '-m', 'trainer.sampling', '--input', str(raw), '--output', str(data), '--score-limit', str(args.data_score_limit)],
                    'sampling', [data, data.with_suffix('.sampling.json')])
        replay.append(data)
        command = [sys.executable, '-m', 'trainer.train', '--data', *map(str, replay[-args.replay_generations:]),
                   '--output', str(candidate), '--epochs', str(args.epochs), '--seed', str(args.seed + generation),
                   '--split-seed', str(args.seed), '--device', args.train_device, '--threads', str(min(args.threads, 4)),
                   '--workers', str(args.train_workers), '--precision', args.train_precision,
                   '--lr', str(args.train_lr), '--outcome-weight', str(args.outcome_weight),
                   '--init-scale', str(args.train_init_scale), '--architecture', args.architecture,
                   '--policy-weight', str(args.policy_weight)]
        if args.train_label_smoothing: command += ['--label-smoothing', str(args.train_label_smoothing)]
        if args.train_early_stop_patience: command += ['--early-stop-patience', str(args.train_early_stop_patience), '--early-stop-min-delta', str(args.train_early_stop_min_delta)]
        if args.train_batch_size is not None: command += ['--batch-size', str(args.train_batch_size)]
        if args.train_deterministic: command += ['--deterministic']
        resume_checkpoint = learner_checkpoint if args.train_resume == 'candidate' else checkpoint
        if resume_checkpoint and Path(resume_checkpoint).with_suffix('.nnue').read_bytes()[:8] != expected_magic:
            resume_checkpoint = None
        if resume_checkpoint: command += ['--resume', str(resume_checkpoint)]
        if args.train_revive_flat_units and resume_checkpoint: command += ['--revive-flat-units']
        training_outputs = [candidate, candidate.with_suffix('.pt'), candidate.with_suffix('.training.json')]
        if args.continue_final:
            command += ['--last-output', str(folder / 'last.nnue')]
            training_outputs += [folder / 'last.nnue', folder / 'last.pt']
        execute(command, 'train', training_outputs)
        learner_checkpoint = (folder / 'last.pt') if args.continue_final else candidate.with_suffix('.pt')
        checks = []
        unchanged = champion != 'hce' and digest(candidate) == digest(champion)
        if unchanged:
            checks.append({'opponent': champion, 'report': None, 'passed': False,
                           'score': 0.5, 'paired_ci95': [0.5, 0.5],
                           'reasons': ['candidate is byte-identical to champion']})
            print('Candidate unchanged; skipping arena and retaining champion.', flush=True)
        tactical_diagnostics = []
        if args.tactical_regressions and not unchanged:
            from trainer.sampling import REGRESSIONS
            for i, (sequence, winner) in enumerate(REGRESSIONS):
                result_path = folder / f'tactical-{i}.json'
                execute([sys.executable, '-m', 'scripts.check_threat_regression',
                         '--engine', str(binaries / 'nolos-nnue'), '--weights', str(candidate),
                         '--sequence', sequence, '--winner', winner, '--defenses', '',
                         '--skip-undo', '--allow-unresolved', '--nodes', '1000000',
                         '--output', str(result_path)], f'tactical-{i}', [result_path])
                result = json.loads(result_path.read_text())
                passed = all(r['found_mate'] for r in result['results'])
                tactical_diagnostics.append({'tactical': i, 'report': str(result_path), 'passed': passed,
                               'reasons': [] if passed else ['held-out mate unresolved']})
        for i, opponent in enumerate([] if unchanged else dict.fromkeys([champion] if args.promotion_policy == 'score' else [champion, 'hce'])):
            result_path = folder / f'arena-{i}.json'
            execute([str(binaries / 'arena'), '--candidate', str(candidate), '--baseline', opponent,
                     '--pairs', str(args.pairs), '--seed', str(arena_seed), '--output', str(result_path), *limits], f'arena-{i}', [result_path])
            result = json.loads(result_path.read_text())
            reasons = promotion_check(result, args.promotion_score, args.confirm_pairs if result_path.name.startswith('confirmation') else args.pairs, args.promotion_policy)
            passed = not reasons
            checks.append({'opponent': opponent, 'report': str(result_path), 'passed': passed,
                           'score': result['score'], 'paired_ci95': result['paired_ci95'], 'reasons': reasons})
            print(json.dumps({'opponent': opponent, 'passed': passed, 'reasons': reasons}), flush=True)
        promoted = all(c['passed'] for c in checks)
        if promoted and args.confirm_pairs:
            # A new seed prevents promotion based only on the openings that
            # selected the candidate. Recheck each required opponent.
            for i, opponent in enumerate(dict.fromkeys([champion] if args.promotion_policy == 'score' else [champion, 'hce'])):
                result_path = folder / f'confirmation-{i}.json'
                execute([str(binaries / 'arena'), '--candidate', str(candidate), '--baseline', opponent,
                         '--pairs', str(args.confirm_pairs), '--seed', str(arena_seed + 2_000_000_033),
                         '--output', str(result_path), *limits], f'confirmation-{i}', [result_path])
                result = json.loads(result_path.read_text())
                reasons = promotion_check(result, args.promotion_score, args.confirm_pairs if result_path.name.startswith('confirmation') else args.pairs, args.promotion_policy)
                checks.append({'opponent': opponent, 'confirmation': True, 'report': str(result_path),
                               'passed': not reasons, 'score': result['score'],
                               'paired_ci95': result['paired_ci95'], 'reasons': reasons})
            promoted = all(c['passed'] for c in checks)
        if promoted and args.arena_time_ms:
            for phase, pairs, offset in [('time', args.pairs, 3_000_000_041), ('time-confirm', args.confirm_pairs, 4_000_000_063)]:
                if not pairs: continue
                for i, opponent in enumerate(dict.fromkeys([champion] if args.promotion_policy == 'score' else [champion, 'hce'])):
                    result_path = folder / f'{phase}-{i}.json'
                    execute([str(binaries / 'arena'), '--candidate', str(candidate), '--baseline', opponent,
                             '--pairs', str(pairs), '--seed', str(arena_seed + offset), '--output', str(result_path),
                             '--nodes', '1000000000', '--depth', str(args.depth), '--branch', str(args.branch),
                             '--size', str(args.size), '--threads', '1', '--time-ms', str(args.arena_time_ms)],
                            f'{phase}-{i}', [result_path])
                    result = json.loads(result_path.read_text())
                    reasons = promotion_check(result, args.promotion_score, pairs)
                    checks.append({'opponent': opponent, 'phase': phase, 'report': str(result_path),
                                   'passed': not reasons, 'score': result['score'], 'paired_ci95': result['paired_ci95'], 'reasons': reasons})
                    if reasons: break
                if reasons: break
            promoted = all(c['passed'] for c in checks)
        if promoted:
            champion, checkpoint = str(candidate), candidate.with_suffix('.pt')
            shutil.copyfile(candidate, run_dir / 'champion.nnue')
            shutil.copyfile(checkpoint, run_dir / 'champion.pt')
        report = {'generation': generation, 'teacher': teacher, 'candidate': str(candidate),
                  'data_sha256': digest(data), 'candidate_sha256': digest(candidate),
                  'promoted': promoted, 'promotion_policy': args.promotion_policy, 'checks': checks, 'tactical_diagnostics': tactical_diagnostics, 'commands': commands}
        atomic_json(manifest, report)
        reports.append(report)
        save_summary()
        print(f'generation {generation}: promoted={promoted}, champion={champion}', flush=True)
        rejections = 0 if promoted else rejections + 1
        if args.max_rejections and rejections >= args.max_rejections:
            print('Stopping: consecutive rejection limit reached.', flush=True)
            break
    if checkpoint:
        shutil.copyfile(champion, run_dir / 'champion.nnue')
        shutil.copyfile(checkpoint, run_dir / 'champion.pt')
    print(f'Experiment saved to {run_dir}. A rejected candidate never becomes the next teacher.')


if __name__ == '__main__':
    main()
