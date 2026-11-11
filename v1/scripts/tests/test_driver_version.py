"""Default downloads resolve a published release, with no stale-pin fallback."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "resolve_driver_version.sh"


class DriverVersionTests(unittest.TestCase):
    def resolve(self, gh, curl):
        with tempfile.TemporaryDirectory() as directory:
            for name, body in [("gh", gh), ("curl", curl)]:
                command = Path(directory) / name
                command.write_text("#!/bin/sh\n" + body + "\n")
                command.chmod(0o700)
            env = {k: v for k, v in os.environ.items() if k not in ("DRIVER_VERSION", "DRIVER_GH_REPO")}
            env["PATH"] = directory + os.pathsep + env["PATH"]
            return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_authenticated_lookup_uses_latest_release(self):
        result = self.resolve(
            'if [ "$1" = auth ]; then exit 0; fi\n'
            '[ "$2" = repos/redis/redis-adbc-driver/releases/latest ] || exit 1\n'
            'echo \'{"tag_name":"v99.1.2"}\'', "exit 99",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "v99.1.2")

    def test_public_lookup_without_authentication(self):
        result = self.resolve("exit 1", 'echo \'{"tag_name":"v99.2.3"}\'')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "v99.2.3")

    def test_lookup_failure_never_falls_back_to_a_pin(self):
        result = self.resolve("exit 1", "exit 22")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
