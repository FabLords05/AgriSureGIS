# Base image Python version must match the venv actually running on
# 192.168.1.41 -- confirm via `python --version` there first (see the
# SSH handoff sequence) before trusting this tag. Swap it if the remote
# venv is on a different minor version.
FROM python:3.13-slim

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
