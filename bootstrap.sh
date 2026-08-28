#!/usr/bin/env bash
# Clone every repo this stack builds from as a sibling of this one, so
# `docker compose` (dev branch, or docker-compose.build.yml) can build each
# from its own directory.
set -euo pipefail

ORG="${ORG:-smart-home-ia-sample}"
HOST="${GIT_HOST:-github.com}"
PARENT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REPOS=(
  sh-common
  sh-frontend
  sh-bff
  sh-bfa
  sh-orchestrator
  sh-agent-security
  sh-agent-environment
  sh-agent-energy
  sh-mcp
  sh-device-sim
)

for r in "${REPOS[@]}"; do
  if [ -d "$PARENT/$r/.git" ]; then
    echo "== $r (pull)"; git -C "$PARENT/$r" pull --ff-only
  else
    echo "== $r (clone)"; git -C "$PARENT" clone "git@$HOST:$ORG/$r.git"
  fi
done

echo
echo "done. now:  cp .env.example .env  &&  docker compose up --build -d"
