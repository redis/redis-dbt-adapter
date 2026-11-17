"""Resource-probe regressions for paginated Enterprise SCAN replies."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flight_cancellation import Resources, decode
from publication_proxy import read_command


class ResourceTests(unittest.TestCase):
    def test_decodes_paged_scan_and_live_lease_records(self):
        reply = b'*2\r\n$15\r\n281474976710656\r\n*1\r\n$3\r\nkey\r\n'
        self.assertEqual(decode(io.BytesIO(reply)), [b'281474976710656', [b'key']])
        resources = Resources.__new__(Resources)
        resources.call = MagicMock(side_effect=[
            [b'281474976710656', [b'key']], b'{"active":1}', [b'0', []]])
        self.assertEqual(resources.leases(), {b'key': {'active': 1}})
        resources.call.assert_any_call('SCAN', b'281474976710656', 'MATCH', 'arrowflight:query:*', 'COUNT', 100)

    def test_cursor_bytes_are_sent_as_decimal_without_python_repr(self):
        resources = Resources.__new__(Resources)
        resources.socket = MagicMock()
        resources.stream = io.BytesIO(b'+OK\r\n')
        resources.call('SCAN', b'281474976710656')
        frame = resources.socket.sendall.call_args.args[0]
        self.assertEqual(read_command(io.BytesIO(frame)), [b'SCAN', b'281474976710656'])


if __name__ == '__main__':
    unittest.main()
