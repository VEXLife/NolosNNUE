"""Alternate fixed-node native benchmarks; compare timings and exact search results."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--after', type=Path, default=Path('target/release/search_bench'))
    p.add_argument('--input', type=Path, default=Path('artifacts/search-bench-positions.txt'))
    p.add_argument('--weights', type=Path, default=Path('artifacts/cloud-gen9.nnue'))
    p.add_argument('--nodes', type=int, default=50000)
    p.add_argument('--rounds', type=int, default=5)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if min(args.nodes, args.rounds) < 1:
        p.error('positive nodes and rounds required')
    binaries = {'before': args.before.resolve(), 'after': args.after.resolve()}

    def run(label):
        result = subprocess.run([str(binaries[label]), '--input', str(args.input.resolve()),
                                 '--weights', str(args.weights.resolve()), '--nodes', str(args.nodes),
                                 '--repeats', '1'], check=True, capture_output=True, text=True)
        return [json.loads(line) for line in result.stdout.splitlines()]

    for label in binaries:
        run(label)  # Discard warmup; do not overlap timed runs with compilation.
    rows = []
    for round_index in range(args.rounds):
        for label in (['before', 'after'] if round_index % 2 == 0 else ['after', 'before']):
            rows.extend(row | {'engine': label, 'round': round_index} for row in run(label))
        print(f'round {round_index + 1}/{args.rounds}', flush=True)
    positions = []
    for index in sorted({row['position'] for row in rows}):
        groups = {label: [row for row in rows if row['engine'] == label and row['position'] == index]
                  for label in binaries}
        same = all(len({row[key] for group in groups.values() for row in group}) == 1
                   for key in ['nodes', 'depth', 'selective_depth', 'vcf_nodes', 'vcf_depth', 'score', 'best'])
        timings = {label: statistics.median(row['seconds'] for row in group)
                   for label, group in groups.items()}
        positions.append({'position': index, 'identical_search_result': same,
                          'median_seconds': timings, 'time_reduction': 1 - timings['after'] / timings['before'],
                          'diagnostics': groups['after'][0]})
    checksum = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'nodes': args.nodes, 'rounds': args.rounds,
              'sha256': {label: checksum(path) for label, path in binaries.items()} |
                        {'weights': checksum(args.weights), 'input': checksum(args.input)},
              'positions': positions, 'samples': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if not all(row['identical_search_result'] for row in positions):
        raise SystemExit('search result mismatch; inspect report')


if __name__ == '__main__':
    main()
