"""Bounded local speech jobs. No audio/transcripts enter storage or application logs."""
from __future__ import annotations

from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import selectors
import socket
import sqlite3
import stat
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from uuid import UUID, uuid4

from werkzeug.formparser import parse_form_data
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

MAX_SECONDS = 45
MAX_BYTES = 2 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_BYTES + 16 * 1024
MAX_TEXT = 4096
TIMEOUT_SECONDS = 75
UPLOAD_SECONDS = 15
IDLE_SECONDS = 60
TOMBSTONE_SECONDS = 120
RATE_WINDOW = 60
RATE_LIMIT = 6
MAX_OWNERS = 256
MAX_IDS = 1024
DEFAULT_DAILY_LIMIT = 100
MAX_DAILY_LIMIT = 1000

_MESSAGES = {
    "VOICE_BUSY": (429, "Voice is busy. Please try again shortly."),
    "VOICE_DAILY_LIMIT": (429, "The daily voice limit has been reached. You can type your trip details or try again after the UTC reset."),
    "VOICE_UNAVAILABLE": (503, "Voice recognition is unavailable. You can enter your trip details."),
    "VOICE_TIMEOUT": (504, "Voice recognition took too long. Please try again."),
    "VOICE_NO_SPEECH": (422, "No clear speech was found. Please record again."),
    "VOICE_INVALID_AUDIO": (400, "Use a valid recording of no more than 45 seconds."),
    "VOICE_CANCELLED": (409, "Voice recognition was cancelled."),
}


class VoiceError(Exception):
    def __init__(self, code, status=None, *, quota=None):
        self.quota = quota if code == "VOICE_DAILY_LIMIT" else None
        self.code = code if code in _MESSAGES else "VOICE_UNAVAILABLE"
        default, message = _MESSAGES[self.code]
        self.status = status or default
        super().__init__(message)


class DailyVoiceQuota:
    """One aggregate document per UTC day: day storage key and count only.

    Uses the application's existing SQLite transaction (BEGIN IMMEDIATE), so
    multiple service instances cannot each consume the final remaining slot.
    No account, session, request ID, audio or transcript is written here.
    """
    COLLECTION = "voice_daily_usage"

    def __init__(self, store, limit=DEFAULT_DAILY_LIMIT, *, clock=None):
        if isinstance(limit, str) and re.fullmatch(r"[0-9]{1,4}", limit.strip()):
            limit = int(limit.strip())
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_DAILY_LIMIT:
            raise ValueError("VOICE_DAILY_LIMIT must be an integer from 1 to 1000")
        self.store, self.limit = store, limit
        self.clock = clock or time.time

    def _window(self):
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return now.date().isoformat(), reset.isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _count(record, day):
        if record is None:
            return 0
        count = record.get("count")
        if record.get("id") != day or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise VoiceError("VOICE_UNAVAILABLE")
        return count

    def snapshot(self):
        try:
            with self.store.read() as tx:
                day, reset = self._window()
                count = self._count(tx.get(self.COLLECTION, day), day)
            return {"daily_remaining": max(0, self.limit - count), "reset_at": reset}
        except sqlite3.Error:
            raise VoiceError("VOICE_UNAVAILABLE") from None

    def consume(self):
        try:
            with self.store.transaction() as tx:
                # Read the UTC date after acquiring the transaction, so a wait
                # across midnight cannot debit an obsolete date.
                day, reset = self._window()
                count = self._count(tx.get(self.COLLECTION, day), day)
                if count >= self.limit:
                    raise VoiceError("VOICE_DAILY_LIMIT", quota={"daily_remaining": 0, "reset_at": reset})
                tx.put(self.COLLECTION, day, {"id": day, "count": count + 1})
        except sqlite3.Error:
            raise VoiceError("VOICE_UNAVAILABLE") from None


