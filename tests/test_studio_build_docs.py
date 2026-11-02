"""Keep GitHub's full source instructions aligned with the shipped sources."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StudioBuildDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.guide = (ROOT / 'docs/STUDIO_SOURCE_BUILD.md').read_text(encoding='utf-8')
        self.readme = (ROOT / 'README.md').read_text(encoding='utf-8')

    def test_full_guide_is_on_readme_not_only_linked(self):
        start = '<!-- STUDIO_SOURCE_BUILD_BEGIN -->'
        end = '<!-- STUDIO_SOURCE_BUILD_END -->'
        self.assertEqual(self.readme.count(start), 1)
        self.assertEqual(self.readme.count(end), 1)
        included = self.readme.split(start)[1].split(end)[0].strip()
        self.assertEqual(included, self.guide.strip())

    def test_main_contains_the_full_project_and_is_the_documented_branch(self):
        self.assertIn('https://github.com/danhol86/ios-sweet/tree/main', self.readme)
        self.assertIn('git clone --branch main https://github.com/danhol86/ios-sweet.git', self.guide)
        self.assertIn('--ref main', self.guide)
        self.assertIn('--branch main --limit', self.guide)
        for text in (self.readme, self.guide):
            self.assertNotIn('windows-qemu-virtio', text)
            self.assertNotIn('checking out `main` is not enough', text)
            self.assertNotIn('default `main` tree does not contain', text)
            self.assertNotIn('<<<<<<<', text)
            self.assertNotIn('>>>>>>>', text)

    def test_referenced_build_sources_exist(self):
        paths = ('desktop/studio.py', 'desktop/build.py', 'desktop/runtime_setup.py',
                 'desktop/bundles.py', 'desktop/requirements.txt',
                 'desktop/helper-toolchain.Dockerfile', 'desktop/build-helpers.sh',
                 'desktop/appliance/Dockerfile', 'desktop/appliance/build.sh',
                 'desktop/installer/Setup.cs', 'desktop/installer/Uninstall.cs',
                 'tools/guest-install/Dockerfile',
                 'tools/guest-install/agent-entitlements.plist',
                 '.github/workflows/xnu.yml', 'tests/check_viewer_poll.js',
                 'tests/check_viewer_pointer.js')
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())

    def test_documented_package_flags_match_the_parser(self):
        tree = ast.parse((ROOT / 'desktop/build.py').read_text(encoding='utf-8'))
        flags = {arg.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                 for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)}
        for flag in ('--assets', '--qemu', '--signer', '--output'):
            self.assertIn(flag, flags)
            self.assertIn(flag, self.guide)

    def test_manifest_python_example_compiles(self):
        examples = re.findall(r"@'\n(.*?)\n'@ \| & \$Py", self.guide, flags=re.S)
        self.assertEqual(len(examples), 1)
        compile(examples[0], 'README-helper-manifest.py', 'exec')

    def test_fresh_clone_does_not_depend_on_private_paths_or_worker(self):
        self.assertIn('git clone --branch main https://github.com/danhol86/ios-sweet.git', self.guide)
        for private in ('C:\\Users\\danho', 'D:\\Projects', 'novaforge-ipa-worker', 'novaforge-ipa-builder_apple-sdk'):
            self.assertNotIn(private, self.guide)
        self.assertIn('not currently supported', self.guide)
        self.assertIn('independent clean-machine acceptance test', self.guide)


if __name__ == '__main__':
    unittest.main()
