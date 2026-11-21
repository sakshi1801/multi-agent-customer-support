FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed_cache ANONYMIZED_TELEMETRY=False

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the small embedding model into the image so the first request does not download it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY app ./app
COPY data/kb ./data/kb

# Run as an unprivileged user (uid 1000 also suits Hugging Face Spaces). Only /srv/data is writable.
RUN useradd -m -u 1000 app && mkdir -p /srv/data && chown -R app /srv/data /opt/fastembed_cache
USER app

ENV DB_PATH=/srv/data/support.db CHECKPOINT_PATH=/srv/data/checkpoints.db KB_DIR=/srv/data/kb \
    SUPERVISOR_MODE=plan PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
