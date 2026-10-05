"""Lease the permanent relay during capture/compare/clear.

Windows denies concurrent writes and replacement while the handle is held. POSIX
flock is cooperative only; the supported production consumer is Windows. These
are filesystem locks, not a distributed transaction across sync-service replicas.
"""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def relay_lease(path: Path):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # GENERIC_READ|WRITE, FILE_SHARE_READ, OPEN_EXISTING; deny writes/deletion.
        handle = create(str(path.resolve()), 0xC0000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except Exception:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, 'r+b') as stream:
            yield stream
    else:
        import fcntl
        with path.open('r+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield stream


def capture_relay(path: Path, max_bytes: int = 5 * 1024 * 1024) -> bytes:
    with relay_lease(path) as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError('任务文件不能超过5 MB')
    return payload


def clear_if_unchanged(path: Path, expected: bytes, empty: bytes) -> bool:
    with relay_lease(path) as stream:
        # Compare and clear the same handle under one lease, never reopen by name.
        if stream.read(len(expected) + 1) != expected:
            return False
        stream.seek(0)
        stream.write(empty)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    return True
