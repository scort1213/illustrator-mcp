"""Tests for the platform backend abstraction layer."""

import os
import sys
import tempfile
from pathlib import Path
import subprocess
import time
import unittest
from unittest import mock

from illustrator.platform_backend import (
    IllustratorBackend,
    MacBackend,
    WindowsBackend,
    get_backend,
    applescript_string,
)


class BackendStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ai-backend-test-')
        self.addCleanup(self.directory.cleanup)
        self.environment = mock.patch.dict(os.environ, {'ILLUSTRATOR_SCRIPT_DIR': self.directory.name})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.home = mock.patch('illustrator.local_paths.Path.home', return_value=Path(self.directory.name))
        self.home.start(); self.addCleanup(self.home.stop)
        # Backend subprocess mocks should not also pretend to be mount output.
        # The actual mount/link boundary is verified in test_local_paths.py.
        self.mount = mock.patch('illustrator.local_paths._assert_mounted_locally')
        self.mount.start(); self.addCleanup(self.mount.stop)


class TestGetBackend(unittest.TestCase):
    """Test the factory function returns the right backend per platform."""

    @mock.patch("illustrator.platform_backend.sys")
    @mock.patch.object(MacBackend, "__init__", return_value=None)
    def test_returns_mac_backend_on_darwin(self, mock_init, mock_sys):
        mock_sys.platform = "darwin"
        backend = get_backend()
        self.assertIsInstance(backend, MacBackend)

    @mock.patch("illustrator.platform_backend.sys")
    @mock.patch.object(WindowsBackend, "__init__", return_value=None)
    def test_returns_windows_backend_on_win32(self, mock_init, mock_sys):
        mock_sys.platform = "win32"
        backend = get_backend()
        self.assertIsInstance(backend, WindowsBackend)

    @mock.patch("illustrator.platform_backend.sys")
    def test_raises_on_unsupported_platform(self, mock_sys):
        mock_sys.platform = "freebsd"
        with self.assertRaises(RuntimeError):
            get_backend()


class TestMacBackendRunScript(BackendStorageTests):
    """Test MacBackend.run_script with mocked osascript."""

    def _make_backend(self):
        """Create a MacBackend without running the __init__ sanity check."""
        backend = MacBackend.__new__(MacBackend)
        backend._APP_NAME = "Adobe Illustrator"
        return backend

    @mock.patch("illustrator.platform_backend.subprocess.run")
    def test_run_script_success(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="42\n", stderr=""
        )
        backend = self._make_backend()
        result = backend.run_script('alert("hello");')
        self.assertEqual(result, "42")

        # Verify osascript was called with the right arguments
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertEqual(cmd[0], "/usr/bin/osascript")
        self.assertEqual(cmd[1], "-e")
        self.assertIn("do javascript", cmd[2])
        self.assertIn('as «class utf8»', cmd[2])
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    @mock.patch("illustrator.platform_backend.subprocess.run")
    def test_long_deadline_reaches_subprocess_without_thirty_second_cap(self, child):
        child.return_value = mock.Mock(returncode=0, stdout='42', stderr='')
        # A fixed clock tests the forwarded budget without host timer rounding
        # (Windows CI can otherwise subtract to 120.00000000000003 seconds).
        with mock.patch('illustrator.platform_backend.time.monotonic', return_value=101.0):
            self.assertEqual(self._make_backend().run_script('42', deadline=220.0), '42')
        self.assertEqual(child.call_args.kwargs['timeout'], 119.0)

    @mock.patch("illustrator.platform_backend.subprocess.run")
    def test_expired_deadline_never_dispatches(self, child):
        with self.assertRaisesRegex(TimeoutError, 'execution_timeout'):
            self._make_backend().run_script('42', deadline=time.monotonic() - 1)
        child.assert_not_called()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    @mock.patch("illustrator.platform_backend.subprocess.run")
    @mock.patch("illustrator.platform_backend.os.path.isfile", return_value=True)
    def test_constructor_does_not_probe_adobe(self, exists, child):
        MacBackend()
        child.assert_not_called()

    @mock.patch("illustrator.platform_backend.subprocess.run")
    def test_run_script_no_return_value(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="", stderr=""
        )
        backend = self._make_backend()
        result = backend.run_script("app.documents.add();")
        self.assertEqual(result, "Script executed successfully (no return value)")

    @mock.patch("illustrator.platform_backend.subprocess.run")
    def test_run_script_osascript_error(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="execution error: Application not running"
        )
        backend = self._make_backend()
        with self.assertRaises(RuntimeError) as ctx:
            backend.run_script("bad code")
        self.assertIn("osascript failed", str(ctx.exception))
        self.assertTrue((Path(ctx.exception.inspection_path)/'script.jsx').exists())


