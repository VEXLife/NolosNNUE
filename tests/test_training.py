"""Verify both accumulator implementations and packed GPU input semantics on CPU."""
import copy
import io
import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import numpy as np
import torch
from trainer.model import NNUE, FEATURES
from trainer.train import PackedPositions, batch, load_data, make_grad_scaler, target_entropy, revive_flat_units
from trainer.bootstrap import promotion_check, initial_model
from trainer import bootstrap


class TrainingTests(unittest.TestCase):
    def test_failed_confirmation_keeps_initial_teacher_and_stops_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            initial = root / 'initial.nnue'
            initial.write_bytes(b'NOLOS001initial network')
            checkpoint = initial.with_suffix('.pt')
            checkpoint.write_bytes(b'initial checkpoint')
            commands = []
            identical = False

            def launch(command, **kwargs):
                commands.append(command)
                output = Path(command[command.index('--output') + 1])
                if command[0].endswith('/arena'):
                    confirmation = output.name.startswith('confirmation')
                    output.write_text(json.dumps(dict(complete_pairs=32, truncated=0,
                        score=0.50 if confirmation else 0.60,
                        paired_mean=0.50 if confirmation else 0.60,
                        paired_ci95=[0.49, 0.51] if confirmation else [0.55, 0.65])))
                else:
                    output.write_bytes(b'NOLOS001candidate or training data')
                    if 'trainer.train' in command:
                        if identical:
                            output.write_bytes(initial.read_bytes())
                        output.with_suffix('.pt').write_bytes(b'candidate checkpoint')
                        output.with_suffix('.training.json').write_text('{}')
                return Mock(stdout=io.StringIO('stage complete\n'), wait=Mock(return_value=0))

            args = ['bootstrap', '--run-dir', str(root / 'run'), '--initial-weights', str(initial),
                    '--generations', '4', '--pairs', '32', '--confirm-pairs', '32', '--max-rejections', '2']
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap, 'initial_model',
                    return_value=(str(initial), checkpoint)), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(sys, 'argv', args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            summary = json.loads((root / 'run/summary.json').read_text())
            self.assertEqual(len(summary['generations']), 2)
            self.assertEqual(summary['champion'], str(initial))
            self.assertEqual((root / 'run/champion.pt').read_bytes(), checkpoint.read_bytes())
            for report in summary['generations']:
                self.assertFalse(report['promoted'])
                self.assertEqual(report['teacher'], str(initial))
                self.assertTrue(all(c['passed'] for c in report['checks'][:2]))
                self.assertTrue(all(not c['passed'] for c in report['checks'][2:]))
                arena = [c for c in report['commands'] if c[0].endswith('/arena')]
                self.assertNotEqual(arena[0][arena[0].index('--seed') + 1],
                                    arena[2][arena[2].index('--seed') + 1])
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap, 'initial_model',
                    return_value=(str(initial), checkpoint)), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen') as launch_again, \
                    patch.object(sys, 'argv', args + ['--resume-run']), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
                launch_again.assert_not_called()
            identical = True
            commands.clear()
            identical_args = [str(root / 'identical-run') if arg == str(root / 'run') else arg for arg in args]
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap, 'initial_model',
                    return_value=(str(initial), checkpoint)), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(sys, 'argv', identical_args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            self.assertFalse(any(command[0].endswith('/arena') for command in commands))
            summary = json.loads((root / 'identical-run/summary.json').read_text())
            self.assertEqual(summary['champion'], str(initial))
            self.assertEqual(len(summary['generations']), 2)
            self.assertIn('byte-identical', summary['generations'][0]['checks'][0]['reasons'][0])

    def test_amp_compatibility(self):
        modern, legacy = Mock(), Mock()
        with patch.object(torch.amp, 'GradScaler', modern), patch.object(torch.cuda.amp, 'GradScaler', legacy):
            make_grad_scaler(False)
            modern.assert_called_once_with('cuda', enabled=False)
            legacy.assert_not_called()
        for enabled in (False, True):
            legacy = Mock()
            with patch.object(torch.amp, 'GradScaler', None), patch.object(torch.cuda.amp, 'GradScaler', legacy):
                make_grad_scaler(enabled)
                legacy.assert_called_once_with(enabled=enabled)

    def test_soft_label_loss_floor(self):
        targets = torch.tensor([0.0, 0.25, 0.5, 0.75, 1.0])
        entropy = target_entropy(targets)
        self.assertTrue(torch.isfinite(entropy))
        fitted = torch.logit(targets.clamp(1e-7, 1 - 1e-7))
        actual = torch.nn.functional.binary_cross_entropy_with_logits(fitted, targets, reduction='sum')
        self.assertAlmostEqual(entropy.item(), actual.item(), places=5)

    def test_promotion_requires_evidence_even_at_threshold_half(self):
        result = dict(complete_pairs=128, truncated=0, paired_mean=0.539, paired_ci95=[0.504, 0.574])
        self.assertEqual(promotion_check(result, 0.55), ['score below promotion threshold'])
        self.assertEqual(promotion_check(result, 0.50), [])
        for changes in (dict(complete_pairs=31), dict(truncated=1), dict(paired_ci95=[0.49, 0.58])):
            self.assertTrue(promotion_check(result | changes, 0.50))

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

    def test_revival_preserves_calibration_predictions_and_restarts_learning(self):
        original = NNUE()
        with torch.no_grad():
            original.embedding.zero_()
            original.bias.fill_(0.4)
            original.bias[0] = -2
            original.bias[1] = 2
            original.head.fill_(0.1)
            original.embedding[21, 2] = 6.4
        sparse = batch(self.samples, 'cpu', 0.3)
        dense = PackedPositions(self.samples, 0.3).collate([0, 1, 2])
        models = []
        for use_dense, items in ((False, sparse), (True, dense)):
            model = copy.deepcopy(original)
            before = model.forward_dense(*items[:2]) if use_dense else model(*items[:4])
            units = revive_flat_units(model, [items], use_dense, 52, 0.05)
            self.assertEqual(units, [0, 1])
            after = model.forward_dense(*items[:2]) if use_dense else model(*items[:4])
            torch.testing.assert_close(after, before, atol=0, rtol=0)
            torch.testing.assert_close(model.embedding[:, 2:], original.embedding[:, 2:], atol=0, rtol=0)
            self.assertEqual(model.head[units].abs().sum().item(), 0)
            after.sum().backward()
            self.assertGreater(model.head.grad[units].abs().sum().item(), 0)
            models.append(model)
        for first, second in zip(models[0].parameters(), models[1].parameters()):
            torch.testing.assert_close(first, second, atol=0, rtol=0)

    def test_revival_requires_calibration_positions(self):
        with self.assertRaisesRegex(ValueError, 'training positions'):
            revive_flat_units(NNUE(), [], False, 52, 0.05)

    def test_initial_model_requires_matching_inference_and_training_files(self):
        with tempfile.TemporaryDirectory() as folder:
            weights = Path(folder) / 'initial.nnue'
            model = NNUE()
            model.export(weights)
            with self.assertRaisesRegex(ValueError, 'matching .pt'):
                initial_model(weights)
            torch.save(model.state_dict(), weights.with_suffix('.pt'))
            self.assertEqual(initial_model(weights), (str(weights.resolve()), weights.with_suffix('.pt').resolve()))
            with torch.no_grad():
                model.tempo.add_(1)
            torch.save(model.state_dict(), weights.with_suffix('.pt'))
            with self.assertRaisesRegex(ValueError, 'do not match'):
                initial_model(weights)


if __name__ == "__main__":
    unittest.main()
