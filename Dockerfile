# ── Stage 1: Build the React SPA ─────────────────────────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /app

# Install JS deps first so this layer is cached independently of source changes.
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

# Copy source and build.
# vite.config.ts has outDir: '../api/static', so from /app/frontend the output
# lands at /app/api/static — exactly where FastAPI expects the SPA.
COPY frontend/ ./frontend/
RUN mkdir -p api/static && cd frontend && npm run build


# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# git            — required by C3a (git clone / git pull via subprocess)
# build-essential — gcc + g++ + make; needed by numpy/scipy (no Python 3.13 wheels for 1.26.x)
# gfortran        — Fortran compiler required by numpy/scipy meson build
# python3-dev     — CPython headers for any extension that compiles against them
# ca-certificates — TLS to GitHub, Anthropic API
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    gfortran \
    python3-dev \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy uv from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies before copying application source so Docker can
# cache this layer when only source files change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source.
COPY . .

# Bring in the built SPA from the frontend stage.
COPY --from=frontend /app/api/static ./api/static

# Install the project itself into the venv created above.
RUN uv sync --frozen --no-dev

# Pre-create the directories used for runtime data so volume mounts land cleanly.
RUN mkdir -p /app/db /app/cache

# ── Runtime configuration ──────────────────────────────────────────────────────
# Bind to all interfaces inside the container; compose/k8s controls external exposure.
ENV MERIDIAN_HOST=0.0.0.0
ENV MERIDIAN_PORT=8000
# Point the repo cache at the dedicated volume path (overrides the in-tree default).
ENV CACHE_ROOT=/app/cache

EXPOSE 8000

# Single worker — SQLite serialises writes; multiple workers would require WAL
# mode tuning and an external lock, which is out of scope for the embedded DB model.
CMD ["uv", "run", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
