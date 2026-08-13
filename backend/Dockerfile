# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

# Build tooling for any sdist-only deps (most have wheels, but keep the safety net).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (pinned via the official installer; pulls a static binary).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

WORKDIR /app

# Resolve dependencies first (cached layer; only invalidated when lock changes).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then copy the project source and install the project itself.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY static/ ./static/
COPY docs/ ./docs/
RUN uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# curl is needed for HEALTHCHECK; libgomp1 covers scikit-learn/scipy OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Bring the venv and the application source over from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/static /app/static
COPY --from=builder --chown=app:app /app/docs /app/docs

# Build identity for GET /version. Declared last so it never invalidates the
# dependency/source layers above. Railway builds this service with nixpacks and
# stamps app/build_info.json instead (see scripts/ops/deploy_backend.sh); this
# arg is the equivalent for plain `docker build`:
#   docker build --build-arg BUILD_COMMIT_SHA="$(git rev-parse HEAD)" .
ARG BUILD_COMMIT_SHA=""
ENV BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA}

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/livez || exit 1

# SECURITY: never use --forwarded-allow-ips=*. `*` sets uvicorn's always_trust
# flag, which makes it take the LEFTMOST X-Forwarded-For entry -- a value any
# client can forge -- as request.client.host, defeating every IP-based rate
# limit and poisoning audit records. The explicit private/loopback set below
# keeps always_trust off, so uvicorn walks X-Forwarded-For in reverse and
# returns the real client IP appended by the edge proxy. The edge reaches this
# container over the internal network, and no external client can originate
# from a private source address.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips=127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fd00::/8"]
