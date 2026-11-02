"""Byte-exact UDIF transport regressions, using synthetic files only."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
import runtime_setup

spec=importlib.util.spec_from_file_location('test_appliance_prepare',ROOT/'desktop/appliance/prepare.py')
guest=importlib.util.module_from_spec(spec);spec.loader.exec_module(guest)


def dmg():
    # A DMG's EOF is deliberately not aligned to a 512-byte virtual sector.
    return b'bvxn'+b'compressed-placeholder'*33+b'koly'+b'\0'*508


def apfs():
    return b'\0'*32+b'NXSB'+b'\0'*(4096-36)


class FirmwareTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def metadata(self,data):
        return {'kind':'udif','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}

    def test_host_distinguishes_compressed_udif_and_raw_apfs(self):
        files={}
        for name,data in [('os',dmg()),('sysos',apfs()),('appos',apfs())]:
            p=self.root/(name+'.dmg');p.write_bytes(data);files[name]=p
        meta=runtime_setup.firmware_metadata(files,Mock())
        self.assertEqual(meta['os']['kind'],'udif')
        self.assertEqual(meta['os']['size'],len(dmg()))
        self.assertNotEqual(meta['os']['size']%512,0)
        self.assertEqual(meta['sysos']['kind'],'apfs')
        guest.validate_image_metadata(meta)

    def test_sector_padding_is_not_copied_and_dmg_trailer_is_preserved(self):
        original=dmg();padded=original+b'\0'*((-len(original))%512)
        self.assertNotEqual(padded[-512:-508],b'koly')
        source=self.root/'block';source.write_bytes(padded)
        dest=self.root/'exact.dmg'
        with redirect_stdout(io.StringIO()):guest.copy_exact_firmware(source,dest,self.metadata(original))
        self.assertEqual(dest.read_bytes(),original)
        self.assertEqual(dest.read_bytes()[-512:-508],b'koly')
        self.assertEqual(source.read_bytes(),padded)

    def test_wrong_digest_does_not_count_as_verified(self):
        source=self.root/'block';source.write_bytes(dmg());meta=self.metadata(dmg());meta['sha256']='0'*64
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'SHA-256 mismatch'):
            guest.copy_exact_firmware(source,self.root/'bad.dmg',meta)

    def test_truncated_source_fails_closed(self):
        source=self.root/'block';source.write_bytes(dmg()[:-12])
        with self.assertRaisesRegex(RuntimeError,'before its recorded file length'):
            guest.copy_exact_firmware(source,self.root/'truncated.dmg',self.metadata(dmg()))

    def test_original_file_or_previous_destination_is_never_overwritten(self):
        source=self.root/'block';source.write_bytes(dmg());dest=self.root/'existing';dest.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):guest.copy_exact_firmware(source,dest,self.metadata(dmg()))
        self.assertEqual(dest.read_bytes(),b'keep')
        self.assertEqual(source.read_bytes(),dmg())

    def test_missing_or_damaged_metadata_is_rejected_before_formatting(self):
        for invalid in (None,{}, {'os':{'size':1}}):
            with self.assertRaises(RuntimeError):guest.validate_image_metadata(invalid)
        valid={n:self.metadata(dmg()) for n in ('os','sysos','appos')}
        valid['os']['size']=16*1024**3+1
        with self.assertRaises(RuntimeError):guest.validate_image_metadata(valid)

    def test_unknown_firmware_is_rejected_by_host_before_qemu_start(self):
        files={}
        for n in ('os','sysos','appos'):
            p=self.root/(n+'.dmg');p.write_bytes(b'bad'*1024);files[n]=p
        with self.assertRaisesRegex(ValueError,'Unsupported or damaged'):
            runtime_setup.firmware_metadata(files,Mock())

    def test_compressed_scratch_is_removed_before_next_component(self):
        import ast
        src=(ROOT/'desktop/appliance/prepare.py').read_text()
        self.assertIn('scratch.unlink()',src)
        tree=ast.parse(src);populate=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='populate')
        mainloop=next(n for n in populate.body if isinstance(n,ast.For))
        text=ast.get_source_segment(src,mainloop)
        self.assertLess(text.index("run('umount'"),text.index('scratch.unlink()'))


if __name__=='__main__':unittest.main()
