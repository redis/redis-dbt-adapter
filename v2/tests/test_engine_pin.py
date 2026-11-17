"""Verify engine identity without coupling it to a historical source patch."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_engine


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
        self.git('commit', '-qam', 'merged Flight')
        self.pinned = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'upstream.json').write_text(json.dumps({
            'implementation_commit': self.pinned}))
        self.addCleanup(patch.stopall)
        patch.object(verify_engine, 'ROOT', self.root).start()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.engine, text=True)

    def test_merged_pin_is_verified_without_mutation(self):
        identity = verify_engine.verify(self.engine)
        self.assertEqual(identity['engine_commit'], self.pinned)
        self.assertEqual(identity['engine_tree'], self.git('rev-parse', 'HEAD^{tree}').strip())
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.pinned)

    def test_rejects_dirty_merged_pin(self):
        (self.engine / 'source').write_text('after\nmodified\n')
        with self.assertRaisesRegex(ValueError, 'clean pinned'):
            verify_engine.verify(self.engine)

    def test_rejects_unrelated_commit(self):
        (self.engine / 'other').write_text('different revision\n')
        self.git('add', 'other')
        self.git('commit', '-qm', 'unrelated')
        with self.assertRaisesRegex(ValueError, 'HEAD must match'):
            verify_engine.verify(self.engine)

    def test_rejects_staged_changes(self):
        (self.engine / 'source').write_text('staged change\n')
        self.git('add', 'source')
        with self.assertRaisesRegex(ValueError, 'clean pinned'):
            verify_engine.verify(self.engine)

    def test_rejects_a_moving_ref_as_the_pin(self):
        (self.root / 'upstream.json').write_text(json.dumps({'implementation_commit': 'main'}))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            verify_engine.verify(self.engine)


if __name__ == '__main__':
    unittest.main()
