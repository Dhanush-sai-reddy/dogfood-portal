# One stage, one worker, no runtime network. Every dependency ships a wheel for
# amd64 and aarch64, so --only-binary=:all: means the build never needs a
# compiler or a source fetch.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DOGFOOD_DATABASE_URL=sqlite+pysqlite:////data/dogfood.db \
    DOGFOOD_FIXTURES=/app/fixtures.json \
    DOGFOOD_HOST=0.0.0.0 \
    DOGFOOD_PORT=8080

WORKDIR /app

# --require-hashes rejects a yanked or re-uploaded artifact that happens to
# carry the right version, which a version pin alone would accept. The hash set
# was compiled with --universal, so an arm64 laptop builds the same image.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt

COPY app ./app
COPY fixtures.json ./fixtures.json

# chown before USER. A named volume mounted at /data inherits the image's
# ownership, and a non-root user that cannot write /data fails at boot with
# "unable to open database file" — the single most common first-run failure.
RUN mkdir -p /data && chown -R 10001:10001 /app /data
USER 10001

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=4s --start-period=20s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

# --workers 1 is a correctness requirement, not a tuning knob. The SQLite write
# path and the id generator are only single-loop-atomic under one worker:
# SQLite serialises writers per file, and two processes reading the same
# AUTOINCREMENT high-water mark will hand out the same id. Do not "scale" this
# to --workers 4. More throughput here needs a different database, not more
# processes.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