class TestMacBackendScreenshot(BackendStorageTests):
    """Test MacBackend.capture_screenshot with mocked screencapture."""

    def _make_backend(self):
        backend = MacBackend.__new__(MacBackend)
        backend._APP_NAME = "Adobe Illustrator"
        return backend

    @mock.patch('illustrator.platform_backend.subprocess.run')
    @mock.patch('illustrator.platform_backend.storage_directory', side_effect=RuntimeError('local_path_required: remote preview storage'))
    def test_unverified_preview_storage_rejects_before_focusing_adobe(self, storage, child):
        with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
            self._make_backend().capture_screenshot()
        child.assert_not_called()

    @mock.patch("illustrator.platform_backend.os.path.exists", return_value=True)
    @mock.patch("illustrator.platform_backend.os.unlink")
    @mock.patch("illustrator.platform_backend.Image.open")
    @mock.patch("illustrator.platform_backend.subprocess.run")
    @mock.patch("illustrator.platform_backend.time.sleep")
    def test_capture_screenshot_returns_base64(
        self, mock_sleep, mock_run, mock_open, mock_unlink, mock_exists
    ):
        # Mock subprocess calls (focus_app + screencapture)
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        # Mock Image.open to return a small test image
        from PIL import Image
        test_img = Image.new("RGB", (100, 100), color="red")
        mock_open.return_value = test_img

        backend = self._make_backend()
        result = backend.capture_screenshot()

        # Should be a non-empty base64 string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

        # Should be valid base64
        import base64
        decoded = base64.b64decode(result)
        self.assertGreater(len(decoded), 0)
        capture = [call for call in mock_run.call_args_list if call.args[0][0] == '/usr/sbin/screencapture'][0]
        self.assertIn('.illustrator-mcp', capture.args[0][-1])
        self.assertEqual(list((Path(self.directory.name) / '.illustrator-mcp' / 'preview').iterdir()), [])


class TestWindowsBackendRunScript(BackendStorageTests):
    """Test WindowsBackend.run_script with mocked COM."""

    def _make_backend(self):
        backend = WindowsBackend.__new__(WindowsBackend)
        backend._win32com = mock.MagicMock()
        return backend

    def test_run_script_success(self):
        backend = self._make_backend()
        mock_app = mock.MagicMock()
        mock_app.DoJavaScriptFile.return_value = "result_value"
        backend._win32com.client.Dispatch.return_value = mock_app

        result = backend.run_script('alert("test");')
        self.assertEqual(result, "result_value")

    def test_run_script_no_return(self):
        backend = self._make_backend()
        mock_app = mock.MagicMock()
        mock_app.DoJavaScriptFile.return_value = None
        backend._win32com.client.Dispatch.return_value = mock_app

        result = backend.run_script("app.documents.add();")
        self.assertEqual(result, "Script executed successfully (no return value)")


class TestImageToBase64(unittest.TestCase):
    """Test the shared _image_to_base64_jpeg helper."""

    def test_returns_valid_base64_jpeg(self):
        import base64
        from PIL import Image

        img = Image.new("RGB", (50, 50), color="blue")
        result = IllustratorBackend._image_to_base64_jpeg(img)

        decoded = base64.b64decode(result)
        # JPEG files start with FF D8
        self.assertEqual(decoded[:2], b"\xff\xd8")


class AppleScriptLiteralTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'AppleScript literal roundtrip requires macOS')
    def test_quotes_backslashes_controls_and_unicode_roundtrip_without_adobe(self):
        value = '本地 "quote" \\ path\n\r\t' + chr(1) + '🧪'
        # Only the local language interpreter returns a literal; no app is told
        # to run and no Adobe document or network operation is performed.
        result = subprocess.run(['/usr/bin/osascript', '-e', 'return ' + applescript_string(value)], capture_output=True, check=True, timeout=5)
        self.assertEqual(result.stdout[:-1].decode('utf-8'), value)

    @unittest.skipUnless(sys.platform == 'darwin', 'AppleScript file-read roundtrip requires macOS')
    def test_encoded_file_path_reads_utf8_without_telling_adobe(self):
        with tempfile.TemporaryDirectory(prefix='ai-apple-literal-') as root:
            path = Path(root) / '本地"\\\n脚本.jsx'
            source = '中文 🧪 "quoted"'
            path.write_text(source, encoding='utf-8')
            expression = 'return (read POSIX file ' + applescript_string(str(path)) + ' as «class utf8»)'
            result = subprocess.run(['/usr/bin/osascript', '-e', expression], capture_output=True, check=True, timeout=5)
            self.assertEqual(result.stdout[:-1].decode('utf-8'), source)


if __name__ == "__main__":
    unittest.main()
