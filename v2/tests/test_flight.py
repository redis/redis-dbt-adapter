"""Flight runner boundary checks; live protocol coverage lives in the Rust engine."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke import SmokeError, configure_transport


class FlightProfileTests(unittest.TestCase):
    def test_uses_separate_client_profile_and_never_copies_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            library = project / "client.so"
            library.touch()
            ca = project / "ca.pem"
            ca.touch()
            env = dict(FLIGHT_SQL_DRIVER=str(library), FLIGHT_SQL_TLS_CA_FILE=str(ca),
                       FLIGHT_SQL_URI="grpc+tls://localhost:8815", FLIGHT_SQL_USERNAME="alice",
                       FLIGHT_SQL_PASSWORD="flight-secret")
            configure_transport(project, env, "flightsql")
            profile = (project / "profiles.yml").read_text()
            self.assertIn("transport: flightsql", profile)
            self.assertNotIn("adbc.redis.", profile)
            self.assertNotIn("flight-secret", profile)

    def test_rejects_missing_configuration_plaintext_and_uri_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            library = project / "client.so"
            library.touch()
            base = dict(FLIGHT_SQL_DRIVER=str(library), FLIGHT_SQL_TLS_CA_FILE=str(library),
                        FLIGHT_SQL_URI="grpc+tls://localhost:8815", FLIGHT_SQL_USERNAME="alice",
                        FLIGHT_SQL_PASSWORD="secret-value")
            bad = [{**base, key: ""} for key in base]
            bad += [{**base, "FLIGHT_SQL_URI": uri} for uri in
                    ("grpc://localhost:8815", "grpc+tls://alice:secret-value@localhost:8815",
                     "grpc+tls://localhost:8815?password=secret-value")]
            for env in bad:
                with self.assertRaises(SmokeError) as error:
                    configure_transport(project, env, "flightsql")
                self.assertNotIn("secret-value", str(error.exception))
            self.assertFalse((project / "profiles.yml").exists())


if __name__ == "__main__":
    unittest.main()
