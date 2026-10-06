FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# Explicit runtime allowlist. No tests, mobile project, local DBs, or review files.
COPY app/ ./app/
COPY static/ ./static/
COPY hosted.py gunicorn.conf.py ./

CMD ["gunicorn", "--config", "gunicorn.conf.py", "hosted:app"]
