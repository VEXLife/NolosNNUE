"""Compare native engines on identical recorded positions with node and time limits."""
import argparse
import json
from pathlib import Path
import time
from scripts.match_external import Peer, digest, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, default=Path('target/release/nolos-nnue'))
    parser.add_argument('--weights', type=Path, default=Path('artifacts/cloud-gen9.nnue'))
    parser.add_argument('--plies', nargs='+', type=int, default=[2, 6, 10, 14, 18])
    parser.add_argument('--nodes', type=int, default=50000)
    parser.add_argument('--time-ms', type=int, default=600000)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--after-selective', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if min(args.nodes, args.time_ms, args.rounds) < 1:
        parser.error('positive nodes, time and rounds required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    moves = json.loads(args.game.read_text())['games'][0]['moves']
    report = {'nodes': args.nodes, 'time_ms': args.time_ms, 'rounds': args.rounds, 'after_selective': args.after_selective, 'weights_sha256': digest(args.weights), 'positions': []}
    for round_index in range(args.rounds):
        engines = [('before', args.before), ('after', args.after)]
        for label, binary in (engines if round_index % 2 == 0 else engines[::-1]):
            for ply in args.plies:
                if not 0 <= ply < len(moves):
                    parser.error('benchmark ply outside saved game')
                peer = Peer([str(binary.resolve()), '--weights', str(args.weights.resolve())])
                try:
                    peer.send('START 15')
                    peer.receive(lambda line: line == 'OK', 10)
                    if label == 'after' and args.after_selective:
                        peer.send('INFO selective_search 1')
                    peer.send('INFO rule 0', f'INFO timeout_turn {args.time_ms}', 'INFO max_depth 64',
                              f'INFO max_node {args.nodes}', 'INFO hash_size 65536', 'INFO show_detail 1')
                    side = ply % 2 + 1
                    peer.send('YXBOARD', *(f"{m['x']},{m['y']},{1 if m['side'] == side else 2}"
                        for m in moves[:ply]), 'DONE')
                    started = time.monotonic()
                    peer.send('YXSUGGEST')
                    lines = peer.receive(lambda line: line.startswith('SUGGEST '), 120)
                    fields = {}
                    for line in lines:
                        if line.startswith('INFO '):
                            parts = line.split(maxsplit=2)
                            if len(parts) == 3:
                                fields[parts[1]] = parts[2]
                    row = {'engine': label, 'round': round_index, 'binary_sha256': digest(binary), 'ply': ply,
                           'seconds': time.monotonic() - started, 'analysis': fields, 'transcript': lines}
                    report['positions'].append(row)
                    print(label, ply, row['seconds'], fields.get('DEPTH'), fields.get('NODES'), flush=True)
                    save(args.output, report)
                finally:
                    peer.close()


if __name__ == '__main__':
    main()
