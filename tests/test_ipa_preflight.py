"""Synthetic IPA preflight validation: no private apps needed."""

import importlib.util
import plistlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'check-ipa.py'
spec = importlib.util.spec_from_file_location('ipa_preflight_test', SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def make_macho(signed=False, platform=2):
    commands = [struct.pack('<6I', 0x32, 24, platform, 0, 0, 0)]
    if signed:
        commands.append(struct.pack('<4I', 0x1d, 16, 72, 16))
    header = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, len(commands),
                         sum(map(len, commands)), 0, 0)
    blob = header + b''.join(commands)
    return blob.ljust(72, b'\0') + (b'X' * 16 if signed else b'')


class IPAInspectionTests(unittest.TestCase):
    def write_ipa(self, path, signed=False, platform=2, extra=None):
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Payload/Test.app/Info.plist', plistlib.dumps({
                'CFBundleIdentifier': 'example.test', 'CFBundleExecutable': 'Test',
                'MinimumOSVersion': '15.1'}))
            z.writestr('Payload/Test.app/Test', make_macho(signed, platform))
            if signed:
                z.writestr('Payload/Test.app/_CodeSignature/CodeResources', 'sample')
            if extra:
                z.writestr(extra, b'x')

    def test_unsigned_arm64_device_app_is_not_install_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            ipa = Path(folder) / 'sample.ipa'
            self.write_ipa(ipa)
            report = module.inspect(ipa)
            self.assertEqual(report['bundle_id'], 'example.test')
            self.assertEqual(report['mach_o']['target_platform'], 'iOS device')
            self.assertEqual(report['standard_install_prerequisite_structure'],
                             'missing_required_components')
            self.assertFalse(report['installed_on_guest'])

    def test_signed_and_compatible_reports_preflight_only(self):
        with tempfile.TemporaryDirectory() as folder:
            ipa = Path(folder) / 'signed.ipa'
            self.write_ipa(ipa, signed=True)
            self.assertEqual(module.inspect(ipa)['standard_install_prerequisite_structure'],
                             'present_but_cryptographic_signature_unverified')
            self.assertFalse(module.inspect(ipa)['cryptographic_signature_verified'])
            self.assertFalse(module.inspect(ipa)['installed_on_guest'])

    def test_simulator_platform_is_not_real_device_platform(self):
        with tempfile.TemporaryDirectory() as folder:
            ipa = Path(folder) / 'simulator.ipa'
            self.write_ipa(ipa, signed=True, platform=7)
            report = module.inspect(ipa)
            self.assertEqual(report['mach_o']['target_platform'], 'iOS Simulator')
            self.assertEqual(report['standard_install_prerequisite_structure'],
                             'missing_required_components')

    def test_reject_unsafe_zip_path(self):
        with tempfile.TemporaryDirectory() as folder:
            ipa = Path(folder) / 'path.ipa'
            self.write_ipa(ipa, extra='../outside.txt')
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                module.inspect(ipa)


if __name__ == '__main__':
    unittest.main()
