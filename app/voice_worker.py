"""Private local ASR child. Invoked by VoiceService; never exposes an HTTP server."""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import select
import sys

MAX_SECONDS = 45
SAMPLE_RATE = 16000
MAX_SAMPLES = MAX_SECONDS * SAMPLE_RATE
MAX_TEXT = 4096
IDLE_SECONDS = 60


class AudioError(Exception):
    def __init__(self, code="VOICE_INVALID_AUDIO"):
        self.code = code
        super().__init__(code)


def decode_audio(path):
    """Decode incrementally; bound decoded duration before accumulating PCM."""
    import av
    import numpy as np

    parts, samples, source_seconds = [], 0, 0.0

    def append(frame):
        nonlocal samples
        if frame is None:
            return
        samples += frame.samples
        if samples > MAX_SAMPLES:
            raise AudioError()
        value = frame.to_ndarray().reshape(-1)
        if value.size != frame.samples or not np.isfinite(value).all():
            raise AudioError()
        parts.append(value)

    try:
        # A file object, an allowlist of audio container formats, and no URL protocols.
        # This excludes playlist/concat demuxers that can dereference external files.
        with open(path, "rb") as source, av.open(source, mode="r", options={
            "format_whitelist": "wav,mp3,mov,matroska,webm,ogg,flac,aac",
            "protocol_whitelist": "file,pipe",
            "enable_drefs": "0", "use_absolute_path": "0",
        }) as container:
            if len(container.streams.audio) != 1:
                raise AudioError()
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                rate = frame.sample_rate
                if not rate or rate < 8000 or rate > 192000 or len(frame.layout.channels) > 8:
                    raise AudioError()
                source_seconds += frame.samples / rate
                if source_seconds > MAX_SECONDS + 1e-6:
                    raise AudioError()
                for converted in resampler.resample(frame):
                    append(converted)
            for converted in resampler.resample(None):
                append(converted)
    except AudioError:
        raise
    except Exception:
        raise AudioError() from None
    if not samples:
        raise AudioError()
    pcm = np.concatenate(parts).astype(np.float32, copy=False)
    # Reject digital silence before model loading. VAD then checks for speech.
    if float(np.max(np.abs(pcm))) < .0001 or float(np.sqrt(np.mean(pcm * pcm))) < .00005:
        raise AudioError("VOICE_NO_SPEECH")
    return pcm, max(1, round(samples * 1000 / SAMPLE_RATE))


class Recognizer:
    def __init__(self, model_path):
        self.model_path = model_path
        self.model = None

    def run(self, path, language):
        pcm, duration_ms = decode_audio(path)
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(str(self.model_path), device="cpu", compute_type="int8",
                cpu_threads=2, num_workers=1, local_files_only=True)
        segments, info = self.model.transcribe(pcm, language=language, task="transcribe",
            beam_size=3, condition_on_previous_text=False, temperature=0,
            vad_filter=True, vad_parameters={"min_speech_duration_ms": 250, "min_silence_duration_ms": 500})
        if not math.isfinite(info.duration_after_vad) or info.duration_after_vad < .25:
            raise AudioError("VOICE_NO_SPEECH")
        texts, total = [], 0
        for segment in segments:
            text = segment.text.strip()
            # Whisper can emit text from noise. Discard segments it considers silence.
            if segment.no_speech_prob > .6:
                continue
            total += len(text) + 1
            if total > MAX_TEXT:
                raise AudioError()
            if text:
                texts.append(text)
        text = " ".join(texts).strip()
        if not text:
            raise AudioError("VOICE_NO_SPEECH")
        return {"text": text, "duration_ms": duration_ms}


def main():
    logging.disable(logging.CRITICAL)
    if len(sys.argv) != 2:
        return
    model_path = Path(sys.argv[1])
    if not model_path.is_absolute() or not model_path.is_dir():
        return
    recognizer = Recognizer(model_path)
    while True:
        # Idle exit releases model memory; the next admitted job starts a fresh child.
        if not select.select([sys.stdin.buffer], [], [], IDLE_SECONDS)[0]:
            return
        line = sys.stdin.buffer.readline(4097)
        if not line or len(line) > 4096 or not line.endswith(b"\n"):
            return
        identity = None
        try:
            value = json.loads(line)
            identity = value["request_id"]
            language = value["language"]
            path = Path(value["path"])
            if language not in {"en", "te"} or not isinstance(identity, str) or len(identity) != 36:
                return
            if not path.is_absolute() or path.name != "audio" or not path.parent.name.startswith("job-") or not path.parent.parent.name.startswith("route-share-voice-") or path.is_symlink():
                return
            result = recognizer.run(path, language)
        except AudioError as exc:
            result = {"code": exc.code}
        except Exception:
            result = {"code": "VOICE_UNAVAILABLE"}
        result["request_id"] = identity
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
