"""Synthetic/local fixtures only; no remote speech service or personal recordings."""
import io
import threading
import time
from uuid import uuid4

import pytest
from werkzeug.test import EnvironBuilder

from app import voice
from app.store import Store
from app.voice import VoiceError, VoiceService, parse_upload


class Worker:
    def __init__(self, _path):
        self.closed = False
        self.calls = 0

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True

    def transcribe(self, path, language, identity, cancelled, deadline):
        assert path.read_bytes() == b"synthetic-audio"
        assert path.stat().st_mode & 0o777 == 0o600
        self.calls += 1
        return {"request_id": identity, "text": "Hyderabad to Vijayawada", "duration_ms": 2000}


@pytest.fixture
def service(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model / name).write_bytes(b"fixture")
    instance = VoiceService(model, store=Store(tmp_path / "usage.sqlite3"), worker_factory=Worker, temp_base=tmp_path / "audio")
    yield instance
    instance.close()


def run(service, owner="alice", identity=None):
    with service.reserve(owner) as job:
        return service.transcribe(job, identity or str(uuid4()), "te", b"synthetic-audio")


def code(expected, callable):
    with pytest.raises(VoiceError) as failure:
        callable()
    assert failure.value.code == expected
    return failure.value


def test_available_is_local_only_and_fast(tmp_path, service):
    missing = VoiceService("relative-model-name", store=Store(tmp_path / "missing.sqlite3"), temp_base=tmp_path)
    try:
        caps = missing.capabilities()
        assert {key: caps[key] for key in ("available", "languages", "max_seconds", "max_bytes")} == {"available": False, "languages": [], "max_seconds": 45, "max_bytes": 2097152}
        assert caps["daily_remaining"] == 100 and caps["reset_at"].endswith("T00:00:00Z")
        code("VOICE_UNAVAILABLE", lambda: run(missing))
        assert service.capabilities()["available"]
        assert service._worker is None
    finally:
        missing.close()


def test_reuses_worker_and_cleans_every_recording(service):
    first, second = run(service), run(service)
    assert first["language"] == "te" and first["duration_ms"] == 2000
    assert first["request_id"] != second["request_id"]
    assert service._worker.calls == 2
    assert list(service._root.iterdir()) == []


def test_rate_and_global_admission_precede_body_work(service):
    with service.reserve("alice"):
        code("VOICE_BUSY", lambda: run(service, "bob"))
    for _ in range(5):
        run(service)
    code("VOICE_BUSY", lambda: run(service))
    run(service, "bob")


def test_cancel_before_registration_is_owner_scoped_idempotent(service):
    identity = str(uuid4())
    assert service.cancel("alice", identity) == service.cancel("alice", identity)
    code("VOICE_CANCELLED", lambda: run(service, identity=identity))
    assert run(service, "bob", identity)["text"]
    assert service._worker.calls == 1


def test_replayed_request_does_not_run_model_twice(service):
    identity = str(uuid4())
    run(service, identity=identity)
    code("VOICE_CANCELLED", lambda: run(service, identity=identity))
    assert service._worker.calls == 1


def test_tombstones_and_rate_state_expire_and_are_bounded(service, monkeypatch):
    now = [10.]
    service._clock = lambda: now[0]
    monkeypatch.setattr(voice, "MAX_IDS", 2)
    first, second = str(uuid4()), str(uuid4())
    service.cancel("alice", first)
    service.cancel("alice", second)
    code("VOICE_BUSY", lambda: service.cancel("bob", str(uuid4())))
    assert len(service._ids) == 2
    now[0] += 121
    run(service, identity=first)
    assert len(service._ids) == 1


class BlockingWorker(Worker):
    started = None
    release = None

    def transcribe(self, path, language, identity, cancelled, deadline):
        self.started.set()
        assert self.release.wait(2), "test hung"
        return super().transcribe(path, language, identity, cancelled, deadline)

    def close(self):
        super().close()
        self.release.set()


