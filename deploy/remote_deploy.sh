#!/bin/bash
# Runs ON the EC2 instance: GitHub Actions calls it through AWS SSM Run Command after it has
# reset the checkout to the commit being deployed. It can also be run by hand:
#
#   sudo bash deploy/remote_deploy.sh <git-sha>
#
# <git-sha> is a commit whose images CI published to the GitHub Container Registry:
#   ghcr.io/abduiiahkhaiid/lumber-spine-ai-{api,worker,web-prod}:<git-sha>   (public, no login)
#
# Steps (nothing running is touched until step 3):
#   1. deploy/runtime.env from SSM Parameter Store (deploy/sync_secrets.sh, fail-closed)
#   2. model checkpoints from S3 (MODELS_S3_URI, optional) into backend/model, and the images
#   3. swap containers (seconds of downtime), wait for /ready, check /health reports <git-sha>
#   4. on failure: roll back to the last commit that passed (deploy/.deployed_sha)
#
# Exit: 0 deployed | 1 failed before changing anything, or failed and rolled back | 2 service down
set -euo pipefail

# A rollback resets the checkout, which rewrites this file while bash is reading it: run a copy.
if [[ -z "${_DEPLOY_COPY:-}" ]]; then
  _REPO="$(cd "$(dirname "$0")/.." && pwd)"
  _COPY="$(mktemp /tmp/remote_deploy.XXXXXX.sh)"
  cp "$0" "$_COPY"
  _DEPLOY_COPY="$_COPY" REPO_DIR="$_REPO" exec bash "$_COPY" "$@"
fi
trap 'rm -f -- "${_DEPLOY_COPY}"' EXIT

SHA="${1:?usage: remote_deploy.sh <git-sha>}"
cd "$REPO_DIR"
ENV_FILE="deploy/runtime.env"
STATE_FILE="deploy/.deployed_sha"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")
READY_ATTEMPTS="${READY_ATTEMPTS:-72}" # x 5 s = 6 min (the worker loads the models first)

echo "== deploying ${SHA:0:12}"
free -m | sed -n '1,3p'
df -h / | tail -1

# ------------------------------------------------------------------------------- helpers
env_value() { sed -nE "s/^$1=(.*)$/\1/p" "$ENV_FILE" | tail -1 | sed -E "s/^['\"]|['\"]$//g"; }

