FROM python:3.12-slim AS base

LABEL maintainer="fx-smc-bot" \
      description="Forward paper trading service for bos_only_usdjpy"

RUN apt-get update && apt-get install -y --no-install-recommends \
        tini curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir -e .

COPY scripts/ scripts/
COPY configs/ configs/

RUN mkdir -p /data/real /data/live /app/forward_runs

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data/real \
    WATCH_DIR=/data/live \
    OUTPUT_DIR=/app/forward_runs \
    FEED_MODE=file_watch \
    AUTO_RESUME=true

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import json,sys,time; h=json.load(open('/app/forward_runs/health.json')); \
        sys.exit(0 if h.get('status') in ('starting','running','stopped') else 1)" \
        || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "scripts/run_live_forward_service.py"]
