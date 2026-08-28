#!/usr/bin/env bash
# Clone every service repo as a sibling of this one, so `docker compose` can
# build each from its own directory.
set -euo pipefail

ORG="${ORG:?set ORG to your GitHub org, e.g. ORG=my-org ./bootstrap.sh}"
HOST="${GIT_HOST:-github.com}"
PARENT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REPOS=(
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