def test_cancel_does_not_wait_for_inference_and_other_owner_cannot_cancel(service):
    started, released = threading.Event(), threading.Event()
    BlockingWorker.started, BlockingWorker.release = started, released
    service._factory = BlockingWorker
    identity, errors = str(uuid4()), []
    def background():
        try:
            run(service, identity=identity)
        except VoiceError as exc:
            errors.append(exc.code)
    thread = threading.Thread(target=background)
    thread.start()
    assert started.wait(1)
    service.cancel("bob", identity)
    assert not released.is_set()
    before = time.monotonic()
    service.cancel("alice", identity)
    thread.join(1)
    assert not thread.is_alive() and time.monotonic() - before < 1
    assert errors == ["VOICE_CANCELLED"]
    assert not list(service._root.iterdir())
    assert service._worker is None


def test_owner_logout_during_unregistered_upload_prevents_work(service):
    with service.reserve("alice") as job:
        service.cancel_owner("alice")
        code("VOICE_CANCELLED", lambda: service.transcribe(job, str(uuid4()), "en", b"synthetic-audio"))
    assert service._worker is None


@pytest.mark.parametrize("response,expected", [
    ({"code": "VOICE_NO_SPEECH"}, "VOICE_NO_SPEECH"),
    ({"code": "VOICE_INVALID_AUDIO"}, "VOICE_INVALID_AUDIO"),
    ({"text": "", "duration_ms": 1000}, "VOICE_NO_SPEECH"),
    ({"text": "x", "duration_ms": 45001}, "VOICE_UNAVAILABLE"),
    ({"text": "x", "duration_ms": True}, "VOICE_UNAVAILABLE"),
    ({"text": "x" * 4097, "duration_ms": 1000}, "VOICE_UNAVAILABLE"),
])
def test_worker_results_are_bounded_and_cleanup(service, response, expected):
    class ResultWorker(Worker):
        def transcribe(self, path, language, identity, cancelled, deadline):
            return {"request_id": identity, **response}
    service._factory = ResultWorker
    code(expected, lambda: run(service))
    assert not list(service._root.iterdir())


def test_timeout_kills_and_next_job_restarts(service):
    class TimeoutWorker(Worker):
        def transcribe(self, *args):
            raise VoiceError("VOICE_TIMEOUT")
    service._factory = TimeoutWorker
    code("VOICE_TIMEOUT", lambda: run(service))
    assert service._worker is None and not list(service._root.iterdir())
    service._factory = Worker
    assert run(service)["text"]


def test_cancel_during_worker_creation_closes_new_child(service):
    workers = []
    identity = str(uuid4())
    def factory(path):
        service.cancel("alice", identity)
        value = Worker(path)
        workers.append(value)
        return value
    service._factory = factory
    code("VOICE_CANCELLED", lambda: run(service, identity=identity))
    assert workers[0].closed and not list(service._root.iterdir())


@pytest.mark.parametrize("data,status", [(b"", 400), (b"a" * (voice.MAX_BYTES + 1), 413)])
def test_encoded_limit_and_empty_audio(service, data, status):
    with service.reserve("alice") as job:
        error = code("VOICE_INVALID_AUDIO", lambda: service.transcribe(job, str(uuid4()), "en", data))
        assert error.status == status
    assert service._worker is None


def test_multipart_validates_exact_fields_and_limits_without_disk():
    identity = str(uuid4())
    builder = EnvironBuilder(method="POST", data={"audio": (io.BytesIO(b"fixture"), "../../private.wav"), "language": "te", "request_id": identity})
    assert parse_upload(builder.get_environ()) == (identity, "te", b"fixture")
    builder.close()
    for data in [
        {"audio": (io.BytesIO(b"fixture"), "a.wav"), "language": "hi", "request_id": identity},
        {"audio": (io.BytesIO(b"x" * (voice.MAX_BYTES + 1)), "a.wav"), "language": "en", "request_id": identity},
        {"audio": (io.BytesIO(b"fixture"), "a.wav"), "language": "en", "request_id": "invalid"},
    ]:
        builder = EnvironBuilder(method="POST", data=data)
        code("VOICE_INVALID_AUDIO", lambda: parse_upload(builder.get_environ()))
        builder.close()


def test_startup_cleanup_leaves_live_and_unrelated_paths(tmp_path, monkeypatch):
    import os
    dead = tmp_path / ("route-share-voice-99999999-" + "a" * 32)
    live = tmp_path / (f"route-share-voice-{os.getpid()}-" + "b" * 32)
    unrelated = tmp_path / "route-share-voice-not-ours"
    for directory in (dead, live, unrelated):
        directory.mkdir()
        (directory / "audio").write_bytes(b"fixture")
    voice._cleanup_crashed_roots(tmp_path)
    assert not dead.exists() and live.exists() and unrelated.exists()


