"""Check release checksums and package identity before granting a publishing token."""
import email
import hashlib
from pathlib import Path
import re
import sys
import tarfile
import zipfile


def verify(tag, directory):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Expected a stable release tag such as v0.2.0')
    version = tag[1:]
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


if __name__ == '__main__':
    verify(sys.argv[1], Path(sys.argv[2]))
