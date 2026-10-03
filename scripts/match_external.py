"""Empty-board freestyle matches: this engine is black, an external engine white."""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time


class Peer:
    def __init__(self, command, cwd=None):
        self.process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.stderr = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def _errors(self):
        self.stderr.extend(line.rstrip() for line in self.process.stderr)

    def send(self, *lines):
        self.process.stdin.write(''.join(line + '\n' for line in lines))
        self.process.stdin.flush()

    def receive(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        transcript = []
        while True:
            try:
                line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError('engine response timeout')
            if line is None:
                raise RuntimeError('engine exited: ' + '\n'.join(self.stderr[-10:]))
            transcript.append(line)
            if line.startswith(('ERROR', 'UNKNOWN')):
                raise RuntimeError('engine protocol error: ' + line)
            if predicate(line):
                return transcript
            if time.monotonic() >= deadline:
                raise TimeoutError('engine response timeout')

    def close(self):
        if self.process.poll() is None:
            try:
                self.send('END')
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait()


def winning(cells, size, x, y, color):
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count = 1
        for sign in (-1, 1):
            xx, yy = x + dx * sign, y + dy * sign
            while 0 <= xx < size and 0 <= yy < size and cells[yy * size + xx] == color:
                count += 1
                xx, yy = xx + dx * sign, yy + dy * sign
        if count >= 5:
            return True
    return False


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def observed_qualification(games, requested):
    if any(game['winner'] == 2 for game in games):
        return False
    if len(games) == requested and all(game['status'] == 'complete' and game['winner'] == 1 for game in games):
        return True
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--black', type=Path, default=Path('target/release/nolos-nnue'))
    parser.add_argument('--weights', type=Path, default=Path('artifacts/cloud-gen9.nnue'))
    parser.add_argument('--hce', action='store_true', help='test handcrafted evaluation instead of NNUE')
    parser.add_argument('--white', type=Path, required=True)
    parser.add_argument('--white-cwd', type=Path)
    parser.add_argument('--games', type=int, default=1)
    parser.add_argument('--time-ms', type=int, default=1000)
    parser.add_argument('--size', type=int, default=15)
    parser.add_argument('--max-plies', type=int, default=225)
    parser.add_argument('--stop-on-loss', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.games < 1 or args.time_ms < 1 or not 5 <= args.size <= 20 or args.max_plies < 1:
        parser.error('invalid match limits')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'rule': 'freestyle', 'opening': 'empty board',
        'black': str(args.black.resolve()), 'black_sha256': digest(args.black),
        'weights': 'hce' if args.hce else str(args.weights.resolve()),
        'weights_sha256': None if args.hce else digest(args.weights),
        'white': str(args.white.resolve()), 'white_sha256': digest(args.white),
        'time_ms': args.time_ms, 'threads': 1, 'max_depth': 64,
        'games_requested': args.games, 'games': [], 'qualified': None}
    save(args.output, report)
    for game in range(args.games):
        peers = []
        record = {'index': game, 'moves': [], 'winner': None, 'status': 'running', 'startup': []}
        report['games'].append(record)
        cells = [0] * args.size ** 2
        try:
            black_command = [str(args.black.resolve())]
            if not args.hce:
                black_command += ['--weights', str(args.weights.resolve())]
            peers = [Peer(black_command),
                     Peer([str(args.white.resolve())], args.white_cwd)]
            for peer in peers:
                peer.send(f'START {args.size}')
                record['startup'].append(peer.receive(lambda line: line == 'OK', 120))
                peer.send('INFO rule 0', f'INFO timeout_turn {args.time_ms}',
                    'INFO timeout_match 2147483647', 'INFO time_left 2147483647',
                    'INFO max_depth 64', 'INFO max_node 0', 'INFO thread_num 1',
                    'INFO hash_size 65536', 'INFO show_detail 2')
            for ply in range(min(args.max_plies, len(cells))):
                side = ply % 2 + 1
                peer = peers[side - 1]
                started = time.monotonic()
                if not record['moves']:
                    peer.send('BEGIN')
                else:
                    peer.send('BOARD', *(f"{move['x']},{move['y']},{1 if move['side'] == side else 2}"
                        for move in record['moves']), 'DONE')
                lines = peer.receive(lambda line: re.fullmatch(r'\d+,\d+', line), args.time_ms / 1000 + 10)
                x, y = map(int, lines[-1].split(','))
                if not 0 <= x < args.size or not 0 <= y < args.size or cells[y * args.size + x]:
                    raise RuntimeError(f'illegal move from side {side}: {x},{y}')
                cells[y * args.size + x] = side
                record['moves'].append({'side': side, 'x': x, 'y': y,
                    'seconds': time.monotonic() - started, 'analysis': lines[:-1]})
                print(f"game {game + 1}, ply {ply + 1}: {'black' if side == 1 else 'white'} {x},{y}", flush=True)
                if winning(cells, args.size, x, y, side):
                    record.update(status='complete', winner=side)
                    break
                save(args.output, report)
            else:
                record.update(status='complete' if len(record['moves']) == len(cells) else 'truncated',
                              winner=0 if len(record['moves']) == len(cells) else None)
        except (OSError, RuntimeError, TimeoutError) as error:
            record.update(status='error', error=str(error))
        finally:
            for peer in peers:
                peer.close()
            record['stderr'] = [peer.stderr for peer in peers]
            # A white victory disproves qualification. Winning this finite suite
            # only passes the observed tests; it does not prove a winning strategy.
            report['qualified'] = observed_qualification(report['games'], args.games)
            save(args.output, report)
        print(f"game {game + 1}: {record['status']}, winner={record['winner']}", flush=True)
        if record['status'] == 'error' or args.stop_on_loss and record['winner'] == 2:
            break


if __name__ == '__main__':
    main()
