#!/usr/bin/env python3
"""Authenticated localhost client for the isolated iOS Sweet guest agent.

Only fixed status, identity, apps, register and launch operations are exposed.
The temporary QEMU forwarding rule is removed even when an operation fails.
The config file is private, contains a capability token and must stay ignored.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@contextmanager
def forwarding(qmp_port=4444):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    with socket.create_connection(('127.0.0.1', qmp_port), 5) as monitor:
        monitor.settimeout(8)
        f = monitor.makefile('rwb')
        greeting = json.loads(f.readline())
        if 'QMP' not in greeting:
            raise ValueError('The local service is not QEMU QMP')

        def call(command, arguments=None):
            request = {'execute': command}
            if arguments is not None:
                request['arguments'] = arguments
            f.write(json.dumps(request).encode() + b'\n'); f.flush()
            while True:
                line = f.readline()
                if not line:
                    raise ConnectionError('QMP disconnected')
                result = json.loads(line)
                if 'error' in result:
                    raise RuntimeError('QMP rejected operation: ' + str(result['error']))
                if 'return' in result:
                    return result['return']

        call('qmp_capabilities')
        rule = f'tcp:127.0.0.1:{port}-10.0.2.15:49160'
        added = call('human-monitor-command', {'command-line': 'hostfwd_add sweetnet ' + rule})
        if added.strip():
            raise RuntimeError('QEMU refused temporary local bridge forwarding')
        try:
            yield port
        finally:
            removed = call('human-monitor-command', {
                'command-line': f'hostfwd_remove sweetnet tcp:127.0.0.1:{port}'})
            # HMP returns a non-empty confirmation when removal succeeds.
            # Do not mask the original HTTP failure with a false cleanup error.
            if any(word in removed.lower() for word in ('error', 'not found', 'could not')):
                raise RuntimeError('Could not remove temporary bridge forwarding')


def invoke(config, action, qmp_port=4444, timeout=20):
    if action not in ('status', 'identity', 'apps', 'register', 'launch', 'processes', 'staged', 'operation'):
        raise ValueError('Operation is not allowlisted')
    token = config.get('Token', '')
    if not re.fullmatch('[0-9a-f]{64}', token):
        raise ValueError('Expected a private 256-bit bridge capability')
    method = 'POST' if action in ('register', 'launch') else 'GET'
    with forwarding(qmp_port) as port:
        request = Request(f'http://127.0.0.1:{port}/v1/{action}', method=method,
                          data=b'' if method == 'POST' else None,
                          headers={'Authorization': 'Bearer ' + token})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read(1024 * 1024))
        except HTTPError as error:
            body = error.read(16384)
            raise RuntimeError(f'Guest returned HTTP {error.code}: {body.decode(errors="replace")}') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--qmp-port', type=int, default=4444)
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('action', choices=('status', 'identity', 'apps', 'register', 'launch', 'processes', 'staged', 'operation'))
    args = parser.parse_args()
    if not 1 <= args.qmp_port <= 65535 or not 1 <= args.timeout <= 60:
        parser.error('Invalid local port or deadline')
    try:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        result = invoke(config, args.action, args.qmp_port, args.timeout)
        print(json.dumps(result, indent=2))
        if 'error' in result or result.get('registrationReturned') is False or result.get('launchRequested') is False:
            raise SystemExit(2)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'operation': args.action, 'success': False,
                          'error': type(error).__name__, 'detail': str(error)}, indent=2))
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
