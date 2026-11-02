"""Read-only lockdown parser tests without a guest or Apple identifiers."""
import importlib.util
import io
from pathlib import Path
import plistlib
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'probe-ios-device-identity.py'
spec = importlib.util.spec_from_file_location('device_probe_test', SOURCE)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class SocketFixture:
    def __init__(self, packet):
        self.reply = io.BytesIO(packet)
        self.sent = None

    def sendall(self, data):
        self.sent = data

    def recv(self, length):
        return self.reply.read(min(5, length))


class DeviceIdentityTests(unittest.TestCase):
    def test_length_prefixed_lockdown_plist_exchange(self):
        expected = {'Type': 'com.apple.mobile.lockdown'}
        raw = plistlib.dumps(expected)
        socket = SocketFixture(struct.pack('>I', len(raw)) + raw)
        reply = probe.exchange(socket, {'Request': 'QueryType'})
        self.assertEqual(reply, expected)
        request_size = struct.unpack('>I', socket.sent[:4])[0]
        self.assertEqual(plistlib.loads(socket.sent[4:4+request_size]), {'Request': 'QueryType'})

    def test_rejects_unbounded_or_truncated_reply(self):
        with self.assertRaisesRegex(ValueError, 'bounded'):
            probe.exchange(SocketFixture(struct.pack('>I', 2000000)), {'Request': 'QueryType'})
        with self.assertRaises(ConnectionError):
            probe.exchange(SocketFixture(struct.pack('>I', 12) + b'hello'), {'Request': 'QueryType'})

    def test_local_forward_removed_after_unresponsive_lockdown(self):
        # Simulate QEMU monitor/HMP without contacting the real guest. Ensure
        # the cleanup command is issued even when client socket times out.
        mock_monitor = MagicMock()
        mock_monitor.__enter__.return_value = mock_monitor
        mock_monitor.recv.return_value = b'{"QMP": {}}\n'
        mock_guest = MagicMock()
        mock_guest.__enter__.return_value = mock_guest
        mock_guest.recv.side_effect = TimeoutError('guest is unresponsive')
        with patch.object(probe.socket, 'create_connection', side_effect=[mock_monitor, mock_guest]), \
                patch.object(probe, 'qmp_command', return_value='') as calls:
            # Reserve the local ephemeral port via a real local OS socket;
            # only the device connection itself is mocked.
            result = probe.probe(timeout=2)
        self.assertFalse(result['responsive'])
        self.assertIsNone(result['udid'])
        self.assertFalse(result['apple_developer_registration_verified'])
        monitor_calls = [call.args for call in calls.call_args_list]
        commands = [args[2]['command-line'] for args in monitor_calls
                    if len(args) >= 3 and args[1] == 'human-monitor-command']
        self.assertEqual(len(commands), 2)
        self.assertTrue(commands[0].startswith('hostfwd_add sweetnet tcp:127.0.0.1:'))
        self.assertTrue(commands[1].startswith('hostfwd_remove sweetnet tcp:127.0.0.1:'))


if __name__ == '__main__':
    unittest.main()