def request_id(value):
    if not isinstance(value, str) or len(value) != 36:
        raise VoiceError("VOICE_INVALID_AUDIO")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise VoiceError("VOICE_INVALID_AUDIO") from None
    if str(parsed) != value.lower():
        raise VoiceError("VOICE_INVALID_AUDIO")
    return str(parsed)


class _BoundedUpload(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_BYTES:
            raise VoiceError("VOICE_INVALID_AUDIO", 413)
        return super().write(data)


def parse_upload(environ):
    """Parse only after authentication/admission; never use client filenames."""
    streams = []
    def factory(**_kwargs):
        value = _BoundedUpload()
        streams.append(value)
        return value
    try:
        _, form, files = parse_form_data(environ, stream_factory=factory,
            max_form_memory_size=128 * 1024, max_content_length=MAX_MULTIPART_BYTES,
            max_form_parts=3, silent=False)
        if set(form) != {"language", "request_id"} or set(files) != {"audio"}:
            raise VoiceError("VOICE_INVALID_AUDIO")
        if any(len(form.getlist(k)) != 1 for k in form) or len(files.getlist("audio")) != 1:
            raise VoiceError("VOICE_INVALID_AUDIO")
        language = form["language"]
        if language not in {"en", "te"}:
            raise VoiceError("VOICE_INVALID_AUDIO")
        identity = request_id(form["request_id"])
        data = files["audio"].stream.getvalue()
        if not data:
            raise VoiceError("VOICE_INVALID_AUDIO")
        return identity, language, data
    except RequestEntityTooLarge:
        raise VoiceError("VOICE_INVALID_AUDIO", 413) from None
    except (BadRequest, ValueError, OSError):
        raise VoiceError("VOICE_INVALID_AUDIO") from None
    finally:
        for stream in streams:
            stream.close()


@contextmanager
def bounded_upload(environ, job):
    """Bound a WSGI body read, including a client that continuously drips bytes.

    Production runs on Gunicorn gthread. A timer ends this request's read side;
    no background thread reads audio, and no new inference can start meanwhile.
    """
    stream = environ["wsgi.input"]
    sock = environ.get("gunicorn.socket") or environ.get("werkzeug.socket")
    if sock is None and not isinstance(stream, io.BytesIO):
        # Werkzeug's test client spools larger, already buffered bodies to a
        # regular temporary file. Pipes and unknown network streams fail closed.
        try:
            finite_file = isinstance(stream, (io.BufferedReader, io.BufferedRandom, tempfile.SpooledTemporaryFile)) and stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
        except (AttributeError, OSError, ValueError):
            finite_file = False
        if not finite_file:
            raise VoiceError("VOICE_UNAVAILABLE")
    deadline = min(job.deadline, time.monotonic() + UPLOAD_SECONDS)
    gate, armed = threading.Lock(), [True]
    timed_out = threading.Event()
    previous_timeout = sock.gettimeout() if sock is not None else None

    def interrupt(expired=False):
        with gate:
            if not armed[0]:
                return
            if expired:
                timed_out.set()
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RD)
                except OSError:
                    pass

    def check():
        if job.cancelled.is_set():
            raise VoiceError("VOICE_CANCELLED")
        if timed_out.is_set() or time.monotonic() >= deadline:
            raise VoiceError("VOICE_TIMEOUT")

    class Input:
        def read(self, size=-1):
            check()
            try:
                value = stream.read(min(65536, size) if size >= 0 else 65536)
            except (TimeoutError, OSError):
                check()
                raise VoiceError("VOICE_TIMEOUT") from None
            check()
            return value

        def readinto(self, buffer):
            value = self.read(len(buffer))
            buffer[:len(value)] = value
            return len(value)

    timer = threading.Timer(max(0, deadline - time.monotonic()), lambda: interrupt(True))
    timer.daemon = True
    job.abort_upload = interrupt
    try:
        check()
        if sock is not None:
            sock.settimeout(min(5., max(.01, deadline - time.monotonic())))
        timer.start()
        bounded = dict(environ)
        bounded["wsgi.input"] = Input()
        yield bounded
        check()
    finally:
        with gate:
            armed[0] = False
        timer.cancel()
        job.abort_upload = None
        if sock is not None:
            try:
                sock.settimeout(previous_timeout)
            except OSError:
                pass


