import json
from pathlib import Path

import pytest

from herald import Urgency
from herald.receiver import (
    _CONFIG_DEFAULTS,
    _handle_file,
    _load_config,
    _parse_notification,
    _rotate_history,
    _send_notification,
)

# --- Mock helpers ---

# D-Bus MessageType.METHOD_RETURN == 2
_METHOD_RETURN = 2


class _MockReply:
    def __init__(self):
        self.message_type = _METHOD_RETURN
        self.body = [0]


class _MockBus:
    def __init__(self):
        self.calls = []

    async def call(self, msg):
        self.calls.append(msg)
        return _MockReply()


# --- _parse_notification ---


def test_parse_valid_full(tmp_path):
    p = tmp_path / "note.json"
    p.write_text(json.dumps({
        "title": "Hello",
        "body": "World",
        "urgency": "critical",
        "icon": "dialog-warning",
        "timeout": 0,
    }))
    data = _parse_notification(p)
    assert data["title"] == "Hello"
    assert data["body"] == "World"
    assert data["urgency"] is Urgency.CRITICAL
    assert data["icon"] == "dialog-warning"
    assert data["timeout"] == 0


def test_parse_minimal_defaults(tmp_path):
    p = tmp_path / "note.json"
    p.write_text(json.dumps({"title": "Just a title"}))
    data = _parse_notification(p)
    assert data["title"] == "Just a title"
    assert data["body"] == ""
    assert data["urgency"] is Urgency.NORMAL
    assert data["icon"] == ""
    assert data["timeout"] == -1


def test_parse_missing_title(tmp_path):
    p = tmp_path / "note.json"
    p.write_text(json.dumps({"body": "no title here"}))
    assert _parse_notification(p) is None


def test_parse_invalid_json(tmp_path):
    p = tmp_path / "note.json"
    p.write_text("not json at all{{{")
    assert _parse_notification(p) is None


def test_parse_invalid_urgency_defaults_to_normal(tmp_path):
    p = tmp_path / "note.json"
    p.write_text(json.dumps({"title": "Test", "urgency": "extreme"}))
    data = _parse_notification(p)
    assert data["urgency"] is Urgency.NORMAL


# --- _rotate_history ---


def test_rotate_under_limit(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.json").touch()
    _rotate_history(tmp_path, 5)
    assert len(list(tmp_path.iterdir())) == 3


def test_rotate_over_limit_deletes_oldest(tmp_path):
    for i in range(5):
        (tmp_path / f"{i:04d}.json").touch()
    _rotate_history(tmp_path, 3)
    remaining = sorted(f.name for f in tmp_path.iterdir())
    assert remaining == ["0002.json", "0003.json", "0004.json"]


def test_rotate_empty_dir(tmp_path):
    _rotate_history(tmp_path, 10)


# --- _load_config ---


def test_config_no_file_returns_defaults(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent")))
    config = _load_config()
    assert config == _CONFIG_DEFAULTS


def test_config_partial_merge(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config" / "herald"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_text("max_history = 50\nshow_body = false\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    config = _load_config()
    assert config["max_history"] == 50
    assert config["show_body"] is False
    assert config["timeout_override"] is None


def test_config_invalid_toml_returns_defaults(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config" / "herald"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_text("not valid toml [[[")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    config = _load_config()
    assert config == _CONFIG_DEFAULTS


# --- _handle_file ---


@pytest.fixture()
def read_setup(tmp_path):
    read_dir = tmp_path / ".read"
    read_dir.mkdir()
    config = dict(_CONFIG_DEFAULTS)
    return tmp_path, read_dir, config


@pytest.mark.asyncio
async def test_handle_valid_file_parsed_and_moved(read_setup):
    tmp_path, read_dir, config = read_setup
    p = tmp_path / "1234.000000_abcd.json"
    p.write_text(json.dumps({"title": "Test"}))

    bus = _MockBus()
    await _handle_file(p, bus, read_dir, config)

    assert not p.exists()
    assert (read_dir / p.name).exists()
    assert len(bus.calls) == 1


@pytest.mark.asyncio
async def test_handle_malformed_moved_without_notify(read_setup):
    tmp_path, read_dir, config = read_setup
    p = tmp_path / "bad.json"
    p.write_text("not json{{{")

    bus = _MockBus()
    await _handle_file(p, bus, read_dir, config)

    assert not p.exists()
    assert (read_dir / p.name).exists()
    assert len(bus.calls) == 0


@pytest.mark.asyncio
async def test_handle_urgency_filter(read_setup):
    tmp_path, read_dir, config = read_setup
    config["urgency_filter"] = ["critical"]

    p = tmp_path / "low.json"
    p.write_text(json.dumps({"title": "Low", "urgency": "low"}))

    bus = _MockBus()
    await _handle_file(p, bus, read_dir, config)

    assert not p.exists()
    assert (read_dir / p.name).exists()
    assert len(bus.calls) == 0


# --- _send_notification ---


@pytest.mark.asyncio
async def test_notify_correct_dbus_message():
    bus = _MockBus()
    config = dict(_CONFIG_DEFAULTS)
    await _send_notification(
        bus,
        title="Hello",
        body="World",
        urgency=Urgency.CRITICAL,
        icon="dialog-warning",
        timeout=5000,
        config=config,
    )
    assert len(bus.calls) == 1
    msg = bus.calls[0]
    assert msg.member == "Notify"
    assert msg.body[0] == "herald"
    assert msg.body[3] == "Hello"
    assert msg.body[4] == "World"
    assert msg.body[6]["urgency"].value == 2
    assert msg.body[7] == 5000


@pytest.mark.asyncio
async def test_notify_timeout_override():
    bus = _MockBus()
    config = dict(_CONFIG_DEFAULTS)
    config["timeout_override"] = 0
    await _send_notification(
        bus,
        title="T",
        body="B",
        urgency=Urgency.NORMAL,
        icon="",
        timeout=5000,
        config=config,
    )
    msg = bus.calls[0]
    assert msg.body[7] == 0


@pytest.mark.asyncio
async def test_notify_show_body_false():
    bus = _MockBus()
    config = dict(_CONFIG_DEFAULTS)
    config["show_body"] = False
    await _send_notification(
        bus,
        title="T",
        body="Secret",
        urgency=Urgency.NORMAL,
        icon="",
        timeout=-1,
        config=config,
    )
    msg = bus.calls[0]
    assert msg.body[4] == ""
