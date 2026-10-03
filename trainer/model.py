"""The Rust NOLOS001 architecture, including canonical color inversion."""
from __future__ import annotations
import struct
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

FEATURES, HIDDEN, NORMALIZER, SCALE = 4096, 32, 32.0, 600.0


def canonical(pattern: int) -> int:
    reverse = sum(((pattern >> (2 * i)) & 3) << (2 * (5 - i)) for i in range(6))
    return min(pattern, reverse)


def invert(pattern: int) -> int:
    return canonical(sum((2 if (c := (pattern >> (2 * i)) & 3) == 1 else 1 if c == 2 else c) << (2 * i) for i in range(6)))


INVERSE = np.array([invert(i) for i in range(FEATURES)], dtype=np.int64)


class NNUE(nn.Module):
    def __init__(self, init_scale=0.05):
        super().__init__()
        # Tiny embeddings leave almost all accumulators inside clip's linear
        # region, where the two color towers collapse to one linear evaluator.
        self.embedding = nn.Parameter(torch.randn(FEATURES, HIDDEN) * init_scale)
        self.bias = nn.Parameter(torch.full((HIDDEN,), 0.4))
        self.head = nn.Parameter(torch.randn(HIDDEN) * 0.05)
        self.tempo = nn.Parameter(torch.tensor(0.0))
        self.register_buffer("inverse", torch.from_numpy(INVERSE.copy()), persistent=False)

    def forward(self, ids, counts, offsets, sides):
        black = F.embedding_bag(ids, self.embedding, offsets, mode="sum", per_sample_weights=counts / NORMALIZER, include_last_offset=True)
        white = F.embedding_bag(self.inverse[ids], self.embedding, offsets, mode="sum", per_sample_weights=counts / NORMALIZER, include_last_offset=True)
        value = ((black + self.bias).clamp(0.0, 1.0) - (white + self.bias).clamp(0.0, 1.0)) @ self.head
        return value * sides + self.tempo

    def forward_dense(self, counts, sides):
        """GPU-friendly equivalent of the sparse accumulator (one dense GEMM)."""
        weights = torch.cat((self.embedding, self.embedding[self.inverse]), dim=1)
        accumulators = counts @ weights / NORMALIZER
        black, white = accumulators.split(HIDDEN, dim=1)
        # Keep the small output head in float32, including under autocast.
        with torch.autocast(device_type=counts.device.type, enabled=False):
            value = ((black.float() + self.bias).clamp(0.0, 1.0)
                     - (white.float() + self.bias).clamp(0.0, 1.0)) @ self.head.float()
            return value * sides + self.tempo.float()

    @torch.no_grad()
    def export(self, path: Path):
        arrays = [self.embedding, self.bias, self.head, self.tempo.reshape(1)]
        payload = b"".join(p.detach().cpu().numpy().astype("<f4").tobytes() for p in arrays)
        checksum = 2166136261
        for byte in payload:
            checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
        header = struct.pack("<8sIIffI", b"NOLOS001", FEATURES, HIDDEN, NORMALIZER, SCALE, checksum)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(header + payload)

SPATIAL_FEATURES, CHANNELS, VALUE_HIDDEN = 1 << 18, 16, 32


def spatial_tables():
    ids = np.arange(SPATIAL_FEATURES, dtype=np.int64)
    reverse = np.zeros_like(ids)
    inverse = np.zeros_like(ids)
    for i in range(9):
        cells = (ids >> (2 * i)) & 3
        reverse |= cells << (2 * (8 - i))
        inverse |= np.where(cells == 1, 2, np.where(cells == 2, 1, cells)) << (2 * i)
    canonical_ids = np.minimum(ids, reverse)
    return canonical_ids, canonical_ids[inverse]


SPATIAL_CANONICAL, SPATIAL_INVERSE = spatial_tables()


def spatial_patterns(board, size):
    cells = np.asarray([int(c) for c in board], dtype=np.int64).reshape(size, size)
    padded = np.pad(cells, 4, constant_values=3)
    patterns = np.zeros((size, size, 4), dtype=np.int64)
    for direction, (dx, dy) in enumerate(((1, 0), (0, 1), (1, 1), (1, -1))):
        for offset in range(-4, 5):
            x, y = 4 + dx * offset, 4 + dy * offset
            patterns[:, :, direction] |= padded[y:y + size, x:x + size] << (2 * (offset + 4))
    return SPATIAL_CANONICAL[patterns.reshape(size * size, 4)]


class SpatialNNUE(nn.Module):
    """Local directional embedding -> crossing ReLU -> pooled value and point policy.

    Both towers share parameters; side chooses their order. No clipping ceiling
    and no forced black/white antisymmetry, so first-player advantage is learnable.
    """
    def __init__(self, init_scale=0.05):
        super().__init__()
        self.embedding = nn.Parameter(torch.randn(SPATIAL_FEATURES, CHANNELS) * init_scale)
        self.local_bias = nn.Parameter(torch.full((CHANNELS,), 0.05))
        self.policy = nn.Parameter(torch.randn(CHANNELS * 2) * 0.05)
        self.policy_bias = nn.Parameter(torch.tensor(0.0))
        self.value_in = nn.Parameter(torch.randn(VALUE_HIDDEN, CHANNELS * 2) * 0.15)
        self.value_bias = nn.Parameter(torch.full((VALUE_HIDDEN,), 0.05))
        self.value_out = nn.Parameter(torch.randn(VALUE_HIDDEN) * 0.15)
        self.value_out_bias = nn.Parameter(torch.tensor(0.0))
        self.register_buffer('inverse', torch.from_numpy(SPATIAL_INVERSE.copy()), persistent=False)

    def forward(self, ids, sides, mask):
        # Accumulation stays float32, matching the incremental native evaluator.
        black = (F.embedding(ids, self.embedding).sum(dim=2) * 0.5 + self.local_bias).relu()
        white = (F.embedding(self.inverse[ids], self.embedding).sum(dim=2) * 0.5 + self.local_bias).relu()
        own = torch.where(sides[:, None, None] > 0, black, white)
        opponent = torch.where(sides[:, None, None] > 0, white, black)
        local = torch.cat((own, opponent), dim=-1)
        pooled = (local * mask[..., None]).sum(dim=1) / mask.sum(dim=1, keepdim=True)
        hidden = F.linear(pooled, self.value_in, self.value_bias).relu()
        value = hidden @ self.value_out + self.value_out_bias
        policy = local @ self.policy + self.policy_bias
        return value.float(), policy.float()

    @torch.no_grad()
    def export(self, path):
        arrays = [self.embedding, self.local_bias, self.policy, self.policy_bias.reshape(1),
                  self.value_in, self.value_bias, self.value_out, self.value_out_bias.reshape(1)]
        payload = b''.join(p.detach().cpu().numpy().astype('<f4').tobytes() for p in arrays)
        checksum = 2166136261
        for byte in payload:
            checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack('<8sIIffI', b'NOLOS002', SPATIAL_FEATURES, CHANNELS, 1.0, SCALE, checksum) + payload)


def model_from_checkpoint(state):
    model = SpatialNNUE() if 'local_bias' in state else NNUE()
    model.load_state_dict(state)
    return model
