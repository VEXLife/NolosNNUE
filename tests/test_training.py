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
    def test_dataset_clamping_preserves_raw_scores_and_raw_model_gradients(self):
        from trainer.sampling import clamp_scores
        from trainer.train import value_target
        samples = [dict(score=s, outcome=None) for s in (-30000, -4000, 0, 400, 30000)]
        kept = clamp_scores(samples, 1000)
        self.assertEqual([s['score'] for s in kept], [-1000, -1000, 0, 400, 1000])
        self.assertEqual([s['raw_score'] for s in kept], [s['score'] for s in samples])
        self.assertEqual(clamp_scores(kept, 1000), kept)
        self.assertEqual(samples[0]['score'], -30000)
        prediction = torch.tensor([10.0], requires_grad=True)
        target = value_target(kept[-1], 0, .025)
        torch.nn.functional.binary_cross_entropy_with_logits(prediction, torch.tensor([target])).backward()
        self.assertGreater(prediction.grad.item(), .1)

    def test_resume_reads_worker_threads_from_environment(self):
        from scripts import resume_hce
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.json').write_text(json.dumps({'run_dir': str(root), 'threads': 6}))
            with patch.dict('os.environ', {'THREADS': '12'}), \
                    patch.object(sys, 'argv', ['resume', '--run-dir', str(root)]), \
                    patch.object(resume_hce.subprocess, 'run') as launch, \
                    patch.object(resume_hce.os, 'chdir'):
                resume_hce.main()
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index('--worker-threads') + 1], '12')
            self.assertEqual(command[command.index('--threads') + 1], '6')
            self.assertEqual(json.loads((root / 'config.json').read_text())['threads'], 6)

    def test_rejected_learner_continues_best_with_softening_and_early_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []

            def launch(command, **kwargs):
                commands.append(command)
                output = Path(command[command.index('--output') + 1])
                if command[0].endswith('/arena'):
                    output.write_text(json.dumps(dict(complete_pairs=32, truncated=0,
                        score=.49, paired_mean=.49, paired_ci95=[.4, .58])))
                else:
                    output.write_bytes(b'NOLOS001candidate or data')
                    if 'trainer.train' in command:
                        output.with_suffix('.pt').write_bytes(b'validation best checkpoint')
                        output.with_suffix('.training.json').write_text('{}')
                return Mock(stdout=io.StringIO('complete\n'), wait=Mock(return_value=0))

            args = ['bootstrap', '--run-dir', str(root / 'run'), '--generations', '2',
                    '--pairs', '32', '--promotion-policy', 'score', '--train-resume', 'candidate',
                    '--train-label-smoothing', '.025', '--train-early-stop-patience', '10']
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(sys, 'argv', args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            training = [c for c in commands if 'trainer.train' in c]
            self.assertEqual(len(training), 2)
            self.assertNotIn('--resume', training[0])
            self.assertEqual(training[1][training[1].index('--resume') + 1],
                             str(root / 'run/generation-000/candidate.pt'))
            for command in training:
                self.assertNotIn('--last-output', command)
                self.assertEqual(command[command.index('--label-smoothing') + 1], '0.025')
                self.assertEqual(command[command.index('--early-stop-patience') + 1], '10')
            selfplay = [c for c in commands if c[0].endswith('/selfplay')]
            self.assertTrue(all(c[c.index('--weights') + 1] == 'hce' for c in selfplay))

    def test_hce_promotion_requires_node_and_time_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []

            def launch(command, **kwargs):
                commands.append(command)
                output = Path(command[command.index('--output') + 1])
                if command[0].endswith('/arena'):
                    output.write_text(json.dumps(dict(complete_pairs=32, truncated=0,
                        score=0.60, paired_mean=0.60, paired_ci95=[0.55, 0.65])))
                elif 'scripts.check_threat_regression' in command:
                    output.write_text(json.dumps({'results': [{'found_mate': False}]}))
                else:
                    output.write_bytes(b'NOLOS001candidate or data')
                    if 'trainer.train' in command:
                        output.with_suffix('.pt').write_bytes(b'checkpoint')
                        output.with_suffix('.training.json').write_text('{}')
                        last = Path(command[command.index('--last-output') + 1])
                        last.write_bytes(b'NOLOS001last epoch')
                        last.with_suffix('.pt').write_bytes(b'last checkpoint')
                return Mock(stdout=io.StringIO('complete\n'), wait=Mock(return_value=0))

            args = ['bootstrap', '--run-dir', str(root / 'run'), '--generations', '1',
                    '--pairs', '32', '--confirm-pairs', '32', '--arena-time-ms', '10',
                    '--continue-final', '--train-resume', 'candidate', '--tactical-regressions']
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(sys, 'argv', args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            arenas = [c for c in commands if c[0].endswith('/arena')]
            self.assertEqual(len(arenas), 4)
            timed = [c for c in arenas if '--time-ms' in c]
            self.assertEqual(len(timed), 2)
            self.assertTrue(all(c[c.index('--threads') + 1] == '1' for c in timed))
            self.assertEqual(len({c[c.index('--seed') + 1] for c in arenas}), 4)
            self.assertTrue(json.loads((root / 'run/summary.json').read_text())['generations'][0]['promoted'])
            # Simulate the previous package's tactical-only rejection and migrate.
            folder = root / 'run/generation-000'
            report = json.loads((folder / 'manifest.json').read_text())
            report['checks'] = report.pop('tactical_diagnostics')
            report['promoted'] = False
            (folder / 'manifest.json').write_text(json.dumps(report))
            for marker in folder.glob('stage-*.json'):
                if any(name in marker.name for name in ('arena', 'confirmation', 'time')):
                    marker.unlink()
            config_path = root / 'run/config.json'
            config = json.loads(config_path.read_text())
            config['source_sha256'] = {
                'trainer/bootstrap.py': 'c7fc057c7ea4ba29352bbb50f5ce46eb4d1b3f5d34cdf4806f2c288fed4d9272',
                'scripts/train_hce.sh': '5bade16e27c2beee76092d8e7e6f7b7b5207517217d9a7b3d343fe9a631d5837'}
            config_path.write_text(json.dumps(config))
            commands.clear()
            resume_args = [a for a in args if a != '--tactical-regressions'] + ['--resume-run', '--migrate-tactical-gate', '--worker-threads', '12']
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(sys, 'argv', resume_args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            self.assertEqual(len(commands), 4)
            self.assertTrue(all(c[0].endswith('/arena') for c in commands))
            self.assertTrue(all(c[c.index('--threads') + 1] == '12' for c in commands if '--time-ms' not in c))
            migrated = json.loads((folder / 'manifest.json').read_text())
            self.assertTrue(migrated['promoted'])
            self.assertEqual(migrated['tactical_diagnostics'], [])
            self.assertTrue((folder / 'manifest.before-tactical-migration.json').exists())
            # Accept the completed first arena without launching any remaining checks.
            migrated['promoted'] = False
            (folder / 'manifest.json').write_text(json.dumps(migrated))
            commands.clear()
            fast_args = [a for a in resume_args if a != '--migrate-tactical-gate'] + [
                '--migrate-score-policy', '--accept-first-generation', '--promotion-policy', 'score',
                '--pairs', '128', '--confirm-pairs', '0', '--arena-time-ms', '0']
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap.subprocess, 'run'), \
                    patch.object(bootstrap.subprocess, 'Popen', side_effect=launch), \
                    patch.object(bootstrap, 'initial_model', return_value=(str(folder / 'candidate.nnue'), folder / 'candidate.pt')), \
                    patch.object(sys, 'argv', fast_args), patch('sys.stdout', new_callable=io.StringIO):
                bootstrap.main()
            self.assertEqual(commands, [])
            accepted = json.loads((folder / 'manifest.json').read_text())
            self.assertTrue(accepted['first_generation_accepted'])
            self.assertTrue(accepted['promoted'])
            self.assertEqual(json.loads((root / 'run/summary.json').read_text())['champion'], str(folder / 'candidate.nnue'))

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
        self.assertIn('requested opening pairs incomplete', promotion_check(result, 0.50, 512))
        self.assertEqual(promotion_check(result, 0.50, 128), [])
        noisy = result | dict(paired_mean=.52, score=.52, paired_ci95=[.48, .56])
        self.assertEqual(promotion_check(noisy, .52, 128, 'score'), [])
        self.assertTrue(promotion_check(noisy | dict(paired_mean=.519), .52, 128, 'score'))
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

    def test_smoothed_targets_match_sparse_and_dense(self):
        samples = [dict(self.samples[0], score=30000),
                   dict(self.samples[1], score=-30000),
                   dict(self.samples[2], score=0, outcome=None)]
        sparse = batch(samples, 'cpu', 0, .025)
        packed = PackedPositions(samples, 0, .025)
        torch.testing.assert_close(sparse[-1], packed.collate([0, 1, 2])[-1])
        torch.testing.assert_close(sparse[-1], torch.tensor([.975, .025, .5]))

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

    def test_initialization_does_not_saturate_with_color_invariant_offsets(self):
        model = NNUE()
        invariant = model.inverse == torch.arange(FEATURES)
        self.assertEqual(model.embedding[invariant].abs().sum().item(), 0)
        counts = torch.zeros(2, FEATURES)
        counts[:, invariant] = 1000
        black, white = __import__('trainer.train', fromlist=['accumulators']).accumulators(
            model, (counts,), True)
        torch.testing.assert_close(black, model.bias.expand_as(black))
        torch.testing.assert_close(white, model.bias.expand_as(white))

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
