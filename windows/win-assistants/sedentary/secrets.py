from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _windows_apis():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def save_windows_secret(path: Path, value: str) -> None:
    """Use Windows DPAPI so only the current Windows account can decrypt it."""
    if not value:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    if sys.platform != "win32":
        return
    crypt32, kernel32 = _windows_apis()
    raw, keepalive = _blob(value.encode("utf-8"))
    encrypted = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(raw), "RTSP password", None, None, None, 0,
        ctypes.byref(encrypted),
    ):
        raise ctypes.WinError()
    try:
        temp = path.with_suffix(".tmp")
        temp.write_bytes(ctypes.string_at(encrypted.pbData, encrypted.cbData))
        os.replace(temp, path)
    finally:
        kernel32.LocalFree(ctypes.cast(encrypted.pbData, ctypes.c_void_p))
        del keepalive


def load_windows_secret(path: Path) -> str:
    if sys.platform != "win32" or not path.exists():
        return ""
    crypt32, kernel32 = _windows_apis()
    encrypted, keepalive = _blob(path.read_bytes())
    decrypted = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(encrypted), None, None, None, None, 0,
        ctypes.byref(decrypted),
    ):
        return ""
    try:
        return ctypes.string_at(decrypted.pbData, decrypted.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(ctypes.cast(decrypted.pbData, ctypes.c_void_p))
        del keepalive
