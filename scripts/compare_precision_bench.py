"""Alternate FP32/int16 inference, fixed-node and fixed-time diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, default=Path('target/release/search_bench'))
    p.add_argument('--inference', type=Path, default=Path('target/release/inference_bench'))
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--nodes', type=int, default=100000)
    p.add_argument('--time-ms', type=int, default=1000)
    p.add_argument('--rounds', type=int, default=7)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if min(args.nodes, args.time_ms, args.rounds) < 1:
        p.error('positive nodes, time and rounds required')
    rows = []

    def run(phase, precision):
        if phase == 'inference':
            cmd = [str(args.inference.resolve()), '--weights', str(args.weights.resolve()),
                   '--precision', precision, '--samples', '2000', '--repeats', '500000']
        else:
            cmd = [str(args.engine.resolve()), '--weights', str(args.weights.resolve()),
                   '--input', str(args.input.resolve()), '--precision', precision, '--repeats', '1',
                   '--nodes', str(args.nodes if phase == 'nodes' else 1000000000)]
            if phase == 'time':
                cmd += ['--time-ms', str(args.time_ms)]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return [json.loads(line) | {'precision': precision, 'phase': phase}
                for line in result.stdout.splitlines()]

    for phase in ['inference', 'nodes', 'time']:
        for precision in ['fp32', 'int16']:
            run(phase, precision)  # warmup
        for index in range(args.rounds):
            for precision in (['fp32', 'int16'] if index % 2 == 0 else ['int16', 'fp32']):
                rows.extend(row | {'round': index} for row in run(phase, precision))
            print(f'{phase}: {index + 1}/{args.rounds}', flush=True)
    summary = []
    for phase in ['inference', 'nodes', 'time']:
        positions = sorted({r.get('position', -1) for r in rows if r['phase'] == phase})
        for position in positions:
            entry = {'phase': phase, 'position': position}
            for precision in ['fp32', 'int16']:
                group = [r for r in rows if r['phase'] == phase and r['precision'] == precision
                         and r.get('position', -1) == position]
                entry[precision] = {key: statistics.median(r[key] for r in group)
                                    for key in ['seconds', 'nodes', 'depth', 'nps'] if key in group[0]}
                if phase != 'inference':
                    entry[precision]['best_moves'] = sorted({r['best'] for r in group}, key=str)
                    entry[precision]['scores'] = sorted({r['score'] for r in group})
                else:
                    entry['error'] = {k: group[0][k] for k in
                                      ['error_samples', 'mean_abs_error', 'p95_abs_error', 'max_abs_error']}
            summary.append(entry)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'nodes': args.nodes, 'time_ms': args.time_ms, 'rounds': args.rounds,
              'sha256': {name: digest(path) for name, path in
                         [('engine', args.engine), ('inference', args.inference),
                          ('weights', args.weights), ('input', args.input)]},
              'summary': summary, 'samples': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
