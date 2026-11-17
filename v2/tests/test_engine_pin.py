"""Exercise merged-engine verification and historical patch reproduction with Git."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apply_engine_patch


class EnginePinTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.engine = self.root / 'checkout'
        self.engine.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.engine / 'source').write_text('before\n')
        self.git('add', 'source')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        (self.engine / 'source').write_text('after\n')
        diff = self.git('diff')
        (self.root / 'engine').mkdir()
        (self.root / 'engine/flight-sql.patch').write_text(diff)
        self.git('commit', '-qam', 'merged Flight')
        self.pinned = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'upstream.json').write_text(json.dumps({
            'implementation_commit': self.pinned, 'flight_patch_base_commit': self.base}))
        self.addCleanup(patch.stopall)
        patch.object(apply_engine_patch, 'ROOT', self.root).start()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.engine, text=True)

    def test_merged_pin_is_verified_without_mutation(self):
        apply_engine_patch.apply(self.engine)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.pinned)

    def test_rejects_dirty_merged_pin(self):
        (self.engine / 'source').write_text('after\nmodified\n')
        with self.assertRaisesRegex(ValueError, 'clean pinned'):
            apply_engine_patch.apply(self.engine)

    def test_rejects_unrelated_commit(self):
        (self.engine / 'other').write_text('different revision\n')
        self.git('add', 'other')
        self.git('commit', '-qm', 'unrelated')
        with self.assertRaisesRegex(ValueError, 'HEAD must match'):
            apply_engine_patch.apply(self.engine)

    def test_reproduces_historical_patch_idempotently(self):
        self.git('checkout', '-q', '--detach', self.base)
        apply_engine_patch.apply(self.engine)
        self.assertEqual((self.engine / 'source').read_text(), 'after\n')
        apply_engine_patch.apply(self.engine)
        self.assertEqual((self.engine / 'source').read_text(), 'after\n')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.base)

    def test_rejects_pin_that_does_not_contain_flight(self):
        config = self.root / 'upstream.json'
        config.write_text(json.dumps({'implementation_commit': self.base,
                                     'flight_patch_base_commit': self.base}))
        self.git('checkout', '-q', '--detach', self.base)
        with self.assertRaises(subprocess.CalledProcessError):
            apply_engine_patch.apply(self.engine)


if __name__ == '__main__':
    unittest.main()
