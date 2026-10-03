"""No real network paths are opened by these internal-storage boundary tests."""
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from illustrator import local_paths, script_files


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-storage-test-')
        self.addCleanup(self.temp.cleanup)

    def mac_mount(self, output=None):
        return patch('illustrator.local_paths.subprocess.run', return_value=SimpleNamespace(stdout=output or '/dev/disk on / (apfs, local)\n'))

    def test_unc_url_relative_and_device_roots_reject_before_mkdir_or_lstat(self):
        for value in ('//example.invalid/share', r'\\example.invalid\share', 'https://example.invalid/folder', 'relative/path', r'\\?\C:\storage'):
            with self.subTest(value=value), patch('illustrator.local_paths.os.lstat') as inspect, patch.object(Path, 'mkdir') as mkdir, patch('illustrator.local_paths.subprocess.run') as command:
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    local_paths.prepare_directory(value)
                inspect.assert_not_called(); mkdir.assert_not_called(); command.assert_not_called()

    def test_remote_and_unknown_mounts_reject_before_lstat_or_mkdir(self):
        for kind in ('smbfs', 'nfs', 'autofs', 'fusefs', 'unidentified'):
            output = f'/dev/disk on / (apfs, local)\nserver on /Volumes/External ({kind}, nodev)\n'
            with self.subTest(kind=kind), patch('illustrator.local_paths.sys.platform', 'darwin'), self.mac_mount(output), patch('illustrator.local_paths.os.lstat') as inspect, patch.object(Path, 'mkdir') as mkdir:
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    local_paths.prepare_directory('/Volumes/External/new-directory')
                inspect.assert_not_called(); mkdir.assert_not_called()

    def test_ancestor_link_target_mount_is_checked_before_target_is_touched(self):
        inspected = []
        def lstat(path):
            inspected.append(path)
            return SimpleNamespace(st_mode=stat.S_IFLNK if path == '/local/redirect' else stat.S_IFDIR)
        output = '/dev/disk on / (apfs, local)\nserver on /Volumes/Remote (smbfs, nodev)\n'
        with patch('illustrator.local_paths.sys.platform', 'darwin'), self.mac_mount(output), patch('illustrator.local_paths.os.lstat', side_effect=lstat), patch('illustrator.local_paths.os.readlink', return_value='/Volumes/Remote'), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                local_paths.prepare_directory('/local/redirect/new')
            self.assertEqual(inspected, ['/local', '/local/redirect'])
            mkdir.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Physical POSIX symlink fixture; Windows junctions are mocked separately')
    def test_local_ancestor_link_is_resolved_and_leaf_link_is_rejected(self):
        root = Path(self.temp.name)
        target = root / 'target'; target.mkdir()
        alias = root / 'alias'; alias.symlink_to(target, target_is_directory=True)
        actual = local_paths.prepare_directory(alias / 'new')
        self.assertEqual(actual, (target / 'new').resolve())
        with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
            local_paths.prepare_directory(alias)

    def test_default_storage_ignores_tmpdir_and_uses_private_home_subdirectories(self):
        root = Path(self.temp.name)
        with patch.object(Path, 'home', return_value=root), patch.dict(os.environ, {'TMPDIR':'//example.invalid/share'}):
            for kind in ('scripts', 'safety', 'preview'):
                directory = local_paths.storage_directory(kind)
                self.assertEqual(directory.resolve(), (root / '.illustrator-mcp' / kind).resolve())
                self.assertTrue(directory.is_dir())

    def test_runtime_validation_checks_all_roots_without_creating_them(self):
        root = Path(self.temp.name)
        environment = {'ILLUSTRATOR_SCRIPT_DIR': str(root/'new-scripts'),
                       'ILLUSTRATOR_SAFETY_DIR': str(root/'new-safety')}
        with patch.object(Path, 'home', return_value=root), patch.dict(os.environ, environment), patch.object(Path, 'mkdir') as mkdir:
            paths = local_paths.validate_runtime_paths(root, sys.executable)
        self.assertEqual(set(paths), {'installation', 'python', 'scripts', 'safety', 'preview'})
        self.assertEqual(paths['python'], local_paths.validate_internal_path(sys.executable, reject_leaf_link=False))
        mkdir.assert_not_called()
        self.assertFalse((root/'new-scripts').exists())
        self.assertFalse((root/'.illustrator-mcp').exists())

    def test_runtime_unsafe_override_is_rejected_before_mkdir(self):
        root = Path(self.temp.name)
        for environment in ('ILLUSTRATOR_SCRIPT_DIR', 'ILLUSTRATOR_SAFETY_DIR'):
            values = {'ILLUSTRATOR_SCRIPT_DIR': str(root/'scripts'),
                      'ILLUSTRATOR_SAFETY_DIR': str(root/'safety'),
                      environment: '//example.invalid/share'}
            with self.subTest(environment=environment), patch.dict(os.environ, values), patch.object(Path, 'home', return_value=root), patch.object(Path, 'mkdir') as mkdir:
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    local_paths.validate_runtime_paths(root, sys.executable)
                mkdir.assert_not_called()

    def test_runtime_python_link_target_is_checked_before_remote_inspection(self):
        inspected = []
        def lstat(path):
            path = str(path)
            inspected.append(path)
            return SimpleNamespace(st_mode=stat.S_IFLNK if path == '/local/python' else stat.S_IFDIR)
        output = '/dev/disk on / (apfs, local)\nserver on /Volumes/Remote (smbfs, nodev)\n'
        with patch('illustrator.local_paths.sys.platform', 'darwin'), self.mac_mount(output), patch('illustrator.local_paths.os.lstat', side_effect=lstat), patch('illustrator.local_paths.os.readlink', return_value='/Volumes/Remote/python'), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                local_paths.validate_runtime_paths('/local/project', '/local/python')
            self.assertNotIn('/Volumes/Remote/python', inspected)
            self.assertIn('/local/python', inspected)
            mkdir.assert_not_called()

    def test_mount_classification_is_not_cached_between_operations(self):
        target = str(Path(self.temp.name) / 'new')
        if os.name == 'nt':
            with patch('illustrator.local_paths._drive_type', side_effect=[3, 4]) as child:
                local_paths.prepare_directory(target)
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    local_paths.prepare_directory(target)
                self.assertEqual(child.call_count, 2)
            return
        child = Mock(side_effect=[SimpleNamespace(stdout='/dev/disk on / (apfs, local)\n'), SimpleNamespace(stdout='server on / (nfs, nodev)\n')])
        with patch('illustrator.local_paths.sys.platform', 'darwin'), patch('illustrator.local_paths.subprocess.run', child):
            local_paths.prepare_directory(target)
            with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                local_paths.prepare_directory(target)
        self.assertEqual(child.call_count, 2)

    def test_windows_network_and_unknown_drives_reject_before_inspection(self):
        for kind in (0, 1, 4):
            with self.subTest(kind=kind), patch('illustrator.local_paths.sys.platform', 'win32'), patch('illustrator.local_paths._drive_type', return_value=kind) as drive, patch('illustrator.local_paths.os.lstat') as inspect, patch.object(Path, 'mkdir') as mkdir:
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    local_paths.prepare_directory(r'Z:\internal\new')
                drive.assert_called_once_with('Z:\\')
                inspect.assert_not_called(); mkdir.assert_not_called()

    def test_windows_junction_to_unc_is_rejected_before_target_inspection(self):
        inspected = []
        def lstat(path):
            inspected.append(path)
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch('illustrator.local_paths.sys.platform', 'win32'), patch('illustrator.local_paths._drive_type', return_value=3), patch('illustrator.local_paths.os.lstat', side_effect=lstat), patch('illustrator.local_paths.os.readlink', return_value=r'\\?\UNC\example.invalid\share'), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                local_paths.prepare_directory(r'C:\junction\new')
            self.assertEqual(inspected, [r'C:\junction'])
            mkdir.assert_not_called()

    def test_windows_local_junction_extended_prefix_remains_usable(self):
        inspected = []
        def lstat(path):
            inspected.append(path)
            if path == r'C:\junction':
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            raise FileNotFoundError(path)
        with patch('illustrator.local_paths.sys.platform', 'win32'), patch('illustrator.local_paths._drive_type', return_value=3), patch('illustrator.local_paths.os.lstat', side_effect=lstat), patch('illustrator.local_paths.os.readlink', return_value=r'\\?\C:\target'):
            actual = local_paths.validate_internal_path(r'C:\junction\new')
            self.assertEqual(str(actual), r'C:\target\new')
            self.assertEqual(inspected, [r'C:\junction', r'C:\target'])

    def test_unparseable_mount_table_is_rejected(self):
        with patch('illustrator.local_paths.sys.platform', 'darwin'), self.mac_mount('not a mount table'), patch('illustrator.local_paths.os.lstat') as inspect:
            with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                local_paths.prepare_directory('/local/new')
            inspect.assert_not_called()

    def test_recovery_keeps_owned_directory_with_nested_link(self):
        import json
        root = Path(self.temp.name)
        directory = root / 'call-123-stale'; directory.mkdir()
        (directory / 'owner.json').write_text(json.dumps({'kind':'illustrator-mcp-script','pid':123}))
        (directory / 'script.jsx').write_text('synthetic source')
        nested = directory / 'remote-child'; nested.write_text('synthetic link fixture')
        original = os.lstat
        nested_info = original(nested)
        matched = []
        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            # File identity matches both long paths and Windows 8.3 aliases.
            # Resolving inside this hook would recurse through mocked lstat on POSIX.
            if os.path.samestat(info, nested_info):
                matched.append(path)
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return info
        with patch.dict(os.environ, {'ILLUSTRATOR_SCRIPT_DIR': str(root)}), patch.object(script_files, 'owner_alive', return_value=False), patch('illustrator.local_paths.os.lstat', side_effect=lstat):
            self.assertEqual(script_files.cleanup_stale_scripts(), 0)
        self.assertTrue(matched, 'the nested-link fixture must actually be inspected')
        self.assertTrue((directory / 'script.jsx').exists())


if __name__ == '__main__':
    unittest.main()
