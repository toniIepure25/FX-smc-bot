# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="fx-smc-bot forward paper" \
      org.opencontainers.image.description="Legacy, unvalidated forward paper-trading service; not a live-money system." \
      org.opencontainers.image.source="https://github.com/toniIepure25/FX-smc-bot"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data/real \
    WATCH_DIR=/data/live \
    OUTPUT_DIR=/app/forward_runs \
    FEED_MODE=live \
    AUTO_RESUME=true

RUN apt-get update && apt-get install -y --no-install-recommends tini passwd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 fxsmc \
    && useradd --uid 10001 --gid fxsmc --create-home --shell /usr/sbin/nologin fxsmc

WORKDIR /app

# Install the package as a normal wheel; no editable install is needed in the image.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN python -m pip install --no-cache-dir .

COPY --chown=fxsmc:fxsmc scripts/ scripts/
COPY --chown=fxsmc:fxsmc configs/ configs/

RUN mkdir -p /data/real /data/live /app/forward_runs \
    && chown -R fxsmc:fxsmc /app /data

USER fxsmc

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import json,sys; h=json.load(open('/app/forward_runs/health.json')); \
        sys.exit(0 if h.get('status') in ('starting','running','stopped') else 1)"

STOPSIGNAL SIGTERM
ENTRYPOINT ["tini", "--"]
CMD ["python", "scripts/run_live_forward_service.py"]
