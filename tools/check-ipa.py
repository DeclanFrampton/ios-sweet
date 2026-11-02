#!/usr/bin/env python3
"""Read-only preflight for IPA packages targeting the iOS Sweet QEMU guest.

Checks archive safety, app metadata, executable platform and signing state.
Does NOT copy an IPA into iOS, sign code, or claim installation success.
"""

import argparse
import json
from pathlib import Path
import plistlib
import struct
import zipfile

MAX_MEMBERS = 100000
MAX_UNCOMPRESSED = 2 * 1024**3
MAX_PLIST = 2 * 1024**2
MAX_EXECUTABLE = 256 * 1024**2
MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_EXECUTE = 2
LC_CODE_SIGNATURE = 0x1D
LC_BUILD_VERSION = 0x32
PLATFORMS = {2: 'iOS device', 7: 'iOS Simulator'}


def version_tuple(version):
    return tuple(int(piece) for piece in str(version).split('.') if piece.isdigit())


def macho_metadata(data):
    if len(data) < 32:
        raise ValueError('Executable too small for a 64-bit Mach-O header')
    magic, cpu, _subtype, kind, ncmds, cmdbytes, _flags, _reserved = struct.unpack_from('<8I', data)
    if magic != MH_MAGIC_64 or ncmds > 4096 or 32 + cmdbytes > len(data):
        raise ValueError('Unsupported or malformed 64-bit Mach-O executable')
    offset, signed, platform = 32, False, None
    for _ in range(ncmds):
        if offset + 8 > 32 + cmdbytes:
            raise ValueError('Truncated Mach-O load commands')
        command, size = struct.unpack_from('<II', data, offset)
        if size < 8 or offset + size > 32 + cmdbytes:
            raise ValueError('Invalid Mach-O load command size')
        if command == LC_CODE_SIGNATURE:
            if size < 16:
                raise ValueError('Invalid Mach-O code-signature command')
            start, length = struct.unpack_from('<II', data, offset + 8)
            signed = length > 0 and start >= 32 + cmdbytes and start + length <= len(data)
        if command == LC_BUILD_VERSION:
            if size < 24:
                raise ValueError('Invalid Mach-O platform command')
            platform = struct.unpack_from('<I', data, offset + 8)[0]
        offset += size
    return {'architecture': 'arm64' if cpu == CPU_TYPE_ARM64 else f'cpu_0x{cpu:x}',
            'executable': kind == MH_EXECUTE, 'target_platform': PLATFORMS.get(platform, 'unknown'),
            'has_macho_code_signature': signed}


def inspect(path, guest_ios='16.7.16'):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or len(members) > MAX_MEMBERS:
            raise ValueError('Invalid IPA member count')
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED:
            raise ValueError('IPA exceeds safe uncompressed size')
        names = set()
        for member in members:
            name = member.filename
            parts = name.replace('\\', '/').split('/')
            if name.startswith('/') or '\\' in name or '..' in parts or name in names:
                raise ValueError('IPA contains unsafe or duplicate ZIP member paths')
            if member.flag_bits & 1:
                raise ValueError('Encrypted IPA ZIP members are unsupported')
            names.add(name)
        if archive.testzip() is not None:
            raise ValueError('IPA ZIP integrity check failed')
        apps = sorted({name.removesuffix('Info.plist') for name in names
                       if name.startswith('Payload/') and name.count('/') == 2
                       and name.endswith('.app/Info.plist')})
        if len(apps) != 1:
            raise ValueError('Expected exactly one Payload/*.app/Info.plist')
        app = apps[0]
        info_entry = archive.getinfo(app + 'Info.plist')
        if info_entry.file_size > MAX_PLIST:
            raise ValueError('Unexpectedly large Info.plist')
        info = plistlib.loads(archive.read(info_entry))
        executable = info.get('CFBundleExecutable')
        identifier = info.get('CFBundleIdentifier')
        if not isinstance(executable, str) or '/' in executable or '\\' in executable or not executable:
            raise ValueError('Invalid app executable name')
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError('Missing CFBundleIdentifier')
        binary_path = app + executable
        if binary_path not in names:
            raise ValueError('App executable missing from IPA')
        if archive.getinfo(binary_path).file_size > MAX_EXECUTABLE:
            raise ValueError('App executable exceeds safe inspection limit')
        binary = archive.read(binary_path)
        executable_info = macho_metadata(binary)
        minimum = info.get('MinimumOSVersion', 'unknown')
        supported_version = (version_tuple(minimum) <= version_tuple(guest_ios)) if version_tuple(minimum) else None
        provision = app + 'embedded.mobileprovision' in names
        resources = app + '_CodeSignature/CodeResources' in names
        required_structure_present = (executable_info['architecture'] == 'arm64'
                                and executable_info['executable']
                                and executable_info['target_platform'] == 'iOS device'
                                and supported_version is True
                                and executable_info['has_macho_code_signature']
                                and resources)
        return {
            'archive_integrity': 'passed', 'bundle_id': identifier,
            'app_name': info.get('CFBundleDisplayName', info.get('CFBundleName')),
            'minimum_ios': minimum, 'guest_ios': guest_ios,
            'minimum_ios_compatible': supported_version,
            'mach_o': executable_info,
            'code_signature_resources': resources,
            'embedded_provisioning': provision,
            # A load command is not cryptographic verification, and a
            # provisioning profile is not always necessary for every
            # distribution method. Neither implies this emulator can install.
            'standard_install_prerequisite_structure': (
                'present_but_cryptographic_signature_unverified'
                if required_structure_present else 'missing_required_components'),
            'cryptographic_signature_verified': False,
            'installed_on_guest': False,
            'installation_transport': 'not_checked_by_this_tool',
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ipa', type=Path)
    args = parser.parse_args()
    if not args.ipa.is_file():
        parser.error('IPA file does not exist')
    print(json.dumps(inspect(args.ipa), indent=2))


if __name__ == '__main__':
    main()
