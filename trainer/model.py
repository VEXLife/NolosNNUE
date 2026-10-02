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
    def __init__(self):
        super().__init__()
        self.embedding = nn.Parameter(torch.randn(FEATURES, HIDDEN) * 0.002)
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
