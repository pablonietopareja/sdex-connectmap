# syntax=docker/dockerfile:1.7

FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS frontend-builder
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY icons/ /build/icons/
COPY frontend/index.html frontend/vite.config.ts frontend/icon-assets-plugin.ts ./
COPY frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json ./
COPY frontend/src/ ./src/
RUN npm run build


FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS python-builder
WORKDIR /build

COPY backend/requirements.txt ./
RUN python -m pip wheel \
    --require-hashes \
    --disable-pip-version-check \
    --no-cache-dir \
    --wheel-dir /wheels \
    -r requirements.txt


FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

LABEL org.opencontainers.image.title="SDEX ConnectMap" \
      org.opencontainers.image.description="Read-only industrial topology viewer for Softing SDEX Suite" \
      org.opencontainers.image.version="1.0.1" \
      org.opencontainers.image.authors="Pablo Nieto Pareja" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/pablonietopareja/sdex-connectmap"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONNECTMAP_HOST=0.0.0.0 \
    CONNECTMAP_PORT=8080 \
    CONNECTMAP_DATA_DIR=/data \
    CONNECTMAP_DISABLE_DOCS=true \
    CONNECTMAP_STATIC_DIR=/app/frontend/dist

# Apply available security updates within the pinned runtime's Debian release.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 connectmap \
    && useradd --uid 10001 --gid connectmap --no-create-home --shell /usr/sbin/nologin connectmap \
    && mkdir -p /app/backend /app/frontend/dist /data \
    && chown -R connectmap:connectmap /app /data \
    && chmod 0700 /data

# Package installation belongs to the build; keep only the installed runtime dependencies.
RUN --mount=type=bind,from=python-builder,source=/wheels,target=/wheels,ro \
    python -m pip install --no-cache-dir --no-compile /wheels/* \
    && python -m pip uninstall --yes pip \
    && python -c "import pathlib,shutil,sysconfig; shutil.rmtree(pathlib.Path(sysconfig.get_path('stdlib')) / 'ensurepip')" \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12

COPY --chown=connectmap:connectmap backend/app /app/backend/app
COPY --chown=connectmap:connectmap LICENSE THIRD_PARTY_NOTICES.md /app/
COPY --chown=connectmap:connectmap docs/licenses /app/licenses
COPY --from=frontend-builder --chown=connectmap:connectmap /build/frontend/dist /app/frontend/dist

WORKDIR /app/backend
USER 10001:10001
EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import json,os,sys,urllib.request; p=os.getenv('CONNECTMAP_PORT','8080'); r=urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=3); d=json.load(r); ok=d.get('status') in {'healthy','unconfigured'} or (d.get('status') == 'degraded' and d.get('database') == 'ok' and d.get('scheduler') == 'running'); sys.exit(0 if r.status == 200 and ok else 1)"]

STOPSIGNAL SIGTERM
CMD ["python", "-c", "import os,uvicorn; uvicorn.run('app.main:app', host=os.getenv('CONNECTMAP_HOST','0.0.0.0'), port=int(os.getenv('CONNECTMAP_PORT','8080')))"]
