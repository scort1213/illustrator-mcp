"""Regression: an occluding AI-client window must not appear in the capture."""
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from illustrator.platform_backend import WindowsBackend


class WindowsCaptureTests(unittest.TestCase):
    def test_minimized_window_returns_error_without_a_desktop_fallback(self):
        gui = Mock()
        gui.EnumWindows.side_effect = lambda fn, arg: fn(2, arg)
        gui.IsWindowVisible.return_value = True
        gui.GetClassName.return_value = 'illustrator'
        gui.GetWindowRect.return_value = (0, 0, 640, 400)
        gui.IsIconic.return_value = True
        with patch.dict('sys.modules', {'win32gui': gui}), patch('PIL.ImageGrab.grab') as grab:
            with self.assertRaisesRegex(RuntimeError, 'minimized'):
                WindowsBackend.__new__(WindowsBackend).capture_screenshot()
            grab.assert_not_called()
    def test_capture_targets_illustrator_hwnd_instead_of_desktop(self):
        gui = Mock()
        gui.EnumWindows.side_effect = lambda fn, arg: [fn(1, arg), fn(2, arg)]
        gui.IsWindowVisible.return_value = True
        gui.GetClassName.side_effect = lambda hwnd: 'illustrator' if hwnd == 2 else 'Chrome_WidgetWin_1'
        gui.GetWindowRect.return_value = (0, 0, 640, 400)
        gui.IsIconic.return_value = False
        with patch.dict('sys.modules', {'win32gui': gui}), patch('PIL.ImageGrab.grab') as grab:
            grab.return_value = Image.new('RGB', (640, 400), 'blue')
            backend = WindowsBackend.__new__(WindowsBackend)
            self.assertTrue(backend.capture_screenshot())
            grab.assert_called_once_with(window=2)

    def test_missing_window_does_not_fall_back_to_capturing_other_apps(self):
        gui = Mock()
        gui.EnumWindows.side_effect = lambda fn, arg: None
        with patch.dict('sys.modules', {'win32gui': gui}), patch('PIL.ImageGrab.grab') as grab:
            backend = WindowsBackend.__new__(WindowsBackend)
            with self.assertRaisesRegex(RuntimeError, 'No visible Illustrator window'):
                backend.capture_screenshot()
            grab.assert_not_called()
