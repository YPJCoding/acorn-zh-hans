#!/usr/bin/env python3
"""
Unit and integration test for core/acorn_tool.py using a staged temporary App copy.
Verifies safety, backup integrity, exact signature, and 100% clean restoration.
"""

from pathlib import Path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
import shutil
import tempfile
import unittest
import subprocess

from core.acorn_tool import (
    get_status,
    calculate_diff,
    apply_patch,
    restore_app,
    sha256_file,
    Dictionary,
    DEFAULT_APP,
    validate_pair,
    AcornToolError
)

class TestAcornCoreTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DEFAULT_APP.exists():
            raise unittest.SkipTest(f"{DEFAULT_APP} does not exist on this machine")
        cls.orig_hashes = {
            'info': sha256_file(DEFAULT_APP / 'Contents/Info.plist'),
            'bin': sha256_file(DEFAULT_APP / 'Contents/MacOS/Acorn'),
            'code': sha256_file(DEFAULT_APP / 'Contents/_CodeSignature/CodeResources')
        }

    def setUp(self):
        # Create an isolated temporary copy of Acorn.app for testing
        self.temp_dir = tempfile.mkdtemp(prefix='test-acorn-')
        self.test_app = Path(self.temp_dir) / 'Acorn.app'
        subprocess.run(['/usr/bin/ditto', str(DEFAULT_APP), str(self.test_app)], check=True)
        # Ensure test copy starts in clean OFFICIAL state regardless of host app state
        st = get_status(self.test_app)
        if st['status'] == 'LOCALIZED':
            restore_app(self.test_app)
        self.orig_hashes = {
            'info': sha256_file(self.test_app / 'Contents/Info.plist'),
            'bin': sha256_file(self.test_app / 'Contents/MacOS/Acorn'),
            'code': sha256_file(self.test_app / 'Contents/_CodeSignature/CodeResources')
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_status_official(self):
        st = get_status(self.test_app)
        self.assertEqual(st['status'], 'OFFICIAL')
        self.assertTrue(st['signature_valid'])
        self.assertFalse(st['has_backup'])
        self.assertFalse(st['has_zh_resource'])

    def test_diff_calculation(self):
        diff = calculate_diff(self.test_app)
        self.assertGreater(diff['total_keys'], 1000)
        self.assertEqual(diff['translated_count'], diff['total_keys'])
        self.assertEqual(len(diff['untranslated']), 0)
        self.assertEqual(diff['coverage_percentage'], 100.0)

    def test_apply_and_restore_cycle(self):
        # 1. Apply patch
        res_apply = apply_patch(self.test_app)
        self.assertEqual(res_apply['status'], 'SUCCESS')

        # Check status after patch
        st_patched = get_status(self.test_app)
        self.assertEqual(st_patched['status'], 'LOCALIZED')
        self.assertTrue(st_patched['signature_valid'])
        self.assertTrue(st_patched['has_backup'])
        self.assertTrue(st_patched['has_zh_resource'])
        self.assertTrue(st_patched['sparkle_disabled'])

        # 2. Restore to official
        res_restore = restore_app(self.test_app)
        self.assertEqual(res_restore['status'], 'RESTORED')

        # Check status after restore
        st_restored = get_status(self.test_app)
        self.assertEqual(st_restored['status'], 'OFFICIAL')
        self.assertTrue(st_restored['signature_valid'])
        self.assertFalse(st_restored['has_backup'])
        self.assertFalse(st_restored['has_zh_resource'])

        # Verify exact SHA256 hashes against original files
        self.assertEqual(sha256_file(self.test_app / 'Contents/Info.plist'), self.orig_hashes['info'])
        self.assertEqual(sha256_file(self.test_app / 'Contents/MacOS/Acorn'), self.orig_hashes['bin'])
        self.assertEqual(sha256_file(self.test_app / 'Contents/_CodeSignature/CodeResources'), self.orig_hashes['code'])

    def test_placeholder_validation_failure(self):
        # Key with %@ must have %@ in value
        with self.assertRaises(AcornToolError):
            validate_pair("Export to %@", "导出到目标")

if __name__ == '__main__':
    unittest.main()
