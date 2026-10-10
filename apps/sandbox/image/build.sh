#!/bin/sh
# Builds the sandbox image the service runs agent code in.
# Usage: sh apps/sandbox/image/build.sh   (any cwd)
set -eu
cd "$(dirname "$0")"
TAG="${SANDBOX_IMAGE:-yearbook-sandbox:latest}"
echo "building $TAG from $(pwd)/Dockerfile"
docker build --pull=false -t "$TAG" .
docker image inspect "$TAG" --format 'built {{.RepoTags}} id={{.Id}} size={{.Size}} bytes'
