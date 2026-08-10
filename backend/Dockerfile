# Base image Python version must match the venv actually running on
# 192.168.1.41 (confirmed 3.13, matches this tag).
#
# Pinned to a digest, not just the mutable ":3.13-slim" tag. BuildKit always
# resolves a tag against the registry (even when a matching image is already
# cached locally) to check whether the tag now points somewhere else -- that
# resolution step is what was failing on 192.168.1.41 over SSH (Windows
# Credential Manager/DPAPI needs an interactive logon session an SSH-created
# session doesn't have -- see backend/docker-compose.yml/project memory).
# A digest reference is immutable, so BuildKit can match it against the
# local cache directly, no registry contact needed -- this is what actually
# lets `docker compose build` work over SSH for ordinary code-only rebuilds
# going forward. Only re-pulling a genuinely different image (a version
# bump, not this exact digest) needs the console again.
#
# Digest is linux/amd64 for python:3.13-slim, confirmed via Docker Hub's
# API on 2026-08-11: https://hub.docker.com/_/python/tags?name=3.13-slim
# If this ever needs updating, re-check that URL rather than guessing.
FROM python:3.13-slim@sha256:69e18bd8d831d88e0ef70239dc7771ab7c28bc296ae78ac75cde71e60aa4434f

WORKDIR /app

# geopandas/shapely/pyproj normally install as manylinux wheels on slim
# with no system packages needed. If `docker build` shows any of them
# falling back to a source build, uncomment:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#       build-essential libgdal-dev libgeos-dev libproj-dev && \
#     rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# app/ includes app/data/psgc_region10_boundaries.csv (the static PSGC
# lookup) -- one COPY covers app code and that bundled reference file.
COPY app ./app

EXPOSE 8000

# No --reload: this is a deployed service now, not live-edited. A code
# change means git pull + docker compose up --build, matching how this
# project already deploys today.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
