"""Training for the incrementally evaluated spatial value/policy network."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import random
import time
from contextlib import nullcontext
import numpy as np
import torch
from torch.nn import functional as F
from trainer.model import SpatialNNUE, spatial_patterns


class PackedSpatial(torch.utils.data.Dataset):
    def __init__(self, samples, outcome_weight):
        width = max(s['size'] ** 2 for s in samples)
        self.ids = np.zeros((len(samples), width, 4), dtype=np.int32)
        self.mask = np.zeros((len(samples), width), dtype=np.float32)
        self.empty = np.zeros((len(samples), width), dtype=np.bool_)
        self.sides = np.empty(len(samples), dtype=np.float32)
        self.targets = np.empty(len(samples), dtype=np.float32)
        self.labels = np.full(len(samples), -1, dtype=np.int64)
        for i, s in enumerate(samples):
            n = s['size'] ** 2
            self.ids[i, :n] = spatial_patterns(s['board'], s['size'])
            self.mask[i, :n] = 1
            self.empty[i, :n] = np.fromiter((c == '0' for c in s['board']), dtype=np.bool_, count=n)
            self.sides[i] = 1 if s['side'] == 1 else -1
            search = 1 / (1 + math.exp(-max(-30, min(30, s['score'] / 600))))
            self.targets[i] = search if s['outcome'] is None else (1 - outcome_weight) * search + outcome_weight * s['outcome']
            self.labels[i] = s.get('best_move', -1)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        return index

    def collate(self, indices):
        rows = np.asarray(indices, dtype=np.int64)
        return tuple(torch.from_numpy(array[rows]) for array in
                     (self.ids, self.sides, self.mask, self.empty, self.labels, self.targets))


def losses(predictions, batch):
    value, policy = predictions
    value_loss = F.binary_cross_entropy_with_logits(value, batch[-1], reduction='none')
    labels = batch[-2]
    # Finite mask avoids NaN on unlabeled/full-board rows; labels are validated.
    policy = policy.masked_fill(~batch[3], -10000.0)
    policy_loss = F.cross_entropy(policy, labels, ignore_index=-1, reduction='none')
    return value_loss, policy_loss, policy


def run(args):
    from trainer.train import load_data, make_grad_scaler, target_entropy
    if args.revive_flat_units:
        raise ValueError('flat-unit revival applies only to the legacy architecture')
    if min(args.epochs, args.threads) < 1 or args.workers < 0 or not 0 < args.lr < float('inf') or not 0 <= args.policy_weight < float('inf') or not 0 < args.init_scale < float('inf') or not 0 <= args.outcome_weight <= 1 or not 0 < args.validation_fraction < 0.5:
        raise ValueError('invalid spatial training configuration')
    device = torch.device(args.device)
    cuda = device.type == 'cuda'
    if cuda and not torch.cuda.is_available():
        raise ValueError('CUDA requested but unavailable')
    if cuda:
        torch.cuda.set_device(device.index if device.index is not None else torch.cuda.current_device())
        device = torch.device('cuda', torch.cuda.current_device())
    precision = args.precision
    if precision == 'auto':
        precision = 'bf16' if cuda and torch.cuda.is_bf16_supported() else 'fp32'
    if not cuda and precision != 'fp32' or precision == 'bf16' and not torch.cuda.is_bf16_supported():
        raise ValueError('requested precision is unavailable')
    batch_size = args.batch_size or (256 if cuda else 64)
    if batch_size < 1:
        raise ValueError('batch size must be positive')
    deterministic = args.deterministic or not cuda
    if deterministic and cuda:
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.use_deterministic_algorithms(deterministic)
    torch.set_float32_matmul_precision('highest' if deterministic else 'high')
    torch.backends.cuda.matmul.allow_tf32 = cuda and not deterministic
    train, val, sources, games, val_games = load_data(args.data, args.validation_fraction, args.split_seed, spatial=True)
    if not train or not val:
        raise ValueError('both training and validation games are required')
    print(json.dumps(dict(stage='packing_spatial', train_positions=len(train), validation_positions=len(val))), flush=True)
    packed_train, packed_val = PackedSpatial(train, args.outcome_weight), PackedSpatial(val, args.outcome_weight)
    del train, val
    generator = torch.Generator().manual_seed(args.seed)
    options = dict(batch_size=batch_size, num_workers=args.workers, pin_memory=cuda, persistent_workers=args.workers > 0)
    if args.workers:
        options['prefetch_factor'] = 2
    loaders = [torch.utils.data.DataLoader(data, shuffle=training, collate_fn=data.collate,
               generator=generator if training else None, **options)
               for data, training in ((packed_train, True), (packed_val, False))]
    model = SpatialNNUE(args.init_scale).to(device)
    if args.resume:
        model.load_state_dict(torch.load(args.resume, map_location=device, weights_only=True))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0001, fused=cuda)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.epochs, eta_min=args.lr * 0.1)
    scaler = make_grad_scaler(cuda and precision == 'fp16')
    runtime = dict(torch_version=torch.__version__, cuda_version=torch.version.cuda, device=str(device),
                   gpu=torch.cuda.get_device_name(device) if cuda else None, precision=precision,
                   deterministic=deterministic, batch_size=batch_size, workers=args.workers,
                   accumulator='local_embedding_gather', embedding_precision='fp32', head_precision=precision, parameters=sum(p.numel() for p in model.parameters()))
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)

    def batches(training):
        for batch in loaders[0 if training else 1]:
            yield tuple(item.to(device, non_blocking=True) for item in batch)

    def predict(batch):
        context = torch.autocast('cuda', dtype=torch.bfloat16 if precision == 'bf16' else torch.float16) if cuda and precision != 'fp32' else nullcontext()
        with context:
            return model(*batch[:3])

    @torch.no_grad()
    def validate():
        model.eval()
        total = torch.zeros(6, device=device, dtype=torch.float64)
        for b in batches(False):
            predictions = predict(b)
            value_loss, policy_loss, policy = losses(predictions, b)
            labeled = b[-2] >= 0
            total[0] += value_loss.sum()
            total[1] += policy_loss.sum()
            total[2] += labeled.sum()
            total[3] += ((policy.argmax(dim=1) == b[-2]) & labeled).sum()
            total[4] += (predictions[0].sigmoid() - b[-1]).abs().sum()
            total[5] += target_entropy(b[-1])
        value, policy, count, correct, mae, entropy = total.cpu().tolist()
        return dict(value_loss=value / len(packed_val), policy_loss=policy / max(1, count),
                    policy_positions=int(count), policy_accuracy=correct / max(1, count),
                    probability_mae=mae / len(packed_val), target_entropy=entropy / len(packed_val),
                    loss=(value + args.policy_weight * policy) / len(packed_val))

    initial = validate()
    best, best_epoch, best_state = initial, 0, copy.deepcopy(model.state_dict())
    history = []
    print(json.dumps(dict(architecture='spatial', train_positions=len(packed_train), validation_positions=len(packed_val),
                         train_policy_positions=int((packed_train.labels >= 0).sum()), initial_validation=initial, runtime=runtime)), flush=True)
    for epoch in range(args.epochs):
        start = time.perf_counter()
        model.train()
        total = torch.zeros((), device=device)
        for b in batches(True):
            optimizer.zero_grad(set_to_none=True)
            value_loss, policy_loss, _ = losses(predict(b), b)
            loss = (value_loss + args.policy_weight * policy_loss).mean()
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            total += loss.detach() * len(b[-1])
        validation = validate()
        train_loss = total.item() / len(packed_train)
        if not math.isfinite(train_loss) or not math.isfinite(validation['loss']):
            raise RuntimeError('non-finite spatial loss')
        elapsed = time.perf_counter() - start
        row = dict(epoch=epoch + 1, train_loss=train_loss, validation=validation,
                   epoch_seconds=elapsed, positions_per_second=(len(packed_train) + len(packed_val)) / elapsed)
        history.append(row)
        print(json.dumps(row), flush=True)
        if validation['loss'] < best['loss']:
            best, best_epoch, best_state = validation, epoch + 1, copy.deepcopy(model.state_dict())
        scheduler.step()
    model.load_state_dict(best_state)
    model.export(args.output)
    torch.save(best_state, args.output.with_suffix('.pt'))
    runtime['peak_cuda_memory_bytes'] = torch.cuda.max_memory_allocated(device) if cuda else 0
    report = dict(schema=2, architecture='spatial', runtime=runtime, external_data=False, external_weights=False,
                  sources=sources, seed=args.seed, split_seed=args.split_seed, games=games, validation_games=val_games,
                  train_positions=len(packed_train), validation_positions=len(packed_val),
                  initial_validation_loss=initial['loss'], best_validation_loss=best['loss'], best_epoch=best_epoch,
                  initial_validation=initial, best_validation=best, learning_rate=args.lr, policy_weight=args.policy_weight,
                  outcome_weight=args.outcome_weight, epochs=args.epochs, resume=str(args.resume) if args.resume else None,
                  history=history, weights_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.output.with_suffix('.training.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(exported=str(args.output), best_epoch=best_epoch)), flush=True)
