import json
from pathlib import Path

import pytest

from herald import Urgency
from herald.receiver import (
    _CONFIG_DEFAULTS,
    Receiver,
    _load_config,
    _parse_notification,
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


# --- _load_config ---


def test_config_no_file_returns_defaults(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent")))
    config = _load_config()
    assert config == _CONFIG_DEFAULTS


def test_config_partial_merge(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config" / "herald"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_text("show_body = false\n")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    config = _load_config()
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


# --- Receiver._handle_file ---


@pytest.fixture()
def receiver_setup(tmp_path):
    """Create a Receiver with a mock bus and tmp_path as user_dir."""
    r = object.__new__(Receiver)
    r.config = dict(_CONFIG_DEFAULTS)
    r.user_dir = tmp_path
    r.bus = _MockBus()
    r.fd = None
    return r


@pytest.mark.asyncio
async def test_handle_valid_file_parsed_and_deleted(receiver_setup):
    r = receiver_setup
    p = r.user_dir / "1234.000000_abcd.json"
    p.write_text(json.dumps({"title": "Test"}))

    await r._handle_file(p)

    assert not p.exists()
    assert len(r.bus.calls) == 1


@pytest.mark.asyncio
async def test_handle_malformed_deleted_without_notify(receiver_setup):
    r = receiver_setup
    p = r.user_dir / "bad.json"
    p.write_text("not json{{{")

    await r._handle_file(p)

    assert not p.exists()
    assert len(r.bus.calls) == 0


@pytest.mark.asyncio
async def test_handle_urgency_filter(receiver_setup):
    r = receiver_setup
    r.config["urgency_filter"] = ["critical"]

    p = r.user_dir / "low.json"
    p.write_text(json.dumps({"title": "Low", "urgency": "low"}))

    await r._handle_file(p)

    assert not p.exists()
    assert len(r.bus.calls) == 0


# --- Receiver._send_notification ---


@pytest.mark.asyncio
async def test_notify_correct_dbus_message():
    r = object.__new__(Receiver)
    r.config = dict(_CONFIG_DEFAULTS)
    r.bus = _MockBus()

    await r._send_notification(
        title="Hello",
        body="World",
        urgency=Urgency.CRITICAL,
        icon="dialog-warning",
        timeout=5000,
    )
    assert len(r.bus.calls) == 1
    msg = r.bus.calls[0]
    assert msg.member == "Notify"
    assert msg.body[0] == "herald"
    assert msg.body[3] == "Hello"
    assert msg.body[4] == "World"
    assert msg.body[6]["urgency"].value == 2
    assert msg.body[7] == 5000


@pytest.mark.asyncio
async def test_notify_timeout_override():
    r = object.__new__(Receiver)
    r.config = dict(_CONFIG_DEFAULTS)
    r.config["timeout_override"] = 0
    r.bus = _MockBus()

    await r._send_notification(
        title="T",
        body="B",
        urgency=Urgency.NORMAL,
        icon="",
        timeout=5000,
    )
    msg = r.bus.calls[0]
    assert msg.body[7] == 0


@pytest.mark.asyncio
async def test_notify_show_body_false():
    r = object.__new__(Receiver)
    r.config = dict(_CONFIG_DEFAULTS)
    r.config["show_body"] = False
    r.bus = _MockBus()

    await r._send_notification(
        title="T",
        body="Secret",
        urgency=Urgency.NORMAL,
        icon="",
        timeout=-1,
    )
    msg = r.bus.calls[0]
    assert msg.body[4] == ""
