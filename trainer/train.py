"""Train only on this engine's generated positions; no downloaded chess data."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import random
import os
import time
from contextlib import nullcontext
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from trainer.model import NNUE, FEATURES, NORMALIZER
from trainer.checksum import sha256_file


def make_grad_scaler(enabled):
    # torch.amp exists in older releases without exposing GradScaler.
    scaler = getattr(getattr(torch, "amp", None), "GradScaler", None)
    if scaler is not None:
        return scaler("cuda", enabled=enabled)
    return torch.cuda.amp.GradScaler(enabled=enabled)


def target_entropy(targets):
    # BCE cannot reach zero for the soft search/outcome labels.
    targets = targets.double()
    return -(torch.special.xlogy(targets, targets)
             + torch.special.xlogy(1 - targets, 1 - targets)).sum()


def accumulators(model, items, dense):
    if dense:
        values = items[0] @ torch.cat((model.embedding, model.embedding[model.inverse]), dim=1) / NORMALIZER
        return (values + model.bias.repeat(2)).chunk(2, dim=1)
    return tuple(F.embedding_bag(ids, model.embedding, items[2], mode='sum',
        per_sample_weights=items[1] / NORMALIZER, include_last_offset=True) + model.bias
        for ids in (items[0], model.inverse[items[0]]))


@torch.no_grad()
def revive_flat_units(model, items, dense, seed, init_scale):
    """Recycle units contributing exactly zero on every calibration position.

    Only training positions may be used for calibration. Setting the new head
    weights to zero preserves predictions on that calibration set at restart.
    """
    flat = torch.ones_like(model.head, dtype=torch.bool)
    positions = 0
    for b in items:
        black, white = accumulators(model, b, dense)
        flat &= (((black <= 0) & (white <= 0)) | ((black >= 1) & (white >= 1))).all(dim=0)
        positions += len(black)
    if positions == 0:
        raise ValueError('training positions required to revive flat units')
    units = flat.nonzero().flatten()
    generator = torch.Generator(device=model.embedding.device).manual_seed(seed)
    embedding = torch.randn((FEATURES, len(units)), generator=generator,
                            device=model.embedding.device) * init_scale
    # Empty/boundary/color-invariant patterns are extremely frequent. Avoid
    # making their random offsets saturate a revived tower before learning.
    invariant = model.inverse == torch.arange(FEATURES, device=model.embedding.device)
    embedding[invariant] = 0
    model.embedding[:, units] = embedding
    model.bias[units] = 0.4
    model.head[units] = 0
    return units.cpu().tolist()


def batch(samples, device, outcome_weight):
    ids, counts, offsets, sides, targets = [], [], [0], [], []
    for s in samples:
        for feature, count in s["features"]:
            ids.append(feature)
            counts.append(count)
        offsets.append(len(ids))
        sides.append(1.0 if s["side"] == 1 else -1.0)
        search_target = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, s["score"] / 600.0))))
        outcome = s["outcome"]
        targets.append(search_target if outcome is None else (1.0 - outcome_weight) * search_target + outcome_weight * outcome)
    return tuple(torch.tensor(v, dtype=dtype, device=device) for v, dtype in [
        (ids, torch.long), (counts, torch.float32), (offsets, torch.long), (sides, torch.float32), (targets, torch.float32)])


def load_data(paths, validation_fraction, seed, spatial=False):
    samples = []
    sources = []
    for path in paths:
        digest = sha256_file(path)
        sources.append({"path": str(path), "sha256": digest})
        with path.open() as f:
            for line in f:
                s = json.loads(line)
                if not 5 <= s["size"] <= 20 or s["side"] not in (1, 2) or s["rule"] != 0:
                    raise ValueError("this trainer currently trains freestyle positions only")
                if len(s["board"]) != s["size"] ** 2 or set(s["board"]) - set("012"):
                    raise ValueError("invalid board encoding")
                if s["outcome"] not in (None, 0, 0.5, 1) or not math.isfinite(s["score"]) or (s["depth"] < 1 and not (s.get("vcf_depth", 0) > 0)):
                    raise ValueError("invalid training label")
                if any(not 0 <= i < FEATURES or not 0 < n <= 65535 for i, n in s["features"]):
                    raise ValueError("invalid sparse feature")
                if len({i for i, _ in s["features"]}) != len(s["features"]):
                    raise ValueError("duplicate sparse feature")
                # The group identity must not depend on nondeterministic
                # multithreaded JSONL write order (the provenance hash may).
                s["group"] = (s["seed"], s["game"], s["size"], s["rule"])
                if spatial:
                    if "best_move" in s and (not isinstance(s["best_move"], int) or not 0 <= s["best_move"] < len(s["board"]) or s["board"][s["best_move"]] != '0'):
                        raise ValueError("invalid policy label")
                    s.pop("features")
                samples.append(s)
    groups = sorted({s["group"] for s in samples})
    if len(groups) < 4:
        raise ValueError("at least four independent games are required")
    # Split each immutable self-play cohort separately. Adding/replaying new
    # generations must not turn the previous model's training games into its
    # validation games. The split seed stays fixed across all generations.
    cohorts = {}
    for group in groups:
        cohort = (group[0], group[2], group[3])
        cohorts.setdefault(cohort, []).append(group)
    validation_groups = set()
    for cohort, members in sorted(cohorts.items()):
        random.Random(f"{seed}:{cohort}").shuffle(members)
        validation_groups.update(members[:max(1, round(len(members) * validation_fraction))])
    train = sorted((s for s in samples if s["group"] not in validation_groups), key=lambda s: (s["group"], s["board"]))
    val = sorted((s for s in samples if s["group"] in validation_groups), key=lambda s: (s["group"], s["board"]))
    return train, val, sources, len(groups), len(validation_groups)


class PackedPositions(torch.utils.data.Dataset):
    """Compact host representation; dense batches are constructed in workers."""
    def __init__(self, samples, outcome_weight):
        width = max(len(s["features"]) for s in samples)
        self.ids = np.full((len(samples), width), FEATURES, dtype=np.uint16)
        self.counts = np.zeros((len(samples), width), dtype=np.uint16)
        self.sides = np.empty(len(samples), dtype=np.float32)
        self.targets = np.empty(len(samples), dtype=np.float32)
        for row, sample in enumerate(samples):
            features = sample["features"]
            if len({i for i, _ in features}) != len(features):
                raise ValueError("duplicate sparse feature")
            for column, (feature, count) in enumerate(features):
                self.ids[row, column] = feature
                self.counts[row, column] = count
            self.sides[row] = 1 if sample["side"] == 1 else -1
            target = 1 / (1 + math.exp(-max(-30, min(30, sample["score"] / 600))))
            self.targets[row] = target if sample["outcome"] is None else (1 - outcome_weight) * target + outcome_weight * sample["outcome"]

    def __len__(self):
        return len(self.sides)

    def __getitem__(self, index):
        return index

    def collate(self, indices):
        rows = np.asarray(indices, dtype=np.int64)
        dense = np.zeros((len(rows), FEATURES + 1), dtype=np.float32)
        dense[np.arange(len(rows))[:, None], self.ids[rows]] = self.counts[rows]
        return (torch.from_numpy(dense[:, :FEATURES].copy()),
                torch.from_numpy(self.sides[rows]), torch.from_numpy(self.targets[rows]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--architecture", choices=("legacy", "spatial"), default="legacy")
    p.add_argument("--policy-weight", type=float, default=0.5)
    p.add_argument("--data", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--resume", type=Path)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--checkpoint-epochs", type=int, nargs="*", default=[], help="export these epochs along the same optimizer/scheduler trajectory (legacy)")
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--lr", type=float, default=0.003)
    p.add_argument("--init-scale", type=float, default=0.05, help="embedding/revival initialization std; unused for a plain resume")
    p.add_argument("--revive-flat-units", action='store_true', help='reinitialize units flat on every training position; requires --resume')
    p.add_argument("--outcome-weight", type=float, default=0.30)
    p.add_argument("--validation-fraction", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--split-seed", type=int, default=42)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--device", default="cpu")
    p.add_argument("--backend", choices=("auto", "dense", "sparse"), default="auto")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--precision", choices=("auto", "fp32", "bf16", "fp16"), default="auto")
    p.add_argument("--deterministic", action="store_true")
    args = p.parse_args()
    if args.revive_flat_units and not args.resume:
        p.error('--revive-flat-units requires --resume')
    if any(e < 1 or e > args.epochs for e in args.checkpoint_epochs):
        p.error("checkpoint epochs must lie within the training run")
    if args.architecture == "spatial" and args.checkpoint_epochs:
        p.error("checkpoint epochs currently require legacy architecture")
    if args.architecture == "spatial":
        from trainer.spatial_train import run
        return run(args)
    device = torch.device(args.device)
    cuda = device.type == "cuda"
    dense = args.backend == "dense" or (cuda and args.backend == "auto")
    if cuda and not dense:
        p.error("CUDA requires --backend dense for efficient, deterministic-compatible accumulation")
    args.batch_size = (4096 if cuda else 128) if args.batch_size is None else args.batch_size
    deterministic = args.deterministic or not cuda
    if deterministic and cuda:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    if cuda and not torch.cuda.is_available():
        p.error("CUDA requested but unavailable; install a CUDA-enabled PyTorch build")
    if cuda:
        torch.cuda.set_device(device.index if device.index is not None else torch.cuda.current_device())
        device = torch.device("cuda", torch.cuda.current_device())
    if not cuda and args.precision not in ("auto", "fp32"):
        p.error("bf16/fp16 training currently requires CUDA")
    precision = args.precision
    if precision == "auto":
        precision = "bf16" if cuda and torch.cuda.is_bf16_supported() else "fp32"
    if precision == "bf16" and not torch.cuda.is_bf16_supported():
        p.error("this CUDA device does not support bf16")
    torch.set_float32_matmul_precision("highest" if deterministic else "high")
    torch.backends.cuda.matmul.allow_tf32 = cuda and not deterministic

    if args.epochs < 1 or args.batch_size < 1 or args.threads < 1 or args.workers < 0 or not 0 < args.validation_fraction < 0.5 or not 0 <= args.outcome_weight <= 1 or not math.isfinite(args.lr) or args.lr <= 0:
        p.error("invalid training configuration")
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.use_deterministic_algorithms(deterministic)
    train, validation, sources, games, val_games = load_data(args.data, args.validation_fraction, args.split_seed)
    if not train or not validation:
        raise ValueError("both training and validation games are required")
    train_count, validation_count = len(train), len(validation)
    workers = args.workers if dense else 0
    train_loader = validation_loader = None
    if dense:
        packed_train = PackedPositions(train, args.outcome_weight)
        packed_validation = PackedPositions(validation, args.outcome_weight)
        del train, validation
        loader_options = {"batch_size": args.batch_size, "num_workers": workers,
                          "pin_memory": cuda, "persistent_workers": workers > 0}
        if workers:
            loader_options["prefetch_factor"] = 2
        train_loader = torch.utils.data.DataLoader(packed_train, shuffle=True,
            collate_fn=packed_train.collate, generator=torch.Generator().manual_seed(args.seed), **loader_options)
        validation_loader = torch.utils.data.DataLoader(packed_validation, shuffle=False,
            collate_fn=packed_validation.collate, **loader_options)
    if not 0 < args.init_scale < float('inf'):
        p.error('invalid initialization scale')
    model = NNUE(init_scale=args.init_scale).to(device)
    if args.resume:
        model.load_state_dict(torch.load(args.resume, map_location=device, weights_only=True))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0001, fused=cuda)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.05)
    rng = random.Random(args.seed)

    amp_dtype = torch.bfloat16 if precision == "bf16" else torch.float16
    scaler = make_grad_scaler(cuda and precision == "fp16")

    def autocast():
        return torch.autocast("cuda", dtype=amp_dtype) if cuda and precision != "fp32" else nullcontext()

    def batches(training):
        if dense:
            for items in train_loader if training else validation_loader:
                yield tuple(item.to(device, non_blocking=True) for item in items)
        else:
            samples = train if training else validation
            for start in range(0, len(samples), args.batch_size):
                yield batch(samples[start:start + args.batch_size], device, args.outcome_weight)

    def predict(items):
        return model.forward_dense(*items[:2]) if dense else model(*items[:4])

    @torch.no_grad()
    def validate():
        model.eval()
        totals = torch.zeros(2, device=device) if cuda else [0.0, 0.0]
        for b in batches(False):
            with autocast():
                predictions = predict(b)
            loss_sum = F.binary_cross_entropy_with_logits(predictions, b[-1], reduction="sum")
            mae_sum = (torch.sigmoid(predictions) - b[-1]).abs().sum()
            totals[0] += loss_sum if cuda else loss_sum.item()
            totals[1] += mae_sum if cuda else mae_sum.item()
        loss, mae = (totals / validation_count).cpu().tolist() if cuda else [v / validation_count for v in totals]
        if not math.isfinite(loss):
            raise RuntimeError("non-finite validation loss")
        return loss, mae

    runtime = {"torch_version": torch.__version__, "cuda_version": torch.version.cuda,
               "device": str(device), "gpu": torch.cuda.get_device_name(device) if cuda else None,
               "precision": precision, "deterministic": deterministic,
               "batch_size": args.batch_size, "workers": workers,
               "accumulator": "dense_gemm" if dense else "sparse_embedding_bag"}
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    initial_loss, _ = validate()
    original_initial_loss = initial_loss
    revived_units = []
    if args.revive_flat_units:
        def calibration():
            if dense:
                for start in range(0, len(packed_train), args.batch_size):
                    items = packed_train.collate(range(start, min(start + args.batch_size, len(packed_train))))
                    yield tuple(item.to(device) for item in items)
            else:
                yield from batches(True)
        revived_units = revive_flat_units(model, calibration(), dense, args.seed, args.init_scale)
        initial_loss, _ = validate()
        print(json.dumps({'revived_units': revived_units, 'original_initial_validation_loss': original_initial_loss,
                          'initial_validation_loss': initial_loss}), flush=True)
    with torch.no_grad():
        entropy = sum(target_entropy(b[-1]).item() for b in batches(False)) / validation_count
    best_loss = initial_loss
    best_state = copy.deepcopy(model.state_dict())
    best_epoch = 0
    history = []
    print(json.dumps({"train_positions": train_count, "validation_positions": validation_count, "games": games, "validation_games": val_games, "initial_validation_loss": initial_loss, "runtime": runtime}), flush=True)
    for epoch in range(args.epochs):
        started = time.perf_counter()
        if not dense:
            rng.shuffle(train)
        model.train()
        total = torch.zeros((), device=device) if cuda else 0.0
        for b in batches(True):
            optimizer.zero_grad(set_to_none=True)
            with autocast():
                predictions = predict(b)
            loss = F.binary_cross_entropy_with_logits(predictions, b[-1])
            if not cuda and not torch.isfinite(loss):
                raise RuntimeError("non-finite training loss")
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            total += (loss.detach() if cuda else loss.item()) * len(b[-1])
        train_loss = (total / train_count).item() if cuda else total / train_count
        if not math.isfinite(train_loss):
            raise RuntimeError("non-finite training loss")
        val_loss, mae = validate()
        elapsed = time.perf_counter() - started
        row = {"epoch": epoch + 1, "train_loss": train_loss, "validation_loss": val_loss,
               "validation_excess_bce": val_loss - entropy,
               "validation_probability_mae": mae, "epoch_seconds": elapsed,
               "positions_per_second": (train_count + validation_count) / elapsed}
        history.append(row)
        if val_loss < best_loss:
            best_loss, best_epoch = val_loss, epoch + 1
            best_state = copy.deepcopy(model.state_dict())
        if epoch == 0 or (epoch + 1) % 5 == 0 or epoch + 1 == args.epochs:
            print(json.dumps(row), flush=True)
        if epoch + 1 in args.checkpoint_epochs:
            checkpoint = args.output.with_name(f"epoch-{epoch + 1:03d}.nnue")
            model.export(checkpoint)
            torch.save(model.state_dict(), checkpoint.with_suffix(".pt"))
        scheduler.step()
    model.load_state_dict(best_state)
    with torch.no_grad():
        clipped, activations = 0, 0
        for b in batches(False):
            accum = torch.cat(accumulators(model, b, dense), dim=1)
            clipped += ((accum <= 0) | (accum >= 1)).sum().item()
            activations += accum.numel()
        diagnostics = {"validation_clipped_activation_fraction": clipped / activations,
                       "head_absolute_sum": model.head.abs().sum().item()}
    model.export(args.output)
    torch.save(best_state, args.output.with_suffix(".pt"))
    report = {"schema": 1, "runtime": runtime, "external_data": False, "external_weights": False, "sources": sources,
              "seed": args.seed, "split_seed": args.split_seed, "train_positions": train_count, "validation_positions": validation_count,
              "games": games, "validation_games": val_games, "initial_validation_loss": initial_loss,
              "best_validation_loss": best_loss, "best_epoch": best_epoch, "outcome_weight": args.outcome_weight,
              "validation_target_entropy": entropy, "best_validation_excess_bce": best_loss - entropy,
              "learning_rate": args.lr, "epochs": args.epochs, "checkpoint_epochs": args.checkpoint_epochs,
              "init_scale": args.init_scale, "network_diagnostics": diagnostics,
              "revived_units": revived_units, "original_initial_validation_loss": original_initial_loss,
              "resume": str(args.resume) if args.resume else None, "history": history,
              "weights_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}
    runtime["peak_cuda_memory_bytes"] = torch.cuda.max_memory_allocated(device) if cuda else 0
    args.output.with_suffix(".training.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"exported": str(args.output), "best_epoch": best_epoch, "best_validation_loss": best_loss}), flush=True)


if __name__ == "__main__":
    main()
