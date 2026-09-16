"""Serialize COM across clients; a timed-out write is never automatically retried."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import os
import tempfile
import threading
import time

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="illustrator-com")

def root():
    path = Path(os.environ.get("ILLUSTRATOR_SAFETY_DIR", str(Path(tempfile.gettempdir()) / "illustrator-mcp-safety")))
    path.mkdir(parents=True, exist_ok=True)
    return path

def marker():
    return root() / "uncertain.txt"

async def execute(function, timeout=30.0, read_only=False, recover=False):
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 0 < timeout <= 120:
        raise ValueError("invalid_argument: timeout_seconds must be in (0, 120]")
    deadline = time.monotonic() + timeout
    started = threading.Event()
    expired = threading.Event()
    completion_lock = threading.Lock()
    def work():
        windows = os.name == 'nt'
        if windows:
            import pythoncom
            import win32event
            import win32api
            pythoncom.CoInitialize()
            name = "Local\\IllustratorMCP-" + hashlib.sha256(str(root()).encode()).hexdigest()[:24]
            mutex = win32event.CreateMutex(None, False, name)
        else:
            import fcntl
            mutex = (root() / 'active.lock').open('a')
        held = False
        try:
            while time.monotonic() < deadline and not expired.is_set():
                if windows:
                    status = win32event.WaitForSingleObject(mutex, 25)
                else:
                    try:
                        fcntl.flock(mutex.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        status = 0
                    except BlockingIOError:
                        time.sleep(.025)
                        status = 258
                if status in (0, 0x80):
                    held = True
                    if status == 0x80:
                        marker().write_text("Previous COM owner exited; inspect state", encoding="utf-8")
                    break
            if not held or expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("queue_timeout: operation was not dispatched")
            if not read_only and marker().exists():
                raise RuntimeError("outcome_unknown: writes blocked; call get_state then recover_connection")
            if not read_only:
                marker().write_text("Write in progress; outcome unknown if interrupted", encoding="utf-8")
            # Publishing the marker can itself outlive the deadline (slow disk).
            # Commit dispatch under the same lock used by timeout/cancellation.
            with completion_lock:
                if expired.is_set() or time.monotonic() >= deadline:
                    if not read_only:
                        marker().unlink(missing_ok=True)
                    raise TimeoutError("queue_timeout: operation was not dispatched")
                started.set()
            result = function()
            with completion_lock:
                if not expired.is_set() and (recover or not read_only):
                    marker().unlink(missing_ok=True)
            return result
        finally:
            if windows:
                if held: win32event.ReleaseMutex(mutex)
                win32api.CloseHandle(mutex)
                pythoncom.CoUninitialize()
            else:
                if held: fcntl.flock(mutex.fileno(), fcntl.LOCK_UN)
                mutex.close()
    future = _pool.submit(work)
    pending = asyncio.wrap_future(future)
    # The asyncio wrapper also owns an exception after shield detaches it.
    pending.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    try:
        return await asyncio.wait_for(asyncio.shield(pending), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        with completion_lock:
            expired.set()
            future.cancel()
            if started.is_set() and not read_only:
                marker().write_text("outcome_unknown: execution deadline exceeded", encoding="utf-8")
        # Consume a late worker exception without retrying its operation.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        raise TimeoutError("outcome_unknown: execution timeout" if started.is_set() else "queue_timeout: operation was not dispatched")
