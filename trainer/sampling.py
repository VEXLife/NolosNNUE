"""Shared mate thinning and held-out tactical positions."""
from collections import defaultdict
import re
import argparse
import json
import math
from pathlib import Path
from trainer.experiment import sha, save

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
            color = (sample['side'] if sample.get('raw_score', sample['score']) > 0 else 3 - sample['side']) if abs(sample.get('raw_score', sample['score'])) >= MATE else None
            if color is None:
                run_color, count = None, 0
                kept.append(sample)
            else:
                count = count + 1 if color == run_color else 1
                run_color = color
                if count <= 2:
                    kept.append(sample)
    return kept



def clamp_scores(samples, limit):
    """Clamp persisted training labels after tactical filtering; retain raw scores."""
    result = []
    for sample in samples:
        raw = sample.get('raw_score', sample['score'])
        if not math.isfinite(raw):
            raise ValueError('non-finite dataset score')
        result.append(dict(sample, raw_score=raw, score=max(-limit, min(limit, raw))))
    return result


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--score-limit', type=float, default=0.0)
    args = parser.parse_args()
    if not 0 <= args.score_limit <= 12000:
        parser.error('score-limit must be finite and between 0 and 12000')
    samples = [json.loads(line) for line in args.input.read_text().splitlines()]
    if any(s['outcome'] is None for s in samples):
        raise ValueError('truncated games cannot enter bootstrap training')
    kept = thin_samples(samples)
    heldout = heldout_boards()
    excluded = {(s['seed'], s['game'], s['size'], s['rule']) for s in kept if s['board'] in heldout}
    kept = [s for s in kept if (s['seed'], s['game'], s['size'], s['rule']) not in excluded]
    ordinary = sum(abs(s['score']) < MATE for s in kept)
    raw_scores = [s['score'] for s in kept]
    if args.score_limit:
        kept = clamp_scores(kept, args.score_limit)
    with args.output.open('w') as stream:
        for sample in kept:
            stream.write(json.dumps(sample, separators=(',', ':')) + '\n')
    report = {'raw_positions': len(samples), 'kept_positions': len(kept),
              'ordinary_positions': ordinary,
              'score_limit': args.score_limit,
              'clamped_positions': sum(abs(v) > args.score_limit for v in raw_scores) if args.score_limit else 0,
              'raw_score_min': min(raw_scores, default=None), 'raw_score_max': max(raw_scores, default=None),
              'excluded_regression_games': len(excluded), 'source_sha256': sha(args.input),
              'data_sha256': sha(args.output)}
    save(args.output.with_suffix('.sampling.json'), report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()