class ProcessWorker:
    """Persistent child; bounded pipe reads stay interruptible, never holding service locks."""
    def __init__(self, model_path):
        # Inference has no need for session, database, deployment or provider secrets.
        env = {key: value for key, value in os.environ.items() if key in {
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP", "VIRTUAL_ENV",
            "LD_LIBRARY_PATH", "SYSTEMROOT", "WINDIR",
        }}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   HF_HUB_DISABLE_PROGRESS_BARS="1", TOKENIZERS_PARALLELISM="false",
                   OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
        self.process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("voice_worker.py")), str(model_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, bufsize=0, close_fds=True)
        self._close_lock = threading.Lock()

    def alive(self):
        return self.process.poll() is None

    def close(self):
        with self._close_lock:
            if self.alive():
                self.process.kill()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass

    def transcribe(self, path, language, identity, cancelled, deadline):
        try:
            message = json.dumps({"path": str(path), "language": language, "request_id": identity}) + "\n"
            self.process.stdin.write(message.encode())
            self.process.stdin.flush()
            pending = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                while True:
                    if cancelled.is_set():
                        raise VoiceError("VOICE_CANCELLED")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise VoiceError("VOICE_TIMEOUT")
                    if not selector.select(min(.05, remaining)):
                        if not self.alive():
                            raise VoiceError("VOICE_UNAVAILABLE")
                        continue
                    chunk = os.read(self.process.stdout.fileno(), 4096)
                    if not chunk:
                        raise VoiceError("VOICE_UNAVAILABLE")
                    pending.extend(chunk)
                    if len(pending) > 32 * 1024:
                        raise VoiceError("VOICE_UNAVAILABLE")
                    if b"\n" in pending:
                        line, tail = pending.split(b"\n", 1)
                        if tail:
                            raise VoiceError("VOICE_UNAVAILABLE")
                        return json.loads(line)
        except VoiceError:
            raise
        except (OSError, ValueError, TypeError):
            if cancelled.is_set():
                raise VoiceError("VOICE_CANCELLED") from None
            raise VoiceError("VOICE_UNAVAILABLE") from None


@dataclass
class Job:
    owner: str
    identity: str | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    worker: object | None = None
    directory: Path | None = None
    deadline: float = field(default_factory=lambda: time.monotonic() + TIMEOUT_SECONDS)
    abort_upload: object | None = None


def _cleanup_crashed_roots(base):
    """Delete only our dead-process roots; never another live instance or symlink."""
    for path in base.glob("route-share-voice-*"):
        match = re.fullmatch(r"route-share-voice-(\d+)-[a-f0-9]{32}", path.name)
        if not match or path.is_symlink() or not path.is_dir():
            continue
        try:
            os.kill(int(match[1]), 0)
        except ProcessLookupError:
            shutil.rmtree(path, ignore_errors=True)
        except (PermissionError, OSError):
            pass


