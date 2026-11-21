# Multi-arch image (linux/amd64 + linux/arm64): the production node is an arm64
# A1, CI and laptops are amd64. A slim base keeps both small.
#
# The base is pinned by DIGEST (the multi-arch index, not one platform), so a
# rebuild cannot silently pick up a different image under the same tag. The tag
# is kept in front of the digest so a human can read what it is. Looked up
# 2026-11-22 with `docker buildx imagetools inspect python:3.15-slim`. A digest
# never updates itself: bump it deliberately (or with Dependabot's docker
# ecosystem) and let the Trivy gate in CI judge the new base.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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

# TODO(#4): the embedding model files (ONNX) are built into the image here, in
# their own layer before `COPY app`, so a code change does not re-copy them.
# Nothing is downloaded at runtime (ADR 0025: the app has 384Mi and a fixed
# egress story). Add the step when #4 lands the model and its loader.

# Non-root with a numeric UID, so Kubernetes runAsNonRoot can verify it.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

# uvicorn reads any of its options from UVICORN_* variables, so
# `docker run -e UVICORN_PORT=8080` changes the port. A command-line flag would
# override the variable, so none is passed.
ENV UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000
EXPOSE 8000
CMD ["uvicorn", "app.main:app"]
