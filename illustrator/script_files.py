"""Owned script directories; reclaim dead owners only after explicit recovery."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile


def script_root():
    path = Path(os.environ.get('ILLUSTRATOR_SCRIPT_DIR', str(Path(tempfile.gettempdir()) / 'illustrator-mcp-scripts')))
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise RuntimeError('unsafe_script_directory: links are not allowed')
    return path.resolve()


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
    with tempfile.TemporaryDirectory(prefix=f'call-{os.getpid()}-', dir=root) as directory:
        path = Path(directory)
        (path/'owner.json').write_text(json.dumps({'kind':'illustrator-mcp-script','pid':os.getpid()}), encoding='utf-8')
        script = path/'script.jsx'
        script.write_text(code, encoding='utf-8')
        yield str(script)


def cleanup_stale_scripts():
    """Call only after a successful Adobe state read, under the application mutex."""
    root = script_root()
    removed = 0
    for path in root.glob('call-*'):
        if not path.is_dir() or path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            continue
        resolved = path.resolve()
        if resolved.parent != root:
            continue
        try:
            owner = json.loads((resolved/'owner.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        pid = owner.get('pid')
        if (owner.get('kind') != 'illustrator-mcp-script' or type(pid) is not int or pid <= 0
                or not path.name.startswith(f'call-{pid}-') or owner_alive(pid)):
            continue
        # Resolved target is a direct child of our owned root, never a drive/user root.
        shutil.rmtree(resolved)
        removed += 1
    return removed
