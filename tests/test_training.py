"""Verify both accumulator implementations and packed GPU input semantics on CPU."""
import copy
import json
import tempfile
from pathlib import Path
import unittest
import numpy as np
import torch
from trainer.model import NNUE, FEATURES
from trainer.train import PackedPositions, batch, load_data


class TrainingTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(11)
        torch.set_num_threads(1)
        self.samples = [
            {"features": [[0, 23], [21, 4], [4095, 2]], "side": 1, "score": 123, "outcome": 1},
            {"features": [[5, 11], [73, 6]], "side": 2, "score": -300, "outcome": None},
            {"features": [[0, 4], [341, 8]], "side": 1, "score": 20, "outcome": 0.5},
        ]

    def test_packing_and_last_batch(self):
        packed = PackedPositions(self.samples, 0.3)
        self.assertEqual(packed.ids.dtype, np.uint16)
        for indices in ([0, 1], [2], [2, 0, 1]):
            dense, sides, targets = packed.collate(indices)
            sparse = batch([self.samples[i] for i in indices], "cpu", 0.3)
            self.assertEqual(dense.shape, (len(indices), FEATURES))
            torch.testing.assert_close(sides, sparse[3])
            torch.testing.assert_close(targets, sparse[4])
            for row, index in enumerate(indices):
                self.assertEqual(dense[row].sum().item(), sum(n for _, n in self.samples[index]["features"]))
                for feature, count in self.samples[index]["features"]:
                    self.assertEqual(dense[row, feature].item(), count)

    def test_dense_matches_sparse_predictions_and_gradients(self):
        sparse_model = NNUE()
        dense_model = copy.deepcopy(sparse_model)
        packed = PackedPositions(self.samples, 0.3)
        dense, sides, _ = packed.collate([0, 1, 2])
        sparse = batch(self.samples, "cpu", 0.3)
        expected = sparse_model(*sparse[:4])
        actual = dense_model.forward_dense(dense, sides)
        torch.testing.assert_close(actual, expected, atol=1e-7, rtol=1e-6)
        expected.square().sum().backward()
        actual.square().sum().backward()
        for first, second in zip(sparse_model.parameters(), dense_model.parameters()):
            torch.testing.assert_close(first.grad, second.grad, atol=1e-7, rtol=1e-5)

    def test_cohort_split_stays_stable_across_generations_and_row_order(self):
        def cohort(seed):
            return [dict(self.samples[game % 3], size=5, rule=0, depth=1,
                         board="0" * 25, seed=seed, game=game) for game in range(12)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.jsonl"
            original = cohort(1)
            path.write_text("".join(json.dumps(s) + "\n" for s in original))
            first_train, first_val, *_ = load_data([path], 0.15, 42)
            path.write_text("".join(json.dumps(s) + "\n" for s in original + cohort(2)))
            later_train, later_val, *_ = load_data([path], 0.15, 42)
            old_train = {s["group"] for s in first_train}
            old_val = {s["group"] for s in first_val}
            new_train = {s["group"] for s in later_train}
            new_val = {s["group"] for s in later_val}
            self.assertTrue(old_train <= new_train)
            self.assertTrue(old_val <= new_val)
            self.assertFalse(old_train & new_val)
            path.write_text("".join(json.dumps(s) + "\n" for s in reversed(original + cohort(2))))
            reversed_train, reversed_val, *_ = load_data([path], 0.15, 42)
            self.assertEqual([s["group"] for s in later_train], [s["group"] for s in reversed_train])
            self.assertEqual([s["group"] for s in later_val], [s["group"] for s in reversed_val])

    def test_duplicate_features_rejected(self):
        self.samples[0]["features"].append([0, 1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            PackedPositions(self.samples, 0.3)


if __name__ == "__main__":
    unittest.main()
