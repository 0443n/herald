import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from herald import Urgency
from herald.receiver import (
    _CONFIG_DEFAULTS,
    Receiver,
    _load_config,
    _parse_notification,
)

# --- Mock helpers ---


def _make_receiver(tmp_path):
    """Create a Receiver with tmp_path as user_dir."""
    r = object.__new__(Receiver)
    r.config = dict(_CONFIG_DEFAULTS)
    r.user_dir = tmp_path
    r.fd = None
    return r


def _ok_run(*args, **kwargs):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")


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
    return _make_receiver(tmp_path)


def test_handle_valid_file_parsed_and_deleted(receiver_setup):
    r = receiver_setup
    p = r.user_dir / "1234.000000_abcd.json"
    p.write_text(json.dumps({"title": "Test"}))

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._handle_file(p)

    assert not p.exists()
    assert mock_run.call_count == 1


def test_handle_malformed_deleted_without_notify(receiver_setup):
    r = receiver_setup
    p = r.user_dir / "bad.json"
    p.write_text("not json{{{")

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._handle_file(p)

    assert not p.exists()
    assert mock_run.call_count == 0


def test_handle_urgency_filter(receiver_setup):
    r = receiver_setup
    r.config["urgency_filter"] = ["critical"]

    p = r.user_dir / "low.json"
    p.write_text(json.dumps({"title": "Low", "urgency": "low"}))

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._handle_file(p)

    assert not p.exists()
    assert mock_run.call_count == 0


# --- Receiver._send_notification ---


def test_notify_builds_correct_command():
    r = _make_receiver(Path("/tmp"))

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._send_notification(
            title="Hello",
            body="World",
            urgency=Urgency.CRITICAL,
            icon="dialog-warning",
            timeout=5000,
        )
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "notify-send"
    assert "--app-name=herald" in cmd
    assert "--urgency=critical" in cmd
    assert "--icon=dialog-warning" in cmd
    assert "--expire-time=5000" in cmd
    assert "Hello" in cmd
    assert "World" in cmd


def test_notify_timeout_override():
    r = _make_receiver(Path("/tmp"))
    r.config["timeout_override"] = 0

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._send_notification(
            title="T",
            body="B",
            urgency=Urgency.NORMAL,
            icon="",
            timeout=5000,
        )
    cmd = mock_run.call_args[0][0]
    assert "--expire-time=0" in cmd


def test_notify_show_body_false():
    r = _make_receiver(Path("/tmp"))
    r.config["show_body"] = False

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._send_notification(
            title="T",
            body="Secret",
            urgency=Urgency.NORMAL,
            icon="",
            timeout=-1,
        )
    cmd = mock_run.call_args[0][0]
    assert "Secret" not in cmd


def test_notify_no_icon_omits_flag():
    r = _make_receiver(Path("/tmp"))

    with patch("subprocess.run", side_effect=_ok_run) as mock_run:
        r._send_notification(
            title="T",
            body="",
            urgency=Urgency.NORMAL,
            icon="",
            timeout=-1,
        )
    cmd = mock_run.call_args[0][0]
    assert not any(arg.startswith("--icon") for arg in cmd)
    assert not any(arg.startswith("--expire-time") for arg in cmd)
