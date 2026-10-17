"""Windows startup cleanup must probe process state without sending signals."""
import os
import subprocess
import sys

import pytest

from app import voice


@pytest.mark.parametrize(
    "probe_result,should_remain",
    [(False, False), (True, True)],
    ids=["confirmed-dead", "live"],
)
def test_windows_cleanup_uses_probe_and_preserves_live_roots(
    tmp_path, monkeypatch, probe_result, should_remain
):
    pid = 987654321
    root = tmp_path / (f"route-share-voice-{pid}-" + "a" * 32)
    root.mkdir()
    monkeypatch.setattr(voice.sys, "platform", "win32")
    monkeypatch.setattr(voice, "_windows_pid_is_alive", lambda _pid: probe_result)

    def forbidden_kill(*_args, **_kwargs):
        pytest.fail("Windows cleanup must not call os.kill as a liveness probe")

    monkeypatch.setattr(voice.os, "kill", forbidden_kill)
    voice._cleanup_crashed_roots(tmp_path)
    assert root.exists() is should_remain


@pytest.mark.parametrize("probe_error", [OSError("access denied"), RuntimeError("unknown")])
def test_windows_cleanup_preserves_root_when_probe_is_uncertain(tmp_path, monkeypatch, probe_error):
    pid = 987654321
    root = tmp_path / (f"route-share-voice-{pid}-" + "b" * 32)
    root.mkdir()
    monkeypatch.setattr(voice.sys, "platform", "win32")

    def uncertain(_pid):
        raise probe_error

    monkeypatch.setattr(voice, "_windows_pid_is_alive", uncertain)
    monkeypatch.setattr(voice.os, "kill", lambda *_args: pytest.fail("os.kill must not run on Windows"))
    voice._cleanup_crashed_roots(tmp_path)
    assert root.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process API only")
def test_windows_process_probe_reports_current_process_alive():
    assert voice._windows_pid_is_alive(os.getpid()) is True


@pytest.mark.parametrize("pid", [0, -1, 0x100000000, True, "123"])
def test_windows_process_probe_preserves_invalid_pid_roots(pid):
    assert voice._windows_pid_is_alive(pid) is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process API only")
def test_windows_process_probe_detects_exited_child():
    # Only query a child we created; no process receives a signal.
    with subprocess.Popen([sys.executable, "-c", "pass"]) as child:
        assert child.wait(timeout=10) == 0
        assert voice._windows_pid_is_alive(child.pid) is False
