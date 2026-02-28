"""Minimal inotify wrapper using ctypes -- replaces inotify_simple."""

import ctypes
import ctypes.util
import os
import struct
from pathlib import Path
from typing import NamedTuple

_libc_name = ctypes.util.find_library("c")
_libc = ctypes.CDLL(_libc_name, use_errno=True)

_libc.inotify_init1.argtypes = [ctypes.c_int]
_libc.inotify_init1.restype = ctypes.c_int

_libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
_libc.inotify_add_watch.restype = ctypes.c_int

# inotify constants
IN_CLOSE_WRITE: int = 0x00000008
IN_NONBLOCK: int = 0x00000800

_EVENT_HEADER = struct.Struct("iIII")  # wd, mask, cookie, len


class Event(NamedTuple):
    wd: int
    mask: int
    cookie: int
    name: str


def _check(ret: int) -> int:
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))
    return ret


def inotify_init(flags: int = 0) -> int:
    return _check(_libc.inotify_init1(flags))


def add_watch(fd: int, path: Path, mask: int) -> int:
    return _check(_libc.inotify_add_watch(fd, bytes(path), mask))


def read_events(fd: int) -> list[Event]:
    buf = os.read(fd, 8192)
    events: list[Event] = []
    offset = 0
    while offset < len(buf):
        wd, mask, cookie, name_len = _EVENT_HEADER.unpack_from(buf, offset)
        offset += _EVENT_HEADER.size
        name_bytes = buf[offset : offset + name_len]
        offset += name_len
        name = name_bytes.rstrip(b"\x00").decode()
        events.append(Event(wd, mask, cookie, name))
    return events
