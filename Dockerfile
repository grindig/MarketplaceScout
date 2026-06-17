# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Run as UID/GID 1000 so bind-mounted json/ state stays writable for the
# common Linux desktop/server user. Compose can override the numeric user if a
# deployment needs a different host UID/GID.
RUN groupadd --gid 1000 app \
    && useradd \
        --uid 1000 \
        --gid app \
        --home-dir /app \
        --shell /usr/sbin/nologin \
        --no-create-home \
        app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . ./
RUN mkdir -p /app/json \
    && chown -R app:app /app

USER app:app

# Docker's default SIGTERM would bypass the existing KeyboardInterrupt shutdown
# path. SIGINT lets discord.py close cleanly and flush pending seen IDs.
STOPSIGNAL SIGINT

CMD ["python", "main.py"]