def test_real_pipe_timeout_and_cancellation_kill_child(monkeypatch, tmp_path):
    import subprocess
    import sys
    original = subprocess.Popen
    def fixture_process(*_args, **kwargs):
        return original([sys.executable, "-u", "-c", "import sys,time; sys.stdin.readline(); time.sleep(10)"], **kwargs)
    monkeypatch.setattr(voice.subprocess, "Popen", fixture_process)
    for cancelled, deadline, expected in [
        (threading.Event(), time.monotonic() + .03, "VOICE_TIMEOUT"),
        (threading.Event(), time.monotonic() + 1, "VOICE_CANCELLED"),
    ]:
        if expected == "VOICE_CANCELLED":
            cancelled.set()
        worker = voice.ProcessWorker(tmp_path)
        code(expected, lambda: worker.transcribe(tmp_path / "audio", "en", str(uuid4()), cancelled, deadline))
        worker.close()
        assert not worker.alive()


def test_child_idle_exit_without_loading_model(monkeypatch, tmp_path):
    from app import voice_worker
    import sys
    class NoModel:
        def __init__(self, path):
            assert path == tmp_path
        def run(self, *args):
            pytest.fail("idle child must not load a model")
    monkeypatch.setattr(sys, "argv", ["voice_worker", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO()})())
    monkeypatch.setattr(voice_worker, "Recognizer", NoModel)
    waits = []
    monkeypatch.setattr(voice_worker.select, "select", lambda r, w, e, timeout: (waits.append(timeout) or ([], [], [])))
    voice_worker.main()
    assert waits == [60]


def test_cancel_during_tempfile_open_is_cancelled_not_server_error(service, monkeypatch):
    from pathlib import Path
    original = Path.open
    identity = str(uuid4())
    def raced_open(path, *args, **kwargs):
        if path.name == "audio" and args == ("xb",):
            service.cancel("alice", identity)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", raced_open)
    code("VOICE_CANCELLED", lambda: run(service, identity=identity))
    assert not list(service._root.iterdir())


def test_multipart_accepts_exact_encoded_limit():
    builder = EnvironBuilder(method="POST", data={"audio": (io.BytesIO(b"a" * voice.MAX_BYTES), "a.wav"), "language": "en", "request_id": str(uuid4())})
    try:
        assert len(parse_upload(builder.get_environ())[2]) == voice.MAX_BYTES
    finally:
        builder.close()


def test_rate_owner_registry_cannot_grow_without_bound(service, monkeypatch):
    monkeypatch.setattr(voice, "MAX_OWNERS", 2)
    run(service, "alice")
    run(service, "bob")
    code("VOICE_BUSY", lambda: run(service, "charlie"))
    assert len(service._rates) == 2


def test_recognizer_reuses_model_and_rejects_vad_silence(monkeypatch, tmp_path):
    from app import voice_worker
    from types import SimpleNamespace
    monkeypatch.setattr(voice_worker, "decode_audio", lambda _: ([.1], 2000))
    calls = []
    class Model:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            return iter([SimpleNamespace(text="  హైదరాబాద్  ", no_speech_prob=.1)]), SimpleNamespace(duration_after_vad=1.5)
    recognizer = voice_worker.Recognizer(tmp_path)
    recognizer.model = Model()
    for _ in range(2):
        assert recognizer.run(tmp_path / "audio", "te") == {"text": "హైదరాబాద్", "duration_ms": 2000}
    assert len(calls) == 2 and calls[0]["vad_filter"] and calls[0]["condition_on_previous_text"] is False
    class Silence:
        def transcribe(self, *args, **kwargs):
            return iter([]), SimpleNamespace(duration_after_vad=0)
    recognizer.model = Silence()
    with pytest.raises(voice_worker.AudioError) as error:
        recognizer.run(tmp_path / "audio", "te")
    assert error.value.code == "VOICE_NO_SPEECH"


