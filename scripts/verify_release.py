"""Check release checksums and package identity before granting a publishing token."""
import argparse
import ast
import email
import hashlib
import json
from pathlib import Path
import re
import tarfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile


def release_version(tag):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Expected a stable release tag such as v0.2.0')
    return tag[1:]


def verify_source(tag, directory):
    version = release_version(tag)
    project = tomllib.loads((directory / 'pyproject.toml').read_text())['project']
    runtime = ast.parse((directory / 'dbt/adapters/redis_adbc/__version__.py').read_text())
    versions = [ast.literal_eval(node.value) for node in runtime.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'version'
                        for target in node.targets)]
    if project['name'] != 'dbt-redis-adbc' or project['version'] != version or versions != [version]:
        raise ValueError('Tagged package and adapter runtime versions must match the tag')
    print(f'Verified tagged source version {version}')


def verify(tag, directory):
    version = release_version(tag)
    stem = f'dbt_redis_adbc-{version}'
    wheel = f'{stem}-py3-none-any.whl'
    source = f'{stem}.tar.gz'
    expected = {wheel, source}
    if {p.name for p in directory.iterdir()} != expected | {'SHA256SUMS'}:
        raise ValueError('Release must contain exactly the expected wheel, sdist, and SHA256SUMS')
    checksums = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match or match[2] not in expected or match[2] in checksums:
            raise ValueError('Unexpected checksum entry')
        checksums[match[2]] = match[1]
    if set(checksums) != expected:
        raise ValueError('Missing release checksum')
    for name, digest in checksums.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Checksum mismatch: {name}')
    with zipfile.ZipFile(directory / wheel) as archive:
        metadata = archive.read(f'{stem}.dist-info/METADATA')
    with tarfile.open(directory / source) as archive:
        metadata_file = archive.extractfile(f'dbt_redis_adbc-{version}/PKG-INFO')
        if metadata_file is None:
            raise ValueError('Source archive has no package metadata')
        source_metadata = metadata_file.read()
    for content in (metadata, source_metadata):
        package = email.message_from_bytes(content)
        if package['Name'] != 'dbt-redis-adbc' or package['Version'] != version:
            raise ValueError('Package identity does not match the release tag')
    print(f'Verified dbt-redis-adbc {version}: wheel, sdist, and SHA-256 checksums')
    return checksums


def verify_pypi(tag, checksums):
    version = release_version(tag)
    url = f'https://pypi.org/pypi/dbt-redis-adbc/{version}/json'
    for attempt in range(10):
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                release = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in {404, 502, 503, 504} or attempt == 9:
                raise
        except urllib.error.URLError:
            if attempt == 9:
                raise
        time.sleep(3)
    actual = {artifact['filename']: artifact['digests']['sha256']
              for artifact in release['urls']}
    if release['info']['version'] != version or actual != checksums:
        raise ValueError('PyPI distributions do not match the tested release artifacts')
    print(f'Verified PyPI version {version} and both distribution checksums')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('directory', type=Path, nargs='?')
    parser.add_argument('--source', type=Path, help='Check tagged source versions before building')
    parser.add_argument('--pypi', action='store_true', help='Also verify published PyPI hashes')
    args = parser.parse_args()
    if args.source:
        if args.directory or args.pypi:
            parser.error('--source cannot be combined with distributions or --pypi')
        verify_source(args.tag, args.source)
    elif args.directory:
        checksums = verify(args.tag, args.directory)
        if args.pypi:
            verify_pypi(args.tag, checksums)
    else:
        parser.error('Supply a distribution directory or --source')
