"""
Platform abstraction layer for Adobe Illustrator automation.

Provides a unified interface for screenshot capture and ExtendScript execution
across Windows (COM/win32) and macOS (AppleScript/osascript).
"""

import abc
import base64
import io
import logging
import os
import subprocess
import sys
import time
import math

from PIL import Image

try:
    from .script_files import script_file, owned_directory
    from .local_paths import storage_directory, validate_internal_path
except ImportError:
    from script_files import script_file, owned_directory
    from local_paths import storage_directory, validate_internal_path

logger = logging.getLogger(__name__)


def remaining_seconds(deadline=None):
    remaining = 30.0 if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('execution_timeout: deadline expired before subprocess dispatch')
    return remaining


def applescript_string(value):
    """Encode literal strings, including quotes, backslashes and C0 characters."""
    parts, text = [], []
    def flush():
        if text:
            parts.append('"' + ''.join(text).replace('\\', '\\\\').replace('"', '\\"') + '"')
            text.clear()
    for character in value:
        if ord(character) < 32:
            flush()
            parts.append('(ASCII character %d)' % ord(character))
        else:
            text.append(character)
    flush()
    if len(parts) == 1:
        return parts[0]
    return '(' + ' & '.join(parts or ['""']) + ')'


class IllustratorBackend(abc.ABC):
    """Abstract base class for platform-specific Illustrator automation."""

    @abc.abstractmethod
    def focus_app(self, *, deadline=None) -> None:
        """Bring Adobe Illustrator to the foreground."""

    @abc.abstractmethod
    def capture_screenshot(self, *, deadline=None) -> str:
        """Capture a screenshot of the Illustrator window.

        Returns:
            Base64-encoded JPEG image data.
        """

    @abc.abstractmethod
    def run_script(self, code: str, *, deadline=None) -> str:
        """Execute ExtendScript code in Illustrator.

        Args:
            code: ExtendScript/JavaScript source code.

        Returns:
            Result text from the script execution.
        """

    # ---- shared helpers ------------------------------------------------

    @staticmethod
    def _image_to_base64_jpeg(img: Image.Image, quality: int = 50) -> str:
        """Compress a PIL Image to JPEG and return base64-encoded data."""
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# =====================================================================
# Windows backend
# =====================================================================

