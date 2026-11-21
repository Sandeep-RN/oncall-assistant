# Multi-arch image (linux/amd64 + linux/arm64): the production node is an arm64
# A1, CI and laptops are amd64. A slim base keeps both small.
#
# The base is pinned by DIGEST (the multi-arch index, not one platform), so a
# rebuild cannot silently pick up a different image under the same tag. The tag
# is kept in front of the digest so a human can read what it is. Looked up
# 2026-11-22 with `docker buildx imagetools inspect python:3.14-slim`. A digest
# never updates itself: bump it deliberately (or with Dependabot's docker
# ecosystem) and let the Trivy gate in CI judge the new base.
#
# Python 3.14, not 3.15 like the link shortener: ONNX Runtime publishes no
# cp315 wheels yet (docs/adr/0001). Keep in step with python-version in
# ci.yml and target-version in pyproject.toml; move all three together.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

# Links the GHCR package to this repository (permissions, "Connected to repo").
LABEL org.opencontainers.image.source="https://github.com/Sandeep-RN/oncall-assistant"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

# Pull in Debian security fixes the base image has not caught up with yet (Trivy
# gate). Same workaround as the link shortener's image (demo #112, #187): zlib1g
# HIGH CVEs with a fix available. Scoped to one package so builds stay
# predictable. Delete this layer once Trivy passes without it: retest by
# removing it and building. Re-tested 2026-11-22 on this digest (Debian 13.7):
# still needed, Trivy fails on zlib1g CVE-2026-85091 without it. Runs as root,
# before USER, and leaves no apt lists.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pip is removed in the SAME layer as the install, so no layer keeps it. The
# base image's pip vendors its own copies of msgpack, setuptools and urllib3,
# and Trivy fails the build on their HIGH CVEs (demo #187). The app never runs
# pip. If the uninstall ever fails the build stops: a loud failure, never silent.
RUN pip install -r requirements.txt && pip uninstall -y pip

COPY app ./app

# The embedding model (about 130 MB) is baked into the image: nothing is
# downloaded at runtime (docs/adr/0001, ADR 0025). The script fetches a pinned
# Hugging Face revision and refuses any file whose sha256 differs, so a
# tampered download fails the build. It runs after pip is gone because it only
# needs the standard library plus numpy (imported by app.embed.model). The files
# land in /srv/models/..., where the loader looks by default (cwd is /srv).
# Trade-off: this layer is rebuilt when app/ changes, so each such build
# downloads the model again (a few seconds on a runner). Splitting it into its
# own stage would cache it, at the price of listing the files download.py
# imports; not worth it at this size.
RUN python -m app.embed.download

# Non-root with a numeric UID, so Kubernetes runAsNonRoot can verify it.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

# uvicorn reads any of its options from UVICORN_* variables, so
# `docker run -e UVICORN_PORT=8080` changes the port. A command-line flag would
# override the variable, so none is passed.
ENV UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000
EXPOSE 8000
CMD ["uvicorn", "app.main:app"]
