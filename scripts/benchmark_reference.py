"""Record a Yixin/Gomocup engine's depth on the same fixed positions."""
import argparse
import json
from pathlib import Path
import re
import time
from scripts.match_external import Peer, digest, save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--cwd', type=Path)
    p.add_argument('--weights', type=Path)
    p.add_argument('--input', type=Path, default=Path('artifacts/search-bench-positions.txt'))
    p.add_argument('--count', type=int, default=6)
    p.add_argument('--time-ms', type=int, default=300)
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--selective', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if min(args.count, args.time_ms, args.rounds) < 1:
        p.error('positive limits required')
    report = {'engine': str(args.engine.resolve()), 'engine_sha256': digest(args.engine),
              'input_sha256': digest(args.input), 'time_ms': args.time_ms, 'threads': 1,
              'selective': args.selective, 'positions': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for repeat in range(args.rounds):
        for index, line in enumerate(args.input.read_text().splitlines()[:args.count]):
            size, side, *moves = line.split()
            size, side = int(size), int(side)
            command = [str(args.engine.resolve())]
            if args.weights:
                command += ['--weights', str(args.weights.resolve())]
            peer = Peer(command, cwd=args.cwd)
            try:
                peer.send(f'START {size}')
                startup = peer.receive(lambda line: line == 'OK', 120)
                peer.send('INFO rule 0', f'INFO timeout_turn {args.time_ms}',
                          'INFO timeout_match 2147483647', 'INFO time_left 2147483647',
                          'INFO max_depth 64', 'INFO max_node 100000000', 'INFO thread_num 1',
                          'INFO hash_size 65536', 'INFO show_detail 2')
                if args.selective:
                    peer.send('INFO selective_search 1')
                rows = []
                for move in moves:
                    square, color = map(int, move.split(':'))
                    rows.append(f'{square % size},{square // size},{1 if color == side else 2}')
                started = time.monotonic()
                peer.send('BOARD', *rows, 'DONE')
                lines = peer.receive(lambda line: re.fullmatch(r'\d+,\d+', line), args.time_ms / 1000 + 20)
                fields = {}
                for line in lines:
                    if line.startswith('INFO '):
                        parts = line.split(maxsplit=2)
                        if len(parts) == 3:
                            fields[parts[1]] = parts[2]
                row = {'position': index, 'round': repeat, 'seconds': time.monotonic() - started,
                       'analysis': fields, 'startup': startup, 'transcript': lines}
                summaries = [line for line in lines if line.startswith('MESSAGE Speed ') and 'Depth ' in line]
                if summaries:
                    match = re.search(r'Depth (\d+)-(\d+).*Time (\d+)ms', summaries[-1])
                    if match:
                        row['final_summary'] = {'depth': int(match[1]), 'selective_depth': int(match[2]),
                                                'search_time_ms': int(match[3]), 'line': summaries[-1]}
                report['positions'].append(row)
                save(args.output, report)
                print(index, repeat, row['seconds'], fields.get('DEPTH'), fields.get('SELDEPTH'), fields.get('NODES'), flush=True)
            finally:
                peer.close()


if __name__ == '__main__':
    main()
