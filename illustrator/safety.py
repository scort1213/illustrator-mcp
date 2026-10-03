"""Serialize Adobe calls; timed-out writes are never automatically retried."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import hashlib
import os
import subprocess
import threading
import time

try:
    from .local_paths import local_path_context, storage_directory, validate_internal_path
except ImportError:
    from local_paths import local_path_context, storage_directory, validate_internal_path

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="illustrator-com")
_operation = ContextVar('illustrator_script_inspection', default=None)


def script_directory_started(path):
    operation = _operation.get()
    if operation is not None:
        operation['inspection_path'] = str(path)


def script_directory_finished(path, retained=False):
    operation = _operation.get()
    if operation is not None and not retained and operation['inspection_path'] == str(path):
        operation['inspection_path'] = None


def should_retain_script():
    operation = _operation.get()
    return operation is not None and (operation['expired'].is_set() or time.monotonic() >= operation['deadline'])


def root():
    return storage_directory('safety', 'ILLUSTRATOR_SAFETY_DIR')


def marker():
    return validate_internal_path(root() / 'uncertain.txt')


async def execute(function, timeout=30.0, read_only=False, recover=False, pass_deadline=False):
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 0 < timeout <= 120:
        raise ValueError("invalid_argument: timeout_seconds must be in (0, 120]")
    deadline = time.monotonic() + timeout
    started = threading.Event()
    expired = threading.Event()
    completion_lock = threading.Lock()
    operation = {'expired': expired, 'deadline': deadline, 'inspection_path': None}

    def work():
        token = _operation.set(operation)
        try:
            with local_path_context():
                return work_locally()
        finally:
            _operation.reset(token)

    def work_locally():
        storage = root()  # Verify storage before creating locks or entering COM.
        windows = os.name == 'nt'
        if windows:
            import pythoncom
            import win32event
            import win32api
            pythoncom.CoInitialize()
            try:
                # Windows short names and trailing dots can identify the same
                # directory. All aliases must use the same kernel mutex.
                identity = os.path.normcase(str(storage.resolve()))
                name = "Local\\IllustratorMCP-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                mutex = win32event.CreateMutex(None, False, name)
            except BaseException:
                pythoncom.CoUninitialize()
                raise
        else:
            import fcntl
            mutex = validate_internal_path(storage / 'active.lock').open('a')
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
            with completion_lock:
                if expired.is_set() or time.monotonic() >= deadline:
                    if not read_only:
                        marker().unlink(missing_ok=True)
                    raise TimeoutError("queue_timeout: operation was not dispatched")
                started.set()
            result = function(deadline) if pass_deadline else function()
            with completion_lock:
                # The event loop may not have delivered its timeout callback yet.
                # A late worker return must not clear an unknown-write marker.
                if expired.is_set() or time.monotonic() >= deadline:
                    expired.set()
                    raise TimeoutError("execution_timeout: operation completed after its deadline")
                if recover or not read_only:
                    marker().unlink(missing_ok=True)
            return result
        finally:
            if windows:
                if held:
                    win32event.ReleaseMutex(mutex)
                win32api.CloseHandle(mutex)
                pythoncom.CoUninitialize()
            else:
                if held:
                    fcntl.flock(mutex.fileno(), fcntl.LOCK_UN)
                mutex.close()

    future = _pool.submit(work)
    pending = asyncio.wrap_future(future)
    pending.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    try:
        return await asyncio.wait_for(asyncio.shield(pending), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError, subprocess.TimeoutExpired) as error:
        with completion_lock:
            expired.set()
            future.cancel()
            if started.is_set() and not read_only:
                marker().write_text("outcome_unknown: execution deadline exceeded", encoding="utf-8")
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        if not started.is_set():
            message = "queue_timeout: operation was not dispatched"
        elif read_only:
            message = "execution_timeout: read-only operation exceeded its deadline"
        else:
            message = "outcome_unknown: execution timeout; Adobe may still be running the script"
        failure = TimeoutError(message)
        inspection = getattr(error, 'inspection_path', None) or operation['inspection_path']
        if inspection:
            failure.inspection_path = inspection
            failure.add_note('inspection_path: ' + inspection)
        raise failure from error
