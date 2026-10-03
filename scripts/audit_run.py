"""Verify an imported bootstrap run and inspect its saved networks on sampled data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from trainer.model import model_from_checkpoint, SpatialNNUE, NORMALIZER
from trainer.spatial_train import PackedSpatial, losses
from trainer.checksum import sha256_file
from trainer.train import PackedPositions, target_entropy


def audit(run, data_generations, model_generations, stride):
    config = json.loads((run / 'config.json').read_text())
    original_root = Path(config['run_dir'])
    hashes = {}

    def verify(path, expected):
        if path not in hashes:
            hashes[path] = sha256_file(path)
        if hashes[path] != expected:
            raise ValueError(f'checksum mismatch: {path}')

    generations = []
    for folder in sorted(run.glob('generation-*')):
        if not (folder / 'manifest.json').exists():
            continue
        manifest = json.loads((folder / 'manifest.json').read_text())
        verify(folder / 'selfplay.jsonl', manifest['data_sha256'])
        verify(folder / 'candidate.nnue', manifest['candidate_sha256'])
        for marker in folder.glob('stage-*.json'):
            stage = json.loads(marker.read_text())
            for name, checksum in stage['outputs'].items():
                verify(run / Path(name).relative_to(original_root), checksum)
        training = json.loads((folder / 'candidate.training.json').read_text())
        generations.append({
            'generation': manifest['generation'], 'teacher': manifest['teacher'],
            'promoted': manifest['promoted'], 'checks': manifest['checks'],
            'initial_validation_loss': training['initial_validation_loss'],
            'best_validation_loss': training['best_validation_loss'],
            'best_epoch': training['best_epoch'],
            'candidate_sha256': manifest['candidate_sha256'],
        })

    samples = []
    for generation in data_generations:
        with (run / f'generation-{generation:03d}' / 'selfplay.jsonl').open() as stream:
            samples.extend(json.loads(line) for index, line in enumerate(stream) if index % stride == 0)
    legacy_packed = spatial_packed = None
    diagnostics = {}
    for generation in model_generations:
        checkpoint = run / f'generation-{generation:03d}' / 'candidate.pt'
        model = model_from_checkpoint(torch.load(checkpoint, map_location='cpu', weights_only=True))
        if isinstance(model, SpatialNNUE):
            if spatial_packed is None:
                spatial_packed = PackedSpatial(samples, 0.30)
            totals = torch.zeros(5, dtype=torch.float64)
            channel_active = torch.zeros(16, dtype=torch.bool)
            with torch.no_grad():
                for start in range(0, len(samples), 256):
                    b = spatial_packed.collate(range(start, min(start + 256, len(samples))))
                    value_loss, policy_loss, policy = losses(model(*b[:3]), b)
                    labeled = b[-2] >= 0
                    totals += torch.tensor([value_loss.sum().item(), policy_loss.sum().item(),
                        labeled.sum().item(), ((policy.argmax(1) == b[-2]) & labeled).sum().item(),
                        target_entropy(b[-1]).item()], dtype=torch.float64)
                    for ids in (b[0], model.inverse[b[0]]):
                        local = torch.nn.functional.embedding(ids, model.embedding).sum(2) * 0.5 + model.local_bias
                        channel_active |= ((local > 0) & (b[2][..., None] > 0)).any(dim=(0, 1))
            value_loss, policy_loss, labeled, correct, entropy = totals.tolist()
            diagnostics[str(generation)] = dict(architecture='spatial', samples=len(samples),
                sample_bce=value_loss / len(samples), sample_target_entropy=entropy / len(samples),
                sample_excess_bce=(value_loss - entropy) / len(samples), policy_positions=int(labeled),
                policy_ce=policy_loss / max(1, labeled), policy_accuracy=correct / max(1, labeled),
                always_inactive_local_channels=(~channel_active).nonzero().flatten().tolist())
            continue
        if legacy_packed is None:
            legacy_packed = PackedPositions(samples, 0.30)
        packed = legacy_packed
        clipped = flat = activations = loss = entropy = 0
        unit_flat = torch.zeros_like(model.head)
        with torch.no_grad():
            for start in range(0, len(samples), 256):
                counts, sides, targets = packed.collate(range(start, min(start + 256, len(samples))))
                accumulators = counts @ torch.cat((model.embedding, model.embedding[model.inverse]), dim=1)
                accumulators = accumulators / NORMALIZER + model.bias.repeat(2)
                black, white = accumulators.chunk(2, dim=1)
                clipped += ((accumulators <= 0) | (accumulators >= 1)).sum().item()
                same_boundary = ((black <= 0) & (white <= 0)) | ((black >= 1) & (white >= 1))
                unit_flat += same_boundary.sum(dim=0)
                flat += same_boundary.sum().item()
                activations += accumulators.numel()
                loss += torch.nn.functional.binary_cross_entropy_with_logits(
                    model.forward_dense(counts, sides), targets, reduction='sum').item()
                entropy += target_entropy(targets).item()
        diagnostics[str(generation)] = {
            'samples': len(samples), 'clipped_activation_fraction': clipped / activations,
            'both_towers_flat_fraction': flat / (activations / 2),
            'sample_bce': loss / len(samples), 'sample_target_entropy': entropy / len(samples),
            'sample_excess_bce': (loss - entropy) / len(samples),
            'head_absolute_sum': model.head.abs().sum().item(),
            'per_unit_flat_fraction': (unit_flat / len(samples)).tolist(),
            'always_flat_units_in_sample': (unit_flat == len(samples)).nonzero().flatten().tolist(),
        }
    return {'schema': 1, 'config': config, 'verified_files': len(hashes),
            'generations': generations, 'diagnostic_data_generations': data_generations,
            'diagnostic_sample_stride': stride, 'diagnostics': diagnostics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-generations', type=int, nargs='+', default=[8, 9, 10])
    parser.add_argument('--model-generations', type=int, nargs='+', default=[0, 5, 10, 12])
    parser.add_argument('--sample-stride', type=int, default=64)
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    if args.sample_stride < 1 or args.threads < 1:
        parser.error('stride and threads must be positive')
    torch.set_num_threads(args.threads)
    result = audit(args.run_dir, args.data_generations, args.model_generations, args.sample_stride)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'verified_files': result['verified_files'], 'diagnostics': result['diagnostics']}, indent=2))


if __name__ == '__main__':
    main()