@pytest.mark.parametrize("seconds,silence,expected", [(2, False, None), (45, False, None), (45.1, False, "VOICE_INVALID_AUDIO"), (2, True, "VOICE_NO_SPEECH")])
def test_real_decoder_duration_and_silence_when_runtime_installed(tmp_path, seconds, silence, expected):
    pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    import wave
    from app import voice_worker
    path = tmp_path / "audio.wav"
    samples = round(seconds * 16000)
    pcm = np.zeros(samples, dtype=np.int16) if silence else (np.sin(np.arange(samples) * 2 * np.pi * 220 / 16000) * 6000).astype(np.int16)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm.tobytes())
    if expected:
        with pytest.raises(voice_worker.AudioError) as error:
            voice_worker.decode_audio(path)
        assert error.value.code == expected
    else:
        result, duration = voice_worker.decode_audio(path)
        assert len(result) == samples and duration == round(seconds * 1000)


def test_child_does_not_inherit_application_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("DATABASE_URL", "test-only-database")
    monkeypatch.setenv("VOICE_MODEL_PATH", str(tmp_path))
    captured = {}
    class Child:
        stdin = io.BytesIO()
        stdout = io.BytesIO()
        def poll(self): return 0
        def wait(self, timeout): return 0
    def spawn(args, **kwargs):
        captured.update(kwargs["env"])
        return Child()
    monkeypatch.setattr(voice.subprocess, "Popen", spawn)
    worker = voice.ProcessWorker(tmp_path)
    worker.close()
    assert "SECRET_KEY" not in captured and "DATABASE_URL" not in captured and "VOICE_MODEL_PATH" not in captured
    assert captured["HF_HUB_OFFLINE"] == "1" and captured["OMP_NUM_THREADS"] == "2"


def test_language_switch_replaces_child_before_loading_next(service, tmp_path):
    other = tmp_path / "other-model"
    other.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (other / name).write_bytes(b"fixture")
    service.model_paths["en"] = other
    children = []
    def factory(path):
        assert all(child.closed for child in children)
        child = Worker(path)
        children.append(child)
        return child
    service._factory = factory
    run(service)
    with service.reserve("alice") as job:
        service.transcribe(job, str(uuid4()), "en", b"synthetic-audio")
    assert len(children) == 2 and children[0].closed and not children[1].closed
    assert service.capabilities()["languages"] == ["en", "te"]


def test_header_registration_supports_cancel_while_uploading(service):
    identity = str(uuid4())
    with service.reserve("alice", identity) as job:
        stopped = threading.Event()
        job.abort_upload = stopped.set
        service.cancel("alice", identity)
        assert stopped.is_set() and job.cancelled.is_set()
        code("VOICE_CANCELLED", lambda: service.transcribe(job, identity, "en", b"synthetic-audio"))
    assert service._worker is None


def test_even_same_model_path_switches_child_on_language_change(service):
    run(service)
    first = service._worker
    with service.reserve("alice") as job:
        service.transcribe(job, str(uuid4()), "en", b"synthetic-audio")
    assert first.closed and service._worker is not first


def test_admission_deadline_includes_time_before_inference(service):
    with service.reserve("alice") as job:
        job.deadline = time.monotonic() - .01
        code("VOICE_TIMEOUT", lambda: service.transcribe(job, str(uuid4()), "en", b"synthetic-audio"))
    assert service._worker is None


def test_daily_quota_survives_service_restart_and_contains_no_personal_data(service, tmp_path):
    service._quota.limit = 2
    run(service, owner="private-account-one")
    database = service._quota.store.path
    paths = dict(service.model_paths)
    service.close()
    restarted = VoiceService(store=Store(database), model_paths=paths, daily_limit=2, worker_factory=Worker, temp_base=tmp_path / "restarted")
    try:
        assert restarted.capabilities()["daily_remaining"] == 1
        run(restarted, owner="private-account-two")
        error = code("VOICE_DAILY_LIMIT", lambda: run(restarted, owner="third-account"))
        assert error.status == 429 and error.quota["daily_remaining"] == 0
        assert restarted._active is None
        with Store(database).read() as tx:
            rows = tx.list(voice.DailyVoiceQuota.COLLECTION)
        assert len(rows) == 1 and set(rows[0]) == {"id", "count"} and rows[0]["count"] == 2
        assert len(rows[0]["id"]) == 10  # UTC date, not an account/request identifier.
        assert all("private-account" not in str(row) for row in rows)
    finally:
        restarted.close()


