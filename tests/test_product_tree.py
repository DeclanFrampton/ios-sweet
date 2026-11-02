"""Fresh-clone product tree and boot-tool diagnostic tests, using synthetic data."""
import hashlib
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'tools')]
import adt
import mkadt
import product_tree


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


def synthetic_product(path):
    root=mkadt.node('device-tree',[],[mkadt.node('product',[
        ('artwork-display-gamut',b'P3\0'),('test-only-fixture',b'not Apple firmware\0')])])
    data=adt.serialize(root);Path(path).write_bytes(data);return data


class ProductTreeTests(unittest.TestCase):
    def test_explicit_product_works_without_developer_research_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'private product.adt';original=synthetic_product(source)
            with patch.object(mkadt,'D22AP_ADT',str(Path(folder)/'missing.adt')):
                tree=mkadt.build(qemu=True,highmem=True,qemu_cpus=2,qemu_srgb_display=True,product_adt=str(source))
            product=next(n for n in tree.children if n.name=='product')
            self.assertEqual(product.prop('artwork-display-gamut'),b'sRGB\0')
            self.assertEqual(next(n for n in tree.children if n.name=='cpus').children.__len__(),2)
            self.assertEqual(source.read_bytes(),original)

    def test_missing_product_still_fails_instead_of_disabling_validation(self):
        with self.assertRaisesRegex(ValueError,'Missing iPhone /product'):
            mkadt.build(qemu=True,qemu_srgb_display=True,product_adt='missing-private-product-for-test.adt')

    def test_source_tool_subprocess_uses_explicit_product_and_space_path(self):
        with tempfile.TemporaryDirectory(prefix='studio product ') as folder:
            source=Path(folder)/'product.adt';synthetic_product(source);output=Path(folder)/'qemu.adt'
            env=dict(os.environ,SWEET_QEMU_PRODUCT_ADT=str(Path(folder)/'no-research.adt'))
            p=subprocess.run([sys.executable,str(ROOT/'desktop/source_entry.py'),'--tool','mkadt.py',str(output),
                '--qemu','--highmem','--qemu-cpus=2','--qemu-srgb-display','--product-adt='+str(source)],
                env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(output.is_file())

    def test_known_tree_reuses_private_cache_without_network_or_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);target=home/'boot-assets/d22ap-20H392.adt';target.parent.mkdir()
            payload=b'synthetic-valid-tree';target.write_bytes(payload)
            with patch.object(product_tree,'ADT_BYTES',len(payload)),patch.object(product_tree,'ADT_SHA256',hashlib.sha256(payload).hexdigest()),patch.object(product_tree,'load') as fetch:
                self.assertEqual(product_tree.ensure(home,ROOT,lambda _:None),target.resolve())
                fetch.assert_not_called()

    def test_unknown_existing_tree_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);p=home/'boot-assets/d22ap-20H392.adt';p.parent.mkdir();p.write_bytes(b'keep-existing-data')
            with self.assertRaisesRegex(ValueError,'not overwritten'):product_tree.ensure(home,ROOT,lambda _:None)
            self.assertEqual(p.read_bytes(),b'keep-existing-data')

    def test_production_studio_passes_and_records_private_tree(self):
        text=(ROOT/'desktop/studio.py').read_text()
        self.assertIn('product_tree.ensure',text)
        self.assertIn("'--product-adt',c['productAdt']",text)
        self.assertIn("'--product-adt-sha256',c['productAdtSha256']",text)
        self.assertNotIn('research/ipsw-x',text)
        source=(ROOT/'desktop/runtime_setup.py').read_text()
        self.assertIn('productAdtSha256=product_tree.ADT_SHA256',source)

    def test_public_pack_does_not_contain_apple_product_tree(self):
        for name in ('build.py','build_runtime_pack.py'):
            text=(ROOT/'desktop'/name).read_text()
            self.assertIn("'lzfse.exe'",text)
            self.assertIn("'.adt'",text);self.assertIn("'.im4p'",text)


class BootFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=load('_test_boot_diagnostic_native',ROOT/'tools/iossweet-native-windows.py')

    def test_child_error_is_retained_and_does_not_dump_command_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            command=[sys.executable,'-c',"import sys;print('ValueError: Missing iPhone product capabilities',file=sys.stderr);sys.exit(1)"]
            with self.assertRaisesRegex(RuntimeError,'mkadt failed.*Missing iPhone product'):
                self.native.run_boot_tool(command,Path(folder),'mkadt',10)
            self.assertIn('Missing iPhone product',(Path(folder)/'mkadt.log').read_text())

    def test_timeout_retains_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            command=[sys.executable,'-u','-c',"import time;print('Started');time.sleep(20)"]
            with self.assertRaisesRegex(RuntimeError,'mkpayload timed out'):
                self.native.run_boot_tool(command,Path(folder),'mkpayload',.2)
            self.assertTrue((Path(folder)/'mkpayload.log').is_file())

    def test_der_truncation_and_encrypted_component_are_not_accepted(self):
        extractor=load('_test_product_extractor',ROOT/'tools/extract-im4p-adt.py')
        for data in (b'',b'\x30',b'\x30\x82\x01',b'\x30\x80',b'\x30\x85\0\0\0\0\0'):
            with self.assertRaises(ValueError):extractor.tlv(data,0)


if __name__=='__main__':unittest.main()
