# No model downloads occur when a request arrives. Build once, run offline.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS voice-model-build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/tmp/huggingface HF_HUB_DISABLE_IMPLICIT_TOKEN=1 OMP_NUM_THREADS=2
WORKDIR /build
COPY docs/voice/requirements-converter.txt ./requirements-converter.txt
RUN python -m pip install --no-cache-dir torch==2.9.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements-converter.txt
COPY scripts/build_voice_models.py ./scripts/build_voice_models.py
COPY docs/voice/models.json ./docs/voice/models.json
COPY docs/voice/licenses/ ./licenses/
RUN python scripts/build_voice_models.py --cache /tmp/model-downloads --output /models \
    && cp -r /build/licenses /models/licenses \
    && rm -rf /tmp/model-downloads /tmp/huggingface

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    VOICE_MODEL_PATH_TE=/opt/route-share-models/te \
    VOICE_MODEL_PATH_EN=/opt/route-share-models/en
WORKDIR /app
RUN apt-get update && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-voice.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -r requirements-voice.txt \
    && python -c "import av, ctranslate2, faster_whisper; assert 'int8' in ctranslate2.get_supported_compute_types('cpu')"
COPY --from=voice-model-build /models/ /opt/route-share-models/
# Explicit runtime allowlist. No converter, Torch, tests, mobile, local DBs or review files.
COPY app/ ./app/
COPY static/ ./static/
COPY hosted.py gunicorn.conf.py ./
COPY scripts/backup_store.py ./scripts/backup_store.py
# VOICE_ENABLED is deliberately not set here. Release configuration must opt in.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "hosted:app"]
