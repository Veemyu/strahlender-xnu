"""Bundle resources must match the selected Apple platform, including on rebuilds."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'recomp/ios/app/copy_bundle_resources.sh'

class ShaderResources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='shader resources ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache, self.bundle = self.root / 'cache', self.root / 'build/Test.app'
        (self.cache / 'shaders').mkdir(parents=True)
        (self.cache / 'shaders-bin-iphoneos').mkdir()
        self.bundle.mkdir(parents=True)
        (self.cache / 'shaders/v_0000000000000001.metal').write_text('source')
        (self.cache / 'shaders-bin-iphoneos/v_0000000000000001.metallib').write_bytes(b'fixture')
        (self.cache / 'shaders-bin-iphoneos/.sdk').write_text('iphoneos\n')

    def copy(self, platform='iphoneos'):
        env = dict(os.environ, BDSP_SHADER_CACHE_DIR=str(self.cache), TARGET_BUILD_DIR=str(self.bundle.parent),
                   UNLOCALIZED_RESOURCES_FOLDER_PATH=self.bundle.name, PLATFORM_NAME=platform)
        return subprocess.run(['/bin/sh', str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_matching_sources_only(self):
        (self.cache / 'shaders-bin-iphoneos/f_orphan.metallib').write_bytes(b'old')
        self.assertEqual(self.copy().returncode, 0)
        self.assertEqual([p.name for p in (self.bundle / 'shaders-bin').iterdir()], ['v_0000000000000001.metallib'])

    def test_wrong_platform_clears_previous_build(self):
        self.assertEqual(self.copy().returncode, 0)
        (self.cache / 'shaders-bin-iphoneos/.sdk').write_text('macosx\n')
        self.assertEqual(self.copy().returncode, 0)
        self.assertFalse((self.bundle / 'shaders-bin').exists())

    def test_simulator_does_not_receive_device_libraries(self):
        self.assertEqual(self.copy('iphonesimulator').returncode, 0)
        self.assertFalse((self.bundle / 'shaders-bin').exists())

    def test_incomplete_compilation_fails(self):
        (self.cache / 'shaders-bin-iphoneos/v_0000000000000001.metallib').unlink()
        self.assertNotEqual(self.copy().returncode, 0)

    def test_missing_cache_clears_old_resources(self):
        self.assertEqual(self.copy().returncode, 0)
        (self.cache / 'pipelines.bin').write_bytes(b'old')
        self.assertEqual(self.copy().returncode, 0)
        import shutil
        shutil.rmtree(self.cache)
        self.assertEqual(self.copy().returncode, 0)
        for resource in ['shaders', 'shaders-bin', 'pipelines.bin']:
            self.assertFalse((self.bundle / resource).exists())

if __name__ == '__main__':
    unittest.main()