class WindowsBackend(IllustratorBackend):
    """Illustrator automation via Windows COM (pywin32)."""

    def __init__(self) -> None:
        try:
            import win32com.client  # noqa: F401
            import pythoncom  # noqa: F401
            self._win32com = win32com
            logger.info("WindowsBackend initialised – win32com loaded.")
        except ImportError as exc:
            raise RuntimeError(
                "pywin32 is required on Windows. Install it with: pip install pywin32"
            ) from exc

    def focus_app(self, *, deadline=None) -> None:
        remaining_seconds(deadline)
        shell = self._win32com.client.Dispatch("WScript.Shell")
        shell.AppActivate("Adobe Illustrator")

    @staticmethod
    def _verify_window_capture(image):
        """Reject the known unrendered dark-gray surface, not infer art validity.

        A conservative rejection can also match intentionally uniform gray art.
        Other capture defects still require visual inspection by the caller.
        """
        width, height = image.size
        rgb = image.convert('RGB')
        center = rgb.crop((width // 10, height // 10, width * 9 // 10, height * 9 // 10))
        ranges = center.getextrema()
        if not ranges or any(high - low > 3 for low, high in ranges):
            return
        gray = [(low + high) / 2 for low, high in ranges]
        if max(gray) > 96 or max(gray) - min(gray) > 3:
            return
        sample = rgb.resize((128, 128))
        matches = sum(all(abs(pixel[i] - gray[i]) <= 3 for i in range(3))
                      for pixel in sample.get_flattened_data())
        if matches >= 128 * 128 * 0.8:
            raise RuntimeError(
                'capture_unavailable: Illustrator returned an unverified near-uniform dark-gray window. '
                'Use run to export the intended artboard to a local PNG for review. '
                'No desktop fallback was captured.'
            )

    def capture_screenshot(self, *, deadline=None) -> str:
        from PIL import ImageGrab
        import win32gui

        # Capture the application itself, even when another window covers it.
        # Desktop capture can otherwise return the AI client instead of the art.
        windows = []
        def collect_window(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd)
                    and "illustrator" in win32gui.GetClassName(hwnd).lower()):
                windows.append(hwnd)
        win32gui.EnumWindows(collect_window, None)
        if not windows:
            raise RuntimeError("No visible Illustrator window found. Open Illustrator first.")
        hwnd = max(windows, key=lambda handle: (
            (win32gui.GetWindowRect(handle)[2] - win32gui.GetWindowRect(handle)[0])
            * (win32gui.GetWindowRect(handle)[3] - win32gui.GetWindowRect(handle)[1])
        ))
        if win32gui.IsIconic(hwnd):
            raise RuntimeError("Illustrator is minimized. Restore its window before capturing.")
        remaining_seconds(deadline)
        screenshot = ImageGrab.grab(window=hwnd)
        self._verify_window_capture(screenshot)
        logger.info("Screenshot captured (Windows/Illustrator window).")
        return self._image_to_base64_jpeg(screenshot)

    def run_script(self, code: str, *, deadline=None) -> str:
        remaining_seconds(deadline)
        with script_file(code) as jsx_path:
            logger.debug("ExtendScript saved to: %s", jsx_path)
            remaining_seconds(deadline)
            app = self._win32com.client.Dispatch("Illustrator.Application")
            remaining_seconds(deadline)
            result = app.DoJavaScriptFile(jsx_path)
            logger.info("ExtendScript executed successfully (Windows/COM).")
            return str(result) if result is not None else "Script executed successfully (no return value)"


# =====================================================================
# macOS backend
# =====================================================================

class MacBackend(IllustratorBackend):
    """Illustrator automation via AppleScript / osascript on macOS."""

    # AppleScript application name — Adobe Illustrator registers itself this
    # way in the scripting dictionary.  Older versions may use a year suffix
    # (e.g. "Adobe Illustrator 2024") – we try the plain name first.
    _APP_NAME = "Adobe Illustrator"

    def __init__(self) -> None:
        # Quick sanity check — osascript must be present.
        if not os.path.isfile("/usr/bin/osascript"):
            raise RuntimeError("osascript not found – this backend requires macOS.")

        # A tool's actual script establishes connectivity inside that tool's
        # deadline; construction does not dispatch a separate version probe.

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _osascript(script: str, *, deadline=None) -> str:
        """Run a one-liner AppleScript and return stdout."""
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=remaining_seconds(deadline),
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"osascript failed ({result.returncode}): {stderr}")
        return result.stdout.strip()

    @staticmethod
    def _osascript_multi(lines: list[str], *, deadline=None) -> str:
        """Run a multi-line AppleScript passed as separate -e arguments."""
        cmd: list[str] = ["/usr/bin/osascript"]
        for line in lines:
            cmd.extend(["-e", line])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=remaining_seconds(deadline))
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"osascript failed ({result.returncode}): {stderr}")
        return result.stdout.strip()

    # ---- interface implementation --------------------------------------

    def focus_app(self, *, deadline=None) -> None:
        self._osascript(f'tell application {applescript_string(self._APP_NAME)} to activate', deadline=deadline)

    def capture_screenshot(self, *, deadline=None) -> str:
        if deadline is None:
            deadline = time.monotonic() + 30
        root = storage_directory('preview')
        with owned_directory(root, prefix='capture-') as directory:
            tmp_path = str(validate_internal_path(directory / 'preview.jpg'))
            self.focus_app(deadline=deadline)
            time.sleep(min(1, remaining_seconds(deadline)))
            # -x  suppresses the shutter sound
            # -t jpg  output format
            subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-t", "jpg", tmp_path],
                check=True,
                timeout=min(10, remaining_seconds(deadline)),
            )
            with Image.open(tmp_path) as img:
                logger.info("Screenshot captured (macOS/screencapture).")
                return self._image_to_base64_jpeg(img)

    def run_script(self, code: str, *, deadline=None) -> str:
        if deadline is None:
            deadline = time.monotonic() + 30
        remaining_seconds(deadline)
        with script_file(code) as jsx_path:
            logger.debug("ExtendScript saved to: %s", jsx_path)
            # Use AppleScript to tell Illustrator to run the script file.
            seconds = max(1, math.ceil(remaining_seconds(deadline)))
            applescript = (
                f'tell application {applescript_string(self._APP_NAME)}\n'
                f'with timeout of {seconds} seconds\n'
                f'do javascript (read POSIX file {applescript_string(jsx_path)} as «class utf8») as string\n'
                'end timeout\nend tell'
            )
            result = self._osascript(applescript, deadline=deadline)
            logger.info("ExtendScript executed successfully (macOS/osascript).")
            return result if result else "Script executed successfully (no return value)"


# =====================================================================
# Factory
# =====================================================================

def get_backend() -> IllustratorBackend:
    """Return the appropriate backend for the current platform."""
    if sys.platform == "darwin":
        return MacBackend()
    elif sys.platform == "win32":
        return WindowsBackend()
    else:
        raise RuntimeError(
            f"Unsupported platform: {sys.platform}. "
            "This project supports Windows and macOS."
        )
