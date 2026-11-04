"""Plan-only checks: no real firmware, disk or running machine is used."""
import hashlib
import importlib.util
import json
import pathlib
import plistlib
import tempfile
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gpu_launch", PACKAGE / "launch.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)

class LaunchPlan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gpu-plan-")
        self.root = pathlib.Path(self.temp.name)
        self.bundle = self.root / "working bundle"
        self.bundle.mkdir()
        self.data = self.root / "qemu-data"
        self.data.mkdir()
        (self.data / "efi-virtio.rom").write_bytes(b"owned fixture")
        self.old_data = launcher.QEMU_DATA
        launcher.QEMU_DATA = self.data
        (self.bundle / "config.plist").write_bytes(plistlib.dumps({"romImages":{"avpBooter":"OpenAVB.bin","avpSEPBooter":"OpenSEP.bin"}}))
        for name in ["OpenAVB.bin","OpenSEP.bin","Disk.img","SEPStorage"]:
            (self.bundle / name).write_bytes(b"owned fixture")
        (self.bundle / "nvram.bin").write_bytes(bytes(16385))
        (self.bundle / "ecid").write_text("123456789abcdef")
        (self.bundle / "gfx-res").write_text("860x1864")

    def tearDown(self):
        launcher.QEMU_DATA = self.old_data
        self.temp.cleanup()

    def test_paused_plan_preserves_bundle_and_storage_aliases(self):
        before = {p.name:hashlib.sha256(p.read_bytes()).digest() for p in self.bundle.iterdir()}
        plan = launcher.plan(self.bundle,"4G",4,19688,vusb_port=19690,serial_log=self.root/"new-serial.log")
        args = plan["args"]
        drives = [args[i+1] for i,v in enumerate(args) if v=="-drive"]
        self.assertEqual(len(drives),5)
        self.assertEqual(sum("offset=16384" in d for d in drives),2)
        self.assertTrue(any("id=root-pci" in d for d in drives))
        self.assertTrue(any("id=aux-pci" in d for d in drives))
        self.assertIn("apple-gfx-mmio.process-isolation=on",args)
        self.assertIn("apple-gfx-mmio.guest-page-shift=14",args)
        self.assertEqual(args[-1],"-S")
        self.assertFalse((self.root/"new-serial.log").exists())
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).digest() for p in self.bundle.iterdir()})

    def test_refuses_invalid_identity_memory_and_colliding_ports(self):
        for options in [{"memory":"0G"},{"cores":0},{"port":19688,"vusb_port":19688}]:
            with self.assertRaises(ValueError):launcher.plan(self.bundle,**options)
        (self.bundle/"ecid").write_text("bad,value")
        with self.assertRaises(ValueError):launcher.plan(self.bundle)

    def test_refuses_existing_log_and_outside_rom(self):
        log=self.root/"existing.log";log.write_text("preserve")
        with self.assertRaises(ValueError):launcher.plan(self.bundle,serial_log=log)
        (self.root/"outside.bin").write_bytes(b"owned fixture")
        (self.bundle/"config.plist").write_bytes(plistlib.dumps({"romImages":{"avpBooter":"../outside.bin","avpSEPBooter":"OpenSEP.bin"}}))
        with self.assertRaises(ValueError):launcher.plan(self.bundle)

class PatchManifest(unittest.TestCase):
    def test_pinned_patch_digests(self):
        manifest=json.loads((PACKAGE/"sources.json").read_text())
        self.assertEqual(len(manifest["sources"]),3)
        for source in manifest["sources"]:
            self.assertEqual(len(source["base_commit"]),40)
            self.assertEqual(hashlib.sha256((PACKAGE/source["patch"]).read_bytes()).hexdigest(),source["patch_sha256"])
            self.assertTrue(source["files"])

if __name__=="__main__":unittest.main()