set_env() { # set_env KEY VALUE
  if grep -q "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}

git_as_owner() { # the checkout belongs to ubuntu; SSM runs this script as root
  if id ubuntu > /dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
    sudo -u ubuntu git -C "$REPO_DIR" "$@"
  else
    git -C "$REPO_DIR" "$@"
  fi
}

image_prefix() {
  local prefix
  prefix="$(env_value IMAGE_PREFIX)"
  echo "${prefix:-ghcr.io/abduiiahkhaiid/lumber-spine-ai}"
}

pull_images() { # pull_images <tag>: skip what is already here (rollbacks, CI rehearsal)
  local prefix ref
  prefix="$(image_prefix)"
  for ref in "${prefix}-api:$1" "${prefix}-worker:$1" "${prefix}-web-prod:$1"; do
    docker image inspect "$ref" > /dev/null 2>&1 && continue
    echo "   pulling ${ref}"
    docker pull --quiet "$ref" > /dev/null || {
      echo "!! cannot pull ${ref}. Is the package public (GitHub -> Packages -> Package settings)?"
      return 1
    }
  done
}

start_and_verify() { # start_and_verify <sha>
  local want="$1" i health
  "${COMPOSE[@]}" up -d --remove-orphans || return 1
  echo "== waiting for /ready (API, Redis, worker with models loaded)"
  for i in $(seq 1 "$READY_ATTEMPTS"); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/ready > /dev/null 2>&1; then
      health="$(curl -fsS --max-time 5 http://127.0.0.1:8000/health || true)"
      echo "== ready after ~$((i * 5)) s: ${health}"
      [[ "$health" == *"\"commit\":\"${want}\""* ]] \
        || { echo "!! /health does not report ${want}"; return 1; }
      curl -fsS --max-time 10 -o /dev/null http://127.0.0.1:3000/ \
        || { echo "!! the web app does not answer"; return 1; }
      "${COMPOSE[@]}" ps --status running --services | grep -qx caddy \
        || { echo "!! Caddy (HTTPS) is not running"; "${COMPOSE[@]}" logs --tail 30 caddy; return 1; }
      return 0
    fi
    sleep 5
  done
  echo "!! not ready after $((READY_ATTEMPTS * 5)) s"
  "${COMPOSE[@]}" ps || true
  "${COMPOSE[@]}" logs --tail 60 api worker web || true
  return 1
}

prune_images() { # keep the images of the current and the previous release
  local keep_a="$1" keep_b="${2:-}" prefix ref tag
  prefix="$(image_prefix)"
  docker images --format '{{.Repository}}:{{.Tag}}' | grep "^${prefix}-" | while read -r ref; do
    tag="${ref##*:}"
    [[ "$tag" == "$keep_a" || "$tag" == "$keep_b" ]] || docker rmi "$ref" > /dev/null 2>&1 || true
  done
  docker image prune -f > /dev/null || true
}

# ------------------------------------------------------------------------------- 0. previous
PREV=""
[[ -f "$STATE_FILE" ]] && PREV="$(tr -d '[:space:]' < "$STATE_FILE")"
echo "== previous release: ${PREV:-none}"

# ------------------------------------------------------------------------------- 1. settings
echo "== 1/4 settings"
bash deploy/sync_secrets.sh

# ------------------------------------------------------------------------------- 2. models + images
echo "== 2/4 models and images (the running version keeps serving)"
mkdir -p backend/model
MODELS_S3_URI="$(env_value MODELS_S3_URI)"
if [[ -n "$MODELS_S3_URI" ]]; then
  aws s3 sync "${MODELS_S3_URI%/}/" backend/model/ --only-show-errors --exclude "*" \
    --include "*.pt" --include "*.pth" --include "*.onnx" --include "*.json" \
    || { echo "!! could not download the models from ${MODELS_S3_URI}: nothing was changed"; exit 1; }
else
  echo "   MODELS_S3_URI not set: using the files already in backend/model"
fi
find backend/model -maxdepth 1 -type f -printf "   %f  %s bytes\n"
if ! pull_images "$SHA"; then
  echo "!! the images of ${SHA:0:12} are not available: nothing was changed"
  exit 1
fi
set_env IMAGE_TAG "$SHA"

# ------------------------------------------------------------------------------- 3. start
echo "== 3/4 starting ${SHA:0:12}"
if start_and_verify "$SHA"; then
  echo "$SHA" > "$STATE_FILE"
  prune_images "$SHA" "$PREV"
  "${COMPOSE[@]}" ps
  echo "== 4/4 done"
  echo "DEPLOY_OK ${SHA}"
  exit 0
fi

# ------------------------------------------------------------------------------- 4. rollback
echo "!! ${SHA:0:12} failed its checks"
if [[ -z "$PREV" || "$PREV" == "$SHA" ]]; then
  echo "!! no earlier healthy release to roll back to"
  exit 2
fi
echo "== 4/4 ROLLING BACK to ${PREV:0:12}"
git_as_owner fetch --quiet origin || true
git_as_owner reset --hard --quiet "$PREV" || { echo "!! git reset to ${PREV} failed"; exit 2; }
set_env IMAGE_TAG "$PREV"
pull_images "$PREV" || { echo "!! the previous images are not available"; exit 2; }
if start_and_verify "$PREV"; then
  echo "ROLLED_BACK ${SHA} -> ${PREV}: the previous version is serving again" | tee /dev/stderr
  exit 1
fi
echo "!! the rollback failed too: the service is DOWN, see the logs above"
exit 2
