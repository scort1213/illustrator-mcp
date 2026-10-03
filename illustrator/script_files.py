"""Owned script directories; reclaim uncertain calls after explicit recovery."""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile

try:
    from .local_paths import storage_directory, validate_internal_path, safe_owned_tree
    from . import safety
except ImportError:
    from local_paths import storage_directory, validate_internal_path, safe_owned_tree
    import safety

logger = logging.getLogger(__name__)


def script_root():
    return storage_directory('scripts', 'ILLUSTRATOR_SCRIPT_DIR')


@contextmanager
def owned_directory(root, prefix, *, retain_on_error=False, retain=None, on_retain=None):
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    failed = False
    try:
        validate_internal_path(path)
        yield path
    except BaseException as error:
        failed = True
        if retain_on_error:
            error.inspection_path = str(path)
            error.add_note('inspection_path: ' + str(path))
        raise
    finally:
        if (failed and retain_on_error) or (retain is not None and retain()):
            if on_retain is not None:
                try:
                    on_retain(path)
                except (OSError, RuntimeError):
                    logger.warning('Could not mark retained script directory as complete: %s', path)
            logger.warning('Retained script directory for explicit inspection/recovery: %s', path)
        elif safe_owned_tree(path):
            shutil.rmtree(path)
        else:
            logger.warning('Retained temporary directory whose local ownership could not be verified: %s', path)


def owner_alive(pid):
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import win32api
        import win32process
        import pywintypes
        handle = None
        try:
            handle = win32api.OpenProcess(0x1000, False, pid)
            return win32process.GetExitCodeProcess(handle) == 259
        except pywintypes.error as error:
            # Access denied and other uncertain states are treated as live.
            return error.winerror != 87
        finally:
            if handle is not None:
                handle.Close()
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def script_file(code):
    root = script_root()
    retained = False
    path = None
    owner = {'kind':'illustrator-mcp-script','pid':os.getpid()}
    def mark_retained(directory):
        nonlocal retained
        retained = True
        owner.update({'inspection_required':True,'completed':True})
        validate_internal_path(directory/'owner.json').write_text(json.dumps(owner), encoding='utf-8')
    try:
        with owned_directory(root, prefix=f'call-{os.getpid()}-', retain_on_error=True,
                             retain=safety.should_retain_script, on_retain=mark_retained) as path:
            safety.script_directory_started(path)
            (path/'owner.json').write_text(json.dumps(owner), encoding='utf-8')
            script = path/'script.jsx'
            script.write_text(code, encoding='utf-8')
            yield str(script)
    finally:
        if path is not None:
            safety.script_directory_finished(path, retained=retained)


def cleanup_stale_scripts():
    """Call only after a successful Adobe state read, under the application mutex."""
    root = script_root()
    removed = 0
    for path in root.glob('call-*'):
        try:
            resolved = validate_internal_path(path)
        except (RuntimeError, OSError):
            continue
        if not resolved.is_dir() or resolved.parent != root:
            continue
        try:
            owner_path = validate_internal_path(resolved/'owner.json')
            owner = json.loads(owner_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, RuntimeError):
            continue
        if not isinstance(owner, dict):
            continue
        pid = owner.get('pid')
        completed_retained = owner.get('completed') is True and owner.get('inspection_required') is True
        if (owner.get('kind') != 'illustrator-mcp-script' or type(pid) is not int or not 0 < pid <= 0xFFFFFFFF
                or not path.name.startswith(f'call-{pid}-') or owner_alive(pid) and not completed_retained):
            continue
        # Resolved target is a direct child of our owned root, never a drive/user root.
        if safe_owned_tree(resolved):
            shutil.rmtree(resolved)
            removed += 1
    return removed
