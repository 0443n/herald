import struct

from herald.inotify import IN_CLOSE_WRITE, IN_NONBLOCK, Event, read_events


def test_constants():
    assert IN_CLOSE_WRITE == 0x00000008
    assert IN_NONBLOCK == 0x00000800


def test_read_events_parses_binary_struct(tmp_path, monkeypatch):
    """Construct a raw inotify_event and verify read_events parses it."""
    name = b"test.json\x00\x00\x00"  # padded to 12 bytes (multiple of 4)
    header = struct.pack("iIII", 1, IN_CLOSE_WRITE, 0, len(name))
    raw = header + name

    import os

    monkeypatch.setattr(os, "read", lambda fd, n: raw)

    events = read_events(42)
    assert len(events) == 1
    assert events[0] == Event(wd=1, mask=IN_CLOSE_WRITE, cookie=0, name="test.json")


def test_read_events_multiple(monkeypatch):
    """Parse two events from a single buffer."""
    events_data = []
    for i, fname in enumerate([b"a.json\x00\x00", b"b.json\x00\x00"]):
        header = struct.pack("iIII", i + 1, IN_CLOSE_WRITE, 0, len(fname))
        events_data.append(header + fname)
    raw = b"".join(events_data)

    import os

    monkeypatch.setattr(os, "read", lambda fd, n: raw)

    events = read_events(42)
    assert len(events) == 2
    assert events[0].name == "a.json"
    assert events[1].name == "b.json"
