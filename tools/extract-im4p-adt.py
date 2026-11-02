#!/usr/bin/env python3
"""Extract d22ap.adt from the user's own Apple IMG4 DeviceTree IM4P.

The IM4P envelope is ASN.1 DER. A 'bvx2' payload is standard LZFSE; the
external lzfse CLI is compiled from the open-source lzfse submodule of
sgan81/apfs-fuse. No private Apple binary is committed to this repository.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def tlv(blob, offset):
    if offset < 0 or offset + 2 > len(blob):
        raise ValueError('Incomplete IM4P DER item')
    tag = blob[offset]
    offset += 1
    length = blob[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7f
        if count == 0 or count > 4 or offset + count > len(blob):
            raise ValueError('Bad DER length prefix')
        length = int.from_bytes(blob[offset:offset + count], 'big')
        offset += count
    end = offset + length
    if end > len(blob):
        raise ValueError('DER item extends beyond IM4P file')
    return tag, blob[offset:end], end


def extract(path, destination, lzfse):
    if not 16 <= path.stat().st_size <= 1024*1024:
        raise ValueError('Unexpected DeviceTree IM4P size')
    blob = path.read_bytes()
    tag, outer, end = tlv(blob, 0)
    if tag != 0x30 or end != len(blob):
        raise ValueError('Not a complete DER SEQUENCE')
    parts = []
    offset = 0
    while offset < len(outer) and len(parts) < 4:
        t, payload, offset = tlv(outer, offset)
        parts.append((t, payload))
    if len(parts) != 4 or parts[0] != (0x16, b'IM4P') or (
            parts[1] != (0x16, b'dtre')) or parts[3][0] != 0x04:
        raise ValueError('Not an Apple DeviceTree (dtre) IM4P')
    while offset < len(outer):
        t, _extra, offset = tlv(outer, offset)
        if t == 0x04:
            raise ValueError('Encrypted DeviceTree payloads are not supported')
    payload = parts[3][1]
    if not payload.startswith(b'bvx2'):
        raise ValueError('Unsupported DeviceTree compression; expected LZFSE bvx2')
    if destination.exists():
        raise FileExistsError('Refusing to overwrite DeviceTree')
    created=False
    try:
        # Binary pipes also support Windows usernames containing Unicode; the
        # decoder never has to open a narrow-character filesystem path.
        result = subprocess.run([lzfse, '-decode'], input=payload,
                                capture_output=True, check=True, timeout=60,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not 16384 <= len(result.stdout) <= 1024*1024:
            raise ValueError('Decompressed Apple DeviceTree has unexpected size')
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import adt
        root, _ = adt.parse(result.stdout)
        product = [n for n in root.children if any(
            name == 'name' and value == b'product\0'
            for name, _flags, value in n.props)]
        if not product:
            raise ValueError('Missing iPhone X /product node')
        with destination.open('xb') as out:
            created=True
            out.write(result.stdout)
    except BaseException:
        if created:destination.unlink(missing_ok=True)
        raise
    print(f'VERIFIED_D22AP_ADT={destination} BYTES={destination.stat().st_size}',
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('im4p', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--lzfse', default='/usr/local/bin/lzfse')
    args = parser.parse_args()
    extract(args.im4p, args.output, args.lzfse)


if __name__ == '__main__':
    main()
