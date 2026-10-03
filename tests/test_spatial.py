import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from trainer.model import SpatialNNUE, spatial_patterns, SPATIAL_INVERSE
from trainer.spatial_train import PackedSpatial, losses
from trainer.train import load_data
from trainer.bootstrap import initial_model


class SpatialTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(44)
        self.model = SpatialNNUE()
        self.sample = dict(size=9, board='0' * 40 + '1' + '2' + '0' * 39, side=1,
                           score=100, outcome=1, best_move=39)

    def test_symmetry_color_side_and_board_rotation(self):
        s = self.sample
        swapped = s | dict(board=s['board'].translate(str.maketrans('12', '21')), side=2)
        rotated = s | dict(board=''.join(np.rot90(np.array(list(s['board'])).reshape(9, 9)).flatten()))
        packed = PackedSpatial([s, swapped, rotated], 0.3)
        with torch.no_grad():
            value, policy = self.model(*packed.collate([0, 1, 2])[:3])
        self.assertTrue(torch.allclose(value[0], value[1], atol=1e-7))
        self.assertTrue(torch.allclose(value[0], value[2], atol=1e-7))
        self.assertTrue(torch.allclose(policy[0], policy[1], atol=1e-7))
        self.assertTrue(np.allclose(np.rot90(policy[0].reshape(9, 9).numpy()), policy[2].reshape(9, 9).numpy(), atol=1e-7))
        ids = spatial_patterns(s['board'], 9)
        inverse = spatial_patterns(swapped['board'], 9)
        np.testing.assert_array_equal(SPATIAL_INVERSE[ids], inverse)

    def test_value_policy_gradients_and_unlabeled_rows(self):
        samples = [self.sample, {k: v for k, v in self.sample.items() if k != 'best_move'}]
        packed = PackedSpatial(samples, 0.3)
        b = packed.collate([0, 1])
        value, policy, _ = losses(self.model(*b[:3]), b)
        self.assertEqual(policy[1].item(), 0)
        (value.mean() + policy.mean()).backward()
        for name in ('embedding', 'policy', 'value_in', 'value_out'):
            self.assertGreater(getattr(self.model, name).grad.abs().sum().item(), 0)
        # The new value head is not constrained to cancel its two color towers.
        with torch.no_grad():
            self.model.value_out.zero_()
            self.model.value_out_bias.fill_(0.7)
            prediction, _ = self.model(*b[:3])
        self.assertTrue(torch.allclose(prediction, torch.full_like(prediction, 0.7)))

    def test_autocast_heads_have_finite_gradients(self):
        packed = PackedSpatial([self.sample], 0.3)
        batch = packed.collate([0])
        with torch.autocast('cpu', dtype=torch.bfloat16):
            predictions = self.model(*batch[:3])
            value, policy, _ = losses(predictions, batch)
        self.assertTrue(all(p.dtype == torch.float32 for p in predictions))
        (value + policy).sum().backward()
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in self.model.parameters()))

    def test_export_checkpoint_match_and_proof_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'seed.nnue'
            self.model.export(path)
            torch.save(self.model.state_dict(), path.with_suffix('.pt'))
            self.assertEqual(initial_model(path)[0], str(path))
            self.assertEqual(path.read_bytes()[:8], b'NOLOS002')
            samples = [self.sample | dict(game=i, seed=1, rule=0, features=[], depth=0, vcf_depth=17) for i in range(8)]
            data = Path(folder) / 'data.jsonl'
            data.write_text(''.join(json.dumps(s) + '\n' for s in samples))
            train, val, *_ = load_data([data], .2, 42, spatial=True)
            self.assertEqual(len(train) + len(val), 8)
            self.assertNotIn('features', train[0])
            legacy_train, legacy_val, *_ = load_data([data], .2, 42)
            self.assertEqual(len(legacy_train) + len(legacy_val), 8)
            samples[0]['best_move'] = 40
            data.write_text(''.join(json.dumps(s) + '\n' for s in samples))
            with self.assertRaisesRegex(ValueError, 'invalid policy label'):
                load_data([data], .2, 42, spatial=True)