class VoiceService:
    def __init__(self, model_path=None, *, store, daily_limit=DEFAULT_DAILY_LIMIT, utc_clock=None, model_paths=None, worker_factory=None, clock=None, temp_base=None):
        self._quota = DailyVoiceQuota(store, daily_limit, clock=utc_clock)
        configured = model_paths if model_paths is not None else {"en": model_path, "te": model_path}
        self.model_paths = {language: Path(path) for language, path in configured.items()
                            if language in {"en", "te"} and path}
        self._factory = worker_factory or ProcessWorker
        self._check_runtime = worker_factory is None
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._active = None
        self._worker = None
        self._worker_key = None
        self._rates = OrderedDict()
        self._ids = OrderedDict()
        base = Path(temp_base or tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        _cleanup_crashed_roots(base)
        self._root = Path(tempfile.mkdtemp(prefix=f"route-share-voice-{os.getpid()}-", dir=base))
        # mkdtemp's random suffix differs from the explicit cleanup ownership shape.
        target = base / f"route-share-voice-{os.getpid()}-{uuid4().hex}"
        self._root.rename(target)
        self._root = target

    def available(self, language=None):
        if language is None:
            return any(self.available(item) for item in ("en", "te"))
        path = self.model_paths.get(language)
        if not path or not path.is_absolute() or not path.is_dir():
            return False
        if not all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
            return False
        if self._check_runtime:
            return all(importlib.util.find_spec(name) is not None for name in ("faster_whisper", "av"))
        return True

    def capabilities(self):
        languages = [item for item in ("en", "te") if self.available(item)]
        return {"available": bool(languages), "languages": languages, "max_seconds": MAX_SECONDS, "max_bytes": MAX_BYTES, **self._quota.snapshot()}

    def _prune(self, now):
        for key, expiry in list(self._ids.items()):
            if expiry <= now:
                del self._ids[key]
        for owner, starts in list(self._rates.items()):
            while starts and starts[0] <= now - RATE_WINDOW:
                starts.popleft()
            if not starts:
                del self._rates[owner]

    def _remember(self, key, now):
        if key not in self._ids and len(self._ids) >= MAX_IDS:
            raise VoiceError("VOICE_BUSY")
        self._ids[key] = now + TOMBSTONE_SECONDS

    @contextmanager
    def reserve(self, owner, identity=None, *, on_admitted=None):
        """Admission before body parsing. No long operation occurs under _lock."""
        if identity is not None:
            identity = request_id(identity)
        if not self.available():
            raise VoiceError("VOICE_UNAVAILABLE")
        with self._lock:
            now = self._clock()
            self._prune(now)
            if identity is not None and (owner, identity) in self._ids:
                raise VoiceError("VOICE_CANCELLED")
            starts = self._rates.get(owner)
            if self._active or (starts is not None and len(starts) >= RATE_LIMIT):
                raise VoiceError("VOICE_BUSY")
            if starts is None:
                if len(self._rates) >= MAX_OWNERS:
                    raise VoiceError("VOICE_BUSY")
                starts = self._rates[owner] = deque()
            starts.append(now)
            job = self._active = Job(owner, identity=identity)
        try:
            # Global/per-account admission already succeeded. Release any caller
            # auth lock before SQLite can wait; never hold _lock during storage.
            if on_admitted is not None:
                on_admitted()
            self._quota.consume()
            self.ensure_current(job)
            yield job
        finally:
            if job.directory:
                shutil.rmtree(job.directory, ignore_errors=True)
            with self._lock:
                if self._active is job:
                    self._active = None

    def ensure_current(self, job):
        if job.cancelled.is_set():
            raise VoiceError("VOICE_CANCELLED")
        if time.monotonic() >= job.deadline:
            raise VoiceError("VOICE_TIMEOUT")

    def _drop_worker(self, worker):
        with self._lock:
            if self._worker is worker:
                self._worker = None
                self._worker_key = None
        if worker:
            worker.close()

    def transcribe(self, job, identity, language, data):
        identity = request_id(identity)
        if language not in {"en", "te"} or not isinstance(data, bytes) or not data:
            raise VoiceError("VOICE_INVALID_AUDIO")
        if len(data) > MAX_BYTES:
            raise VoiceError("VOICE_INVALID_AUDIO", 413)
        if not self.available(language):
            raise VoiceError("VOICE_UNAVAILABLE")
        model_path = self.model_paths[language]
        with self._lock:
            self.ensure_current(job)
            if self._active is not job:
                raise VoiceError("VOICE_CANCELLED")
            if job.identity is not None and job.identity != identity:
                raise VoiceError("VOICE_INVALID_AUDIO")
            now = self._clock()
            self._prune(now)
            key = (job.owner, identity)
            if key in self._ids:
                raise VoiceError("VOICE_CANCELLED")
            self._remember(key, now)
            job.identity = identity
        # The child receives only a private path; filenames supplied by users are ignored.
        deadline = job.deadline
        worker = None
        try:
            job.directory = Path(tempfile.mkdtemp(prefix="job-", dir=self._root))
            path = job.directory / "audio"
            with path.open("xb") as audio:
                os.chmod(path, 0o600)
                audio.write(data)
            self.ensure_current(job)
            with self._lock:
                worker = self._worker
            if worker is not None and (not worker.alive() or self._worker_key != (model_path, language)):
                self._drop_worker(worker)
                worker = None
            if worker is None:
                if time.monotonic() >= deadline:
                    raise VoiceError("VOICE_TIMEOUT")
                worker = self._factory(model_path)
            with self._lock:
                self.ensure_current(job)
                self._worker = worker
                self._worker_key = (model_path, language)
                job.worker = worker
            result = worker.transcribe(path, language, identity, job.cancelled, deadline)
            self.ensure_current(job)
            if not isinstance(result, dict) or result.get("request_id") != identity:
                raise VoiceError("VOICE_UNAVAILABLE")
            if "code" in result:
                code = result["code"]
                if code not in {"VOICE_NO_SPEECH", "VOICE_INVALID_AUDIO", "VOICE_UNAVAILABLE"}:
                    code = "VOICE_UNAVAILABLE"
                raise VoiceError(code, 413 if result.get("status") == 413 else None)
            text = result.get("text")
            duration = result.get("duration_ms")
            if not isinstance(text, str) or len(text) > MAX_TEXT or not isinstance(duration, int) or isinstance(duration, bool) or not 0 < duration <= MAX_SECONDS * 1000:
                raise VoiceError("VOICE_UNAVAILABLE")
            if not text.strip():
                raise VoiceError("VOICE_NO_SPEECH")
            return {"request_id": identity, "text": text.strip(), "language": language, "duration_ms": duration}
        except VoiceError as exc:
            if exc.code not in {"VOICE_NO_SPEECH", "VOICE_INVALID_AUDIO"}:
                self._drop_worker(worker)
            raise
        except Exception:
            self._drop_worker(worker)
            self.ensure_current(job)
            raise VoiceError("VOICE_UNAVAILABLE") from None

    def cancel(self, owner, identity):
        identity = request_id(identity)
        worker, directory, abort = None, None, None
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._remember((owner, identity), now)
            job = self._active
            if job and job.owner == owner and job.identity == identity:
                job.cancelled.set()
                worker, directory, abort = job.worker, job.directory, job.abort_upload
                if self._worker is worker:
                    self._worker = None
                    self._worker_key = None
        if abort:
            abort()
        if worker:
            worker.close()
        if directory:
            shutil.rmtree(directory, ignore_errors=True)
        return {"request_id": identity, "cancelled": True}

    def cancel_owner(self, owner):
        worker, directory, abort = None, None, None
        with self._lock:
            job = self._active
            if job and job.owner == owner:
                job.cancelled.set()
                worker, directory, abort = job.worker, job.directory, job.abort_upload
                if self._worker is worker:
                    self._worker = None
                    self._worker_key = None
        if abort:
            abort()
        if worker:
            worker.close()
        if directory:
            shutil.rmtree(directory, ignore_errors=True)

    def close(self):
        with self._lock:
            abort = None
            if self._active:
                self._active.cancelled.set()
                abort = self._active.abort_upload
            worker, self._worker = self._worker, None
            self._worker_key = None
        if abort:
            abort()
        if worker:
            worker.close()
        shutil.rmtree(self._root, ignore_errors=True)
