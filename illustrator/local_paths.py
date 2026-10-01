"""Validate MCP runtime/storage paths; arbitrary user JSX is not restricted."""
from contextlib import contextmanager
from contextvars import ContextVar
import ctypes
import ntpath
import os
from pathlib import Path
import posixpath
import re
import stat
import subprocess
import sys


_checks = ContextVar('illustrator_local_path_checks', default=None)
_MAC_LOCAL = {'apfs', 'hfs', 'ufs', 'msdos', 'exfat', 'cd9660', 'udf', 'ntfs'}
_LINUX_LOCAL = {
    'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs', 'tmpfs', 'ramfs', 'overlay',
    'vfat', 'exfat', 'ntfs', 'ntfs3', 'iso9660', 'udf', 'squashfs',
}


def _fail(detail):
    raise RuntimeError('local_path_required: ' + detail)


@contextmanager
def local_path_context():
    """Reuse mount metadata for one operation, never across tool calls."""
    if _checks.get() is not None:
        yield
        return
    token = _checks.set({'mounts': None, 'drives': {}})
    try:
        yield
    finally:
        _checks.reset(token)


def _syntax(value, platform=None):
    platform = platform or sys.platform
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        _fail('internal storage needs a non-empty absolute local path')
    if value.startswith(('//', '\\\\')) or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value) and not re.match(r'^[a-zA-Z]:[\\/]', value):
        _fail('URLs, UNC paths and device paths are not internal local storage')
    paths = ntpath if platform == 'win32' else posixpath
    if not paths.isabs(value) or platform == 'win32' and not re.match(r'^[a-zA-Z]:[\\/]', value):
        _fail('internal storage needs an absolute local path')


def _mount_path(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def _mac_mounts(output):
    entries = []
    for line in output.splitlines():
        if not line:
            continue
        try:
            before, flags = line.rsplit(' (', 1)
        except ValueError:
            _fail('could not parse the local mount table')
        if not flags.endswith(')'):
            _fail('could not parse the local mount table')
        # Fail closed when a source/path makes the human-readable separator
        # ambiguous, rather than accidentally overlooking a network mount.
        candidates = [before[index + 4:] for index in range(len(before))
                      if before.startswith(' on ', index) and before[index + 4:].startswith('/')]
        if len(candidates) != 1:
            _fail('could not unambiguously identify a filesystem mount')
        entries.append((_mount_path(candidates[0]), flags[:-1].split(',', 1)[0].strip().lower()))
    if not entries:
        _fail('could not identify the filesystem mounts')
    return entries


def _linux_mounts(output):
    entries = []
    for line in output.splitlines():
        try:
            fields, filesystem = line.split(' - ', 1)
            entries.append((_mount_path(fields.split()[4]), filesystem.split()[0]))
        except (ValueError, IndexError):
            _fail('could not parse the local mount table')
    if not entries:
        _fail('could not identify the filesystem mounts')
    return entries


def _drive_type(root):
    # GetDriveType classifies a drive without opening a file on that drive.
    function = ctypes.windll.kernel32.GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint
    return function(root)


def _assert_mounted_locally(value):
    context = _checks.get()
    if sys.platform == 'win32':
        drive = ntpath.splitdrive(value)[0].upper()
        try:
            kind = context['drives'].get(drive) if context else None
            if kind is None:
                kind = _drive_type(drive + '\\')
                if context is not None:
                    context['drives'][drive] = kind
        except Exception as error:
            raise RuntimeError('local_path_required: could not classify the internal storage drive') from error
        if kind not in (2, 3, 5, 6):
            _fail('network or unknown drives are not internal local storage')
        return
    entries = context['mounts'] if context else None
    if entries is None:
        try:
            if sys.platform == 'darwin':
                result = subprocess.run(['/sbin/mount'], capture_output=True, text=True, check=True, timeout=5)
                entries = _mac_mounts(result.stdout)
            elif sys.platform.startswith('linux'):
                # Allows local mock/stdio tests on Linux; the Adobe backend
                # remains Windows/macOS-only.
                entries = _linux_mounts(Path('/proc/self/mountinfo').read_text())
            else:
                _fail('this platform cannot verify internal local storage')
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError('local_path_required: could not verify filesystem mounts') from error
        if context is not None:
            context['mounts'] = entries
    matches = [(root, kind) for root, kind in entries
               if value == root or value.startswith(root.rstrip('/') + '/')]
    if not matches:
        _fail('could not identify the internal storage filesystem')
    root, kind = max(matches, key=lambda entry: len(entry[0]))
    local = _MAC_LOCAL if sys.platform == 'darwin' else _LINUX_LOCAL
    if kind not in local:
        _fail('network or unknown filesystems are not internal local storage')


def validate_internal_path(value, *, reject_leaf_link=True):
    """Check a mount before lstat; check each link target before following it."""
    value = os.fspath(value)
    _syntax(value)
    paths = ntpath if sys.platform == 'win32' else posixpath
    absolute = paths.normpath(value)
    links = 0
    with local_path_context():
        while True:
            _syntax(absolute)
            _assert_mounted_locally(absolute)
            drive, tail = paths.splitdrive(absolute)
            root = drive + paths.sep if drive else paths.sep
            components = tail.lstrip('\\/').split(paths.sep)
            if sys.platform == 'win32':
                components = tail.lstrip('\\/').replace('/', '\\').split('\\')
            components = [component for component in components if component]
            current = root
            for index, component in enumerate(components):
                current = paths.join(current, component)
                _assert_mounted_locally(current)
                try:
                    info = os.lstat(current)
                except FileNotFoundError:
                    return Path(absolute)
                except OSError as error:
                    raise RuntimeError('local_path_required: could not inspect internal storage') from error
                reparse = getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
                if stat.S_ISLNK(info.st_mode) or reparse:
                    if reject_leaf_link and index == len(components) - 1:
                        _fail('internal storage files/directories must not be links')
                    links += 1
                    if links > 40:
                        _fail('too many links in internal storage')
                    try:
                        target = os.readlink(current)
                    except OSError as error:
                        raise RuntimeError('local_path_required: unknown reparse point in internal storage') from error
                    if sys.platform == 'win32' and re.match(r'^\\\\\?\\[a-zA-Z]:\\', target):
                        target = target[4:]
                    # A relative symlink is allowed only after its absolute
                    # destination has passed the mount/drive checks.
                    if target.startswith(('//', '\\\\')) or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) and not re.match(r'^[a-zA-Z]:[\\/]', target):
                        _fail('internal storage links must not target a network/device path')
                    absolute = paths.normpath(paths.join(paths.dirname(current), target, *components[index + 1:]))
                    break
                if index < len(components) - 1 and not stat.S_ISDIR(info.st_mode):
                    _fail('an internal storage parent is not a directory')
            else:
                return Path(absolute)


