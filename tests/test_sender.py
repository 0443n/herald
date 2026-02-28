import json
import pwd
import re

import pytest

import herald
from herald import Urgency
from herald.sender import _ensure_dir, resolve_recipients, send


@pytest.fixture(autouse=True)
def _redirect_base_dir(tmp_path, monkeypatch):
    """Point BASE_DIR at a temp directory for all tests."""
    from pathlib import Path

    monkeypatch.setattr(herald, "BASE_DIR", Path(tmp_path))
    monkeypatch.setattr(herald.sender, "BASE_DIR", Path(tmp_path))


def _fake_pw(name, uid=1000, gid=1000, shell="/bin/bash"):
    """Build a minimal pwd.struct_passwd."""
    return pwd.struct_passwd((name, "x", uid, gid, "", f"/home/{name}", shell))


# --- resolve_recipients ---


def test_resolve_valid_users(monkeypatch):
    monkeypatch.setattr(pwd, "getpwnam", lambda n: _fake_pw(n))
    result = resolve_recipients(users=["alice", "bob"])
    assert {pw.pw_name for pw in result} == {"alice", "bob"}


def test_resolve_invalid_user_skipped(monkeypatch):
    def lookup(n):
        if n == "ghost":
            raise KeyError(n)
        return _fake_pw(n)

    monkeypatch.setattr(pwd, "getpwnam", lookup)
    result = resolve_recipients(users=["alice", "ghost"])
    assert [pw.pw_name for pw in result] == ["alice"]


def test_resolve_all_invalid_raises(monkeypatch):
    monkeypatch.setattr(pwd, "getpwnam", lambda n: (_ for _ in ()).throw(KeyError(n)))
    with pytest.raises(ValueError, match="No valid recipients"):
        resolve_recipients(users=["ghost"])


def test_resolve_groups(monkeypatch):
    import grp

    monkeypatch.setattr(
        grp,
        "getgrnam",
        lambda g: grp.struct_group(("devs", "x", 100, ["alice", "bob"])),
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda n: _fake_pw(n))

    result = resolve_recipients(groups=["devs"])
    assert {pw.pw_name for pw in result} == {"alice", "bob"}


def test_resolve_everyone_filters_by_uid(monkeypatch):
    all_users = [
        _fake_pw("root", uid=0, shell="/bin/bash"),
        _fake_pw("nobody", uid=65534, shell="/usr/sbin/nologin"),
        _fake_pw("alice", uid=1000, shell="/bin/bash"),
        _fake_pw("bob", uid=1001, shell="/bin/zsh"),
        _fake_pw("svc", uid=999, shell="/bin/bash"),
    ]
    monkeypatch.setattr(pwd, "getpwall", lambda: all_users)

    result = resolve_recipients(everyone=True)
    names = {pw.pw_name for pw in result}
    assert names == {"alice", "bob", "nobody"}


def test_resolve_everyone_includes_existing_dirs(tmp_path, monkeypatch):
    (tmp_path / "charlie").mkdir()
    monkeypatch.setattr(pwd, "getpwall", lambda: [
        _fake_pw("alice", uid=1000),
    ])
    monkeypatch.setattr(pwd, "getpwnam", lambda n: _fake_pw(n))

    result = resolve_recipients(everyone=True)
    names = {pw.pw_name for pw in result}
    assert "alice" in names
    assert "charlie" in names


def test_resolve_dedup(monkeypatch):
    monkeypatch.setattr(pwd, "getpwnam", lambda n: _fake_pw(n))
    result = resolve_recipients(users=["alice", "alice", "alice"])
    assert len(result) == 1


def test_resolve_no_mode_raises():
    with pytest.raises(ValueError, match="No targeting mode"):
        resolve_recipients()


def test_resolve_conflicting_modes_raises():
    with pytest.raises(ValueError, match="Only one targeting mode"):
        resolve_recipients(users=["alice"], everyone=True)


# --- _ensure_dir ---


def test_ensure_dir_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)
    pw = _fake_pw("alice")
    user_dir = _ensure_dir(pw)
    assert user_dir.is_dir()


def test_ensure_dir_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)
    pw = _fake_pw("alice")
    _ensure_dir(pw)
    _ensure_dir(pw)


# --- send ---


def test_send_writes_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)

    pw = _fake_pw("alice")
    count = send(title="Hello", body="World", recipients=[pw])
    assert count == 1

    user_dir = tmp_path / "alice"
    files = [f for f in user_dir.iterdir() if f.suffix == ".json"]
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["title"] == "Hello"
    assert data["body"] == "World"
    assert data["urgency"] == "normal"


def test_send_invalid_urgency_raises(monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)

    pw = _fake_pw("alice")
    with pytest.raises(ValueError, match="Invalid urgency"):
        send(title="Hi", urgency=Urgency.from_string("extreme"), recipients=[pw])


def test_send_multiple_recipients(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)

    users = [_fake_pw("alice"), _fake_pw("bob", uid=1001)]
    count = send(title="Alert", recipients=users)
    assert count == 2

    for name in ("alice", "bob"):
        files = list((tmp_path / name).glob("*.json"))
        assert len(files) == 1


def test_send_filename_format(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.chown", lambda *a, **kw: None)

    pw = _fake_pw("alice")
    send(title="Test", recipients=[pw])

    files = list((tmp_path / "alice").glob("*.json"))
    assert len(files) == 1
    assert re.match(r"\d+\.\d{6}_[0-9a-f]{4}\.json", files[0].name)
