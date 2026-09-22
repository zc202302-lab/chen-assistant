from __future__ import annotations

import ctypes
import sys


class SingleInstance:
    def __init__(self, name: str = "Local\\win-assistants") -> None:
        self.handle = None
        self.already_running = False
        if sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        create_mutex.restype = ctypes.c_void_p
        self.handle = create_mutex(None, False, name)
        self.already_running = kernel32.GetLastError() == 183

    def close(self) -> None:
        if self.handle and sys.platform == "win32":
            close_handle = ctypes.windll.kernel32.CloseHandle
            close_handle.argtypes = (ctypes.c_void_p,)
            close_handle.restype = ctypes.c_bool
            close_handle(self.handle)
            self.handle = None
