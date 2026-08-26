FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim

# yt-dlp requires Node >=22 for YouTube's external JS challenges.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        libchromaprint-tools \
        unzip \
        unrar-free \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt
COPY app /app/app

RUN useradd -u 1000 -m appuser \
    && mkdir -p /music /downloads \
    && chown -R appuser:appuser /app /music /downloads
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
