"""Release checks must reject altered packages and accidental editable installs."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import verify_release
import check_wheel_install


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.wheel = self.root / 'dbt_redis_adbc-0.2.0-py3-none-any.whl'
        self.source = self.root / 'dbt_redis_adbc-0.2.0.tar.gz'
        self.metadata = b'Name: dbt-redis-adbc\nVersion: 0.2.0\n'
        with zipfile.ZipFile(self.wheel, 'w') as archive:
            archive.writestr('dbt_redis_adbc-0.2.0.dist-info/METADATA', self.metadata)
        with tarfile.open(self.source, 'w:gz') as archive:
            entry = tarfile.TarInfo('dbt_redis_adbc-0.2.0/PKG-INFO')
            entry.size = len(self.metadata)
            archive.addfile(entry, io.BytesIO(self.metadata))
        self.hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (self.wheel, self.source)}
        (self.root / 'SHA256SUMS').write_text(''.join(
            f'{digest}  {name}\n' for name, digest in self.hashes.items()))

    def test_checksums_and_package_versions_must_match(self):
        self.assertEqual(verify_release.verify('v0.2.0', self.root), self.hashes)
        self.wheel.write_bytes(b'altered wheel')
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            verify_release.verify('v0.2.0', self.root)

    def test_extra_files_and_duplicate_checksums_are_rejected(self):
        extra = self.root / 'unexpected.whl'
        extra.touch()
        with self.assertRaisesRegex(ValueError, 'exactly'):
            verify_release.verify('v0.2.0', self.root)
        extra.unlink()
        manifest = self.root / 'SHA256SUMS'
        manifest.write_text(manifest.read_text() * 2)
        with self.assertRaisesRegex(ValueError, 'Unexpected checksum'):
            verify_release.verify('v0.2.0', self.root)

    def test_wrong_package_identity_is_rejected_even_with_valid_hashes(self):
        with zipfile.ZipFile(self.wheel, 'w') as archive:
            archive.writestr('dbt_redis_adbc-0.2.0.dist-info/METADATA',
                             self.metadata.replace(b'0.2.0', b'0.2.1'))
        self.hashes[self.wheel.name] = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        (self.root / 'SHA256SUMS').write_text(''.join(
            f'{digest}  {name}\n' for name, digest in self.hashes.items()))
        with self.assertRaisesRegex(ValueError, 'identity'):
            verify_release.verify('v0.2.0', self.root)

    def test_pypi_retry_cannot_hide_different_uploaded_files(self):
        release = {'info': {'version': '0.2.0'}, 'urls': [
            {'filename': name, 'digests': {'sha256': digest}}
            for name, digest in self.hashes.items()]}
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps(release)))
        response.__exit__ = Mock(return_value=False)
        not_found = urllib.error.HTTPError('https://pypi.org', 404, 'pending', {}, None)
        with patch.object(verify_release.urllib.request, 'urlopen', side_effect=[not_found, response]), \
             patch.object(verify_release.time, 'sleep'):
            verify_release.verify_pypi('v0.2.0', self.hashes)
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps(release)))
        with patch.object(verify_release.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'PyPI distributions'):
                verify_release.verify_pypi('v0.2.0', {self.wheel.name: 'different'})

    def test_installed_package_must_be_the_built_wheel_and_not_shadowed(self):
        module = self.root / 'site-packages/dbt/adapters/redis_adbc/__init__.py'
        installed = Mock(version='0.2.0')
        installed.locate_file.return_value = module
        installed.read_text.return_value = json.dumps({'url': self.wheel.as_uri()})
        check_wheel_install.check_install(self.wheel, installed, module, '0.2.0')
        with self.assertRaisesRegex(ValueError, 'shadowed'):
            check_wheel_install.check_install(self.wheel, installed, self.root / 'checkout.py', '0.2.0')
        installed.read_text.return_value = json.dumps({
            'url': self.root.as_uri(), 'dir_info': {'editable': True}})
        with self.assertRaisesRegex(ValueError, 'exact release wheel'):
            check_wheel_install.check_install(self.wheel, installed, module, '0.2.0')

    def test_source_metadata_and_runtime_version_must_match_tag(self):
        (self.root / 'pyproject.toml').write_text('[project]\nname="dbt-redis-adbc"\nversion="0.2.0"\n')
        runtime = self.root / 'dbt/adapters/redis_adbc/__version__.py'
        runtime.parent.mkdir(parents=True)
        runtime.write_text('version = "0.2.0"\n')
        verify_release.verify_source('v0.2.0', self.root)
        runtime.write_text('version = "0.1.0"\n')
        with self.assertRaisesRegex(ValueError, 'versions'):
            verify_release.verify_source('v0.2.0', self.root)
        with self.assertRaisesRegex(ValueError, 'stable release tag'):
            verify_release.verify_source('main', self.root)


if __name__ == '__main__':
    unittest.main()