def prepare_directory(value):
    """Validation precedes mkdir, including an existing ancestor's links."""
    with local_path_context():
        path = validate_internal_path(value)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        verified = validate_internal_path(path)
        if not stat.S_ISDIR(os.lstat(verified).st_mode):
            _fail('internal storage is not a directory')
        return verified


def configured_storage_path(kind, environment=None):
    default = Path.home() / '.illustrator-mcp' / kind
    return os.environ.get(environment, str(default)) if environment else str(default)


def storage_directory(kind, environment=None):
    return prepare_directory(configured_storage_path(kind, environment))


def validate_runtime_paths(installation_directory, python_executable):
    """Validate startup configuration without creating any storage directory."""
    with local_path_context():
        installation = validate_internal_path(installation_directory)
        interpreter = validate_internal_path(python_executable, reject_leaf_link=False)
        try:
            if not stat.S_ISDIR(os.lstat(installation).st_mode):
                _fail('the MCP installation path is not a directory')
            if not stat.S_ISREG(os.lstat(interpreter).st_mode):
                _fail('the Python executable path is not a regular local file')
        except OSError as error:
            raise RuntimeError('local_path_required: could not inspect the MCP runtime installation') from error
        paths = {'installation': installation, 'python': interpreter}
        for kind, environment in (('scripts', 'ILLUSTRATOR_SCRIPT_DIR'),
                                  ('safety', 'ILLUSTRATOR_SAFETY_DIR'),
                                  ('preview', None)):
            path = validate_internal_path(configured_storage_path(kind, environment))
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                pass  # A safe missing root is created only when its tool needs it.
            except OSError as error:
                raise RuntimeError('local_path_required: could not inspect internal storage configuration') from error
            else:
                if not stat.S_ISDIR(info.st_mode):
                    _fail('internal storage configuration is not a directory')
            paths[kind] = path
        return paths


def safe_owned_tree(path):
    """Do not let recursive recovery descend through links or remote mounts."""
    pending = [Path(path)]
    try:
        with local_path_context():
            while pending:
                current = validate_internal_path(pending.pop())
                info = os.lstat(current)
                if stat.S_ISDIR(info.st_mode):
                    pending.extend(Path(entry.path) for entry in os.scandir(current))
        return True
    except (OSError, RuntimeError):
        return False
