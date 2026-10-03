"""Capacity/gradient check on a fixed tiny batch, not a strength benchmark."""
import argparse
import json
from pathlib import Path
import torch
from trainer.model import SpatialNNUE
from trainer.spatial_train import PackedSpatial, losses
from trainer.train import target_entropy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.manual_seed(431)
    rows = sorted((json.loads(line) for line in args.data.open()), key=lambda s: (s['game'], s['board']))
    rows = rows[::max(1, len(rows) // 32)][:32]
    packed = PackedSpatial(rows, 0.3)
    batch = packed.collate(range(len(rows)))
    model = SpatialNNUE()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)

    def metrics():
        with torch.no_grad():
            value, policy, logits = losses(model(*batch[:3]), batch)
            return dict(value_bce=value.mean().item(), policy_ce=policy.mean().item(),
                        combined=(value + 0.5 * policy).mean().item(),
                        policy_accuracy=(logits.argmax(1) == batch[-2]).float().mean().item(),
                        target_entropy=(target_entropy(batch[-1]) / len(rows)).item())

    initial = metrics()
    for _ in range(200):
        optimizer.zero_grad(set_to_none=True)
        value, policy, _ = losses(model(*batch[:3]), batch)
        (value + 0.5 * policy).mean().backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
    final = metrics()
    assert final['combined'] < initial['combined'] * 0.5, (initial, final)
    assert final['value_bce'] < initial['value_bce'], (initial, final)
    report = dict(purpose='tiny-batch capacity check; not held-out validation or playing strength',
                  positions=len(rows), steps=200, initial=initial, final=final)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
