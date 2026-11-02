#!/usr/bin/env python3
"""Read-only lockdown identity probe against a running iOS Sweet guest.

Temporarily forwards 127.0.0.1:<free-port> through QEMU slirp to the guest's
lockdown TCP service. Queries the service; never fabricates an Apple UDID,
changes the iOS disk, or assumes a synthetic ID is Apple-registerable.

NOTE: Apple's lockdown service is normally reached over an Apple USB/pairing
transport, NOT necessarily via TCP/62078. A failed TCP probe does not mean
lockdownd isn't running; it means this particular bridge is not working.
"""

import argparse
import json
import plistlib
import socket
import struct
import sys
from contextlib import contextmanager
from pathlib import Path


MAX_PLIST_SIZE = 1024 * 1024
GUEST_ADDRESS = '10.0.2.15'
GUEST_PORT = 62078


def recv_exact(sock, length):
    pieces = bytearray()
    while len(pieces) < length:
        data = sock.recv(length-len(pieces))
        if not data:
            raise ConnectionError('Lockdown closed the connection')
        pieces.extend(data)
    return bytes(pieces)


def exchange(sock, data):
    payload = plistlib.dumps(data, fmt=plistlib.FMT_XML)
    sock.sendall(struct.pack('>I', len(payload)) + payload)
    length = struct.unpack('>I', recv_exact(sock, 4))[0]
    if not 0 < length <= MAX_PLIST_SIZE:
        raise ValueError('Lockdown response is not a bounded plist')
    result = plistlib.loads(recv_exact(sock, length))
    if not isinstance(result, dict):
        raise ValueError('Lockdown reply must be a dictionary')
    return result


def qmp_command(socket_conn, name, arguments=None):
    request = {'execute': name}
    if arguments is not None:
        request['arguments'] = arguments
    socket_conn.sendall(json.dumps(request).encode() + b'\r\n')
    pending = b''
    while True:
        pending += socket_conn.recv(65536)
        if not pending:
            raise ConnectionError('QMP disconnected')
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            if not line.strip():
                continue
            reply = json.loads(line)
            if 'error' in reply:
                raise RuntimeError(f'QMP command {name} failed: {reply["error"]}')
            if 'return' in reply:
                return reply['return']


@contextmanager
def forwarded_lockdown(qmp_port, local_port):
    """QMP host forward is removed in finally, including timeout/failure."""
    with socket.create_connection(('127.0.0.1', qmp_port), 5) as monitor:
        monitor.settimeout(8)
        greeting = monitor.recv(8192)
        if not greeting or b'QMP' not in greeting:
            raise RuntimeError('Unexpected QMP greeting')
        qmp_command(monitor, 'qmp_capabilities')
        fwd = f'tcp:127.0.0.1:{local_port}-{GUEST_ADDRESS}:{GUEST_PORT}'
        added = False
        try:
            response = qmp_command(monitor, 'human-monitor-command',
                                   {'command-line': f'hostfwd_add sweetnet {fwd}'})
            if not isinstance(response, str) or 'error' in response.lower():
                raise RuntimeError(f'QEMU host forwarding failed: {response!r}')
            added = True
            yield ('127.0.0.1', local_port)
        finally:
            if added:
                reply = qmp_command(monitor, 'human-monitor-command',
                                    {'command-line': f'hostfwd_remove sweetnet tcp:127.0.0.1:{local_port}'})
                if not isinstance(reply, str) or 'error' in reply.lower():
                    raise RuntimeError('Temporary lockdown forward could not be removed')


def probe(qmp_port=4444, timeout=6):
    report = {'guest': 'iOS Sweet ARM64 QEMU', 'service': 'lockdown',
              'transport': 'temporary_QEMU_tcp_62078', 'responsive': False,
              'udid_source': 'not_available', 'udid': None,
              'apple_developer_registration_verified': False,
              'install_service_verified': False}
    # This socket is closed before installing the forward; on a single-user
    # localhost-only diagnostic the race is minimal and all listeners remain
    # loopback, never publicly exposed on a LAN.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp:
        temp.bind(('127.0.0.1', 0))
        local_port = temp.getsockname()[1]
    with forwarded_lockdown(qmp_port, local_port) as address:
        try:
            with socket.create_connection(address, 3) as guest:
                guest.settimeout(timeout)
                initial = exchange(guest, {'Label': 'iOS-Sweet-Identity-Probe',
                                           'Request': 'QueryType'})
                if initial.get('Type') != 'com.apple.mobile.lockdown':
                    raise ValueError('Guest did not identify as lockdown')
                report['responsive'] = True
                identity = exchange(guest, {'Label': 'iOS-Sweet-Identity-Probe',
                                             'Request': 'GetValue', 'Key': 'UniqueDeviceID'})
                value = identity.get('Value')
                if isinstance(value, str) and 16 <= len(value) <= 80:
                    report['udid'] = value
                    report['udid_source'] = 'guest_lockdown_GetValue'
                else:
                    report['udid_source'] = 'lockdown_did_not_return_udid'
        except (OSError, ValueError, ConnectionError, plistlib.InvalidFileException) as error:
            report['reason'] = type(error).__name__
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qmp-port', type=int, default=4444)
    parser.add_argument('--timeout', type=float, default=6)
    args = parser.parse_args()
    if not 1 <= args.qmp_port <= 65535 or not 1 <= args.timeout <= 20:
        parser.error('Invalid QMP port or timeout')
    result = probe(args.qmp_port, args.timeout)
    print(json.dumps(result, indent=2))
    # A diagnostic with no source-verified guest UDID must not silently look
    # successful to a calling signing script or deployment pipeline.
    if not result['udid']:
        sys.exit(2)


if __name__ == '__main__':
    main()
