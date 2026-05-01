FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for packages that need to compile C extensions (lxml, psycopg2, pyzbar, ...).
COPY requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libxml2-dev \
        libxslt1-dev \
        libjpeg-dev \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
    && apt-get install -y --no-install-recommends \
        libzbar0 \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        libpq5 \
        libssl3 \
        libffi8 \
        ffmpeg \
        ca-certificates \
    && pip install -r /tmp/requirements.txt \
    && apt-get purge -y --auto-remove \
        build-essential \
        libpq-dev \
        libxml2-dev \
        libxslt1-dev \
        libjpeg-dev \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app

# The user's `bot.py` is mounted at /app/bot.py at runtime; /app/data is writable.
CMD ["python", "-u", "/app/bot.py"]
