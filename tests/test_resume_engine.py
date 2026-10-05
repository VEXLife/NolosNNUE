"""Engine-only source migration must preserve learner configuration and checkpoints."""
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import resume_engine
from scripts.resume_engine import prepare, source_hashes


class ResumeEngineTests(unittest.TestCase):
    def test_dry_run_and_audited_update_preserve_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            engine = root / 'src/board.rs'
            engine.write_text('original engine')
            run = root / 'run'
            run.mkdir()
            path = run / 'config.json'
            saved = dict(run_dir=str(run), threads=10, outcome_weight=.1,
                         source_sha256=source_hashes(root))
            path.write_text(json.dumps(saved))
            checkpoint = run / 'candidate.pt'
            checkpoint.write_bytes(b'original learner checkpoint')
            original = path.read_bytes()
            engine.write_text('accelerated engine')
            def configured_prepare(*args, **kwargs):
                return prepare(*args, root=root, **kwargs)
            argv = ['resume', '--run-dir', str(run), '--accept-engine-update']
            with patch.object(resume_engine, 'prepare', side_effect=configured_prepare), \
                    patch.object(resume_engine.subprocess, 'run') as launch, \
                    patch('sys.stdout', new_callable=io.StringIO):
                with patch.object(sys, 'argv', argv + ['--dry-run']):
                    resume_engine.main()
                launch.assert_not_called()
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse((run / 'engine-updates').exists())
                with patch.object(sys, 'argv', argv):
                    resume_engine.main()
                self.assertTrue(launch.called)
            audit = json.loads(next((run / 'engine-updates').glob('*.json')).read_text())
            self.assertEqual(audit['before_config'], saved)
            updated = json.loads(path.read_text())
            self.assertEqual(updated, audit['after_config'])
            self.assertEqual(updated['source_sha256'], source_hashes(root))
            self.assertEqual(updated['outcome_weight'], .1)
            self.assertEqual(checkpoint.read_bytes(), b'original learner checkpoint')

    def test_accepts_only_engine_update_and_preserves_original_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'trainer').mkdir()
            (root / 'src/board.rs').write_text('old engine')
            (root / 'trainer/train.py').write_text('original training')
            run = root / 'run'
            run.mkdir()
            saved = dict(run_dir=str(run), threads=10, outcome_weight=.1,
                         train_device='cpu', train_precision='fp32', train_resume='candidate',
                         source_sha256=source_hashes(root))
            path = run / 'config.json'
            path.write_text(json.dumps(saved))
            original = path.read_bytes()
            (root / 'src/board.rs').write_text('accelerated engine')
            with self.assertRaises(ValueError):
                prepare(run, root=root)
            before, updated, changed, command = prepare(run, True, root, 'python', 6)
            self.assertEqual(before, saved)
            self.assertEqual(changed, ['src/board.rs'])
            self.assertEqual({k: v for k, v in updated.items() if k != 'source_sha256'},
                             {k: v for k, v in saved.items() if k != 'source_sha256'})
            self.assertEqual(command[command.index('--threads') + 1], '10')
            self.assertEqual(command[command.index('--worker-threads') + 1], '6')
            self.assertEqual(command[command.index('--outcome-weight') + 1], '0.1')
            self.assertEqual(command[command.index('--train-precision') + 1], 'fp32')
            self.assertEqual(path.read_bytes(), original)
            (root / 'trainer/train.py').write_text('different training')
            with self.assertRaisesRegex(ValueError, 'non-engine'):
                prepare(run, True, root)


if __name__ == '__main__':
    unittest.main()
