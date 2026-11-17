"""Fault fixture regressions: only definite, sealed publication refusals."""
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publication_proxy import PublicationGate, command_frame, read_command, read_frame


def publication(workspace=b'one'):
    return [b'EVALSHA', b'digest', b'1', b'adbc:{meta}:snapshot:catalog', b'publish', b'base', workspace]


class PublicationGateTests(unittest.TestCase):
    def test_refuses_all_rebases_of_only_first_workspace(self):
        gate = PublicationGate()
        gate.arm()
        for _ in range(4):
            args = publication()
            self.assertTrue(gate.select(args))
            self.assertEqual(args[4], b'seal')
            self.assertEqual(gate.record(b':1\r\n'), b':0\r\n')
        self.assertFalse(gate.select(publication(b'fresh-retry')))
        receipt = gate.receipt()
        self.assertEqual(len(receipt['workspaces']), 1)
        self.assertEqual(receipt['refused_cas'], 4)
        self.assertEqual(receipt['passed_publications'], 1)

    def test_never_masks_unsuccessful_seal(self):
        gate = PublicationGate()
        for reply in (b'-ERR seal failed\r\n', b':0\r\n', b'$-1\r\n'):
            self.assertEqual(gate.record(reply), reply)
        self.assertEqual(gate.receipt()['refused_cas'], 0)

    def test_unarmed_and_unrelated_commands_are_untouched(self):
        gate = PublicationGate()
        for args in (publication(), [b'AUTH', b'alice', b'secret'],
                     [b'EVAL', b'script', b'1', b'other-key', b'publish', b'base', b'one']):
            before = args.copy()
            self.assertFalse(gate.select(args))
            self.assertEqual(args, before)

    def test_bound_and_skip_apply_to_workspaces_not_rebase_calls(self):
        gate = PublicationGate()
        gate.arm(limit=None, skip=1)
        self.assertFalse(gate.select(publication(b'committed-prefix')))
        for number in range(20):
            for _ in range(3):
                self.assertTrue(gate.select(publication(str(number).encode())))
        self.assertEqual(len(gate.receipt()['workspaces']), 20)
        self.assertEqual(sum(p['calls'] for p in gate.receipt()['workspaces']), 60)


class RESPTests(unittest.TestCase):
    def test_commands_roundtrip_binary_and_credentials_without_decoding(self):
        command = [b'auth', b'alice', b'password\r\n\x00\xff']
        self.assertEqual(read_command(io.BytesIO(command_frame(command))), command)

    def test_preserves_nested_resp3_frames_and_next_reply(self):
        frame = b'%2\r\n+name\r\n$3\r\na\x00b\r\n+values\r\n*3\r\n:1\r\n_\r\n!9\r\nERR error\r\n'
        stream = io.BytesIO(frame + b'+OK\r\n')
        self.assertEqual(read_frame(stream), frame)
        self.assertEqual(read_frame(stream), b'+OK\r\n')

    def test_rejects_truncated_frames_and_commands(self):
        for frame in (b'', b'+OK', b'$3\r\nx\r\n', b'*2\r\n:1\r\n'):
            with self.assertRaises(EOFError):
                read_frame(io.BytesIO(frame))
        with self.assertRaises(EOFError):
            read_command(io.BytesIO(b'*1\r\n$3\r\nx'))


if __name__ == '__main__':
    unittest.main()