def test_daily_quota_resets_at_exact_utc_midnight(service):
    from datetime import datetime, timezone
    instant = [datetime(2026, 10, 8, 23, 59, 59, 999999, tzinfo=timezone.utc).timestamp()]
    service._quota.clock = lambda: instant[0]
    service._quota.limit = 1
    run(service)
    assert service.capabilities()["daily_remaining"] == 0
    assert service.capabilities()["reset_at"] == "2026-10-09T00:00:00Z"
    instant[0] = datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp()
    assert service.capabilities()["daily_remaining"] == 1
    assert service.capabilities()["reset_at"] == "2026-10-10T00:00:00Z"
    run(service)
    with service._quota.store.read() as tx:
        assert tx.list(voice.DailyVoiceQuota.COLLECTION) == [{"id": "2026-10-08", "count": 1}, {"id": "2026-10-09", "count": 1}]


def test_last_daily_slot_is_atomic_across_service_instances(service, tmp_path):
    service._quota.limit = 1
    other = VoiceService(store=Store(service._quota.store.path), model_paths=service.model_paths, daily_limit=1, worker_factory=Worker, temp_base=tmp_path / "other")
    barrier, outcomes = threading.Barrier(2), []
    def attempt(instance, owner):
        barrier.wait()
        try:
            run(instance, owner)
            outcomes.append("ok")
        except VoiceError as exc:
            outcomes.append(exc.code)
    threads = [threading.Thread(target=attempt, args=(instance, owner)) for instance, owner in [(service, "alice"), (other, "bob")]]
    try:
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        assert all(not thread.is_alive() for thread in threads)
        assert sorted(outcomes) == ["VOICE_DAILY_LIMIT", "ok"]
        assert service.capabilities()["daily_remaining"] == other.capabilities()["daily_remaining"] == 0
        assert service._active is other._active is None
    finally:
        other.close()


def test_cancelled_failed_attempts_count_but_busy_and_pre_cancelled_do_not(service):
    with service.reserve("alice", str(uuid4())) as job:
        service.cancel_owner("alice")
        code("VOICE_CANCELLED", lambda: service.transcribe(job, job.identity, "en", b"synthetic-audio"))
    assert service.capabilities()["daily_remaining"] == 99
    with service.reserve("alice") as job:
        code("VOICE_INVALID_AUDIO", lambda: service.transcribe(job, str(uuid4()), "en", b""))
        code("VOICE_BUSY", lambda: run(service, "bob"))
    assert service.capabilities()["daily_remaining"] == 98
    identity = str(uuid4())
    service.cancel("alice", identity)
    def prior_cancel():
        with service.reserve("alice", identity): pytest.fail("pre-cancelled request admitted")
    code("VOICE_CANCELLED", prior_cancel)
    assert service.capabilities()["daily_remaining"] == 98


def test_quota_failure_releases_slot_and_never_starts_worker(service, monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    @contextmanager
    def fail():
        raise sqlite3.OperationalError("fixture write failure")
        yield
    with monkeypatch.context() as patch:
        patch.setattr(service._quota.store, "transaction", fail)
        code("VOICE_UNAVAILABLE", lambda: run(service))
        assert service._active is None and service._worker is None
    assert service.capabilities()["daily_remaining"] == 100
    assert run(service)["text"]


def test_quota_read_failure_does_not_advertise_available(service, monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    @contextmanager
    def fail():
        raise sqlite3.OperationalError("fixture read failure")
        yield
    monkeypatch.setattr(service._quota.store, "read", fail)
    code("VOICE_UNAVAILABLE", service.capabilities)


def test_quota_wait_does_not_hold_manager_lock_and_cancelled_admission_counts(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service._quota.consume
    def waiting():
        entered.set()
        assert release.wait(2)
        original()
    monkeypatch.setattr(service._quota, "consume", waiting)
    identity, outcomes = str(uuid4()), []
    def background():
        try:
            with service.reserve("alice", identity): pytest.fail("cancelled reservation yielded")
        except VoiceError as exc: outcomes.append(exc.code)
    thread = threading.Thread(target=background)
    thread.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        service.cancel("alice", identity)
        assert time.monotonic() - started < .5
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and outcomes == ["VOICE_CANCELLED"]
    assert service.capabilities()["daily_remaining"] == 99 and service._active is None


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "unbounded", "100000000000000000"])
def test_daily_configuration_is_bounded(service, limit):
    with pytest.raises(ValueError, match="VOICE_DAILY_LIMIT"):
        voice.DailyVoiceQuota(service._quota.store, limit)
