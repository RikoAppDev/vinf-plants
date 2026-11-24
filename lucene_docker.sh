#!/bin/bash
# Run one module of the project in the PyLucene image coady/pylucene (native on amd64 and arm64).
#
#   ./lucene_docker.sh lucene_index.build
#   ./lucene_docker.sh lucene_index.search "quercus NOT robur"
#   ./lucene_docker.sh lucene_index.compare
#   ./lucene_docker.sh unittest tests.test_lucene_index
#   LUCENE_PORT=8080 ./lucene_docker.sh lucene_index.web      then open http://localhost:8080
#
# The project is mounted at /vinf, so relative paths mean the same files as on the host.
# LUCENE_PORT publishes that port on localhost only and names the container vinf-lucene-web
# (stop it with Ctrl+C or docker stop vinf-lucene-web); lucene_index.web listens on the same port.
set -e
cd "$(dirname "$0")"
IMAGE=coady/pylucene:latest
PUBLISH=()
if [ -n "$LUCENE_PORT" ]; then
  PUBLISH=(-p "127.0.0.1:$LUCENE_PORT:$LUCENE_PORT" -e LUCENE_PORT="$LUCENE_PORT" --name vinf-lucene-web)
fi
exec docker run --rm --init \
  -v "$PWD":/vinf -w /vinf \
  -e PYTHONIOENCODING=utf-8 -e PYTHONDONTWRITEBYTECODE=1 \
  "${PUBLISH[@]}" \
  "$IMAGE" \
  python3 tools/run_module.py "$@"
