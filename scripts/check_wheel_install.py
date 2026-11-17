"""Fail release validation if dbt is importing an editable adapter or another wheel."""
import email
from importlib.metadata import distribution
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse
import zipfile


def check_install(wheel, installed, module_path, runtime_version):
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        if len(names) != 1:
            raise ValueError('Expected one wheel metadata record')
        package = email.message_from_bytes(archive.read(names[0]))
    direct = json.loads(installed.read_text('direct_url.json') or '{}')
    origin = urlparse(direct.get('url', ''))
    if (direct.get('dir_info', {}).get('editable') or origin.scheme != 'file'
            or Path(unquote(origin.path)).resolve() != wheel.resolve()):
        raise ValueError('Adapter must be installed from the exact release wheel')
    if (package['Name'] != 'dbt-redis-adbc' or installed.version != package['Version']
            or runtime_version != package['Version']):
        raise ValueError('Installed adapter version differs from the built wheel')
    expected_module = installed.locate_file('dbt/adapters/redis_adbc/__init__.py')
    if Path(module_path).resolve() != Path(expected_module).resolve():
        raise ValueError('Imported adapter is shadowed by a source checkout')
    print(f'Verified installed release wheel: {wheel.name} ({module_path})')


if __name__ == '__main__':
    import dbt.adapters.redis_adbc as adapter
    from dbt.adapters.redis_adbc.__version__ import version

    wheels = list(Path(sys.argv[1]).glob('*.whl'))
    if len(wheels) != 1:
        raise ValueError('Expected exactly one release wheel')
    check_install(wheels[0], distribution('dbt-redis-adbc'), adapter.__file__, version)
