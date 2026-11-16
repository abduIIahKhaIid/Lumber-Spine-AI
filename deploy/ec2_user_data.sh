#!/bin/bash
# EC2 "User data" (Ubuntu 24.04). Paste it into: Launch instance -> Advanced details -> User data.
# It prepares the server only: Docker, AWS CLI, 4 GB swap and a checkout of the repository.
# The first deploy comes from GitHub Actions (re-run the CI workflow on main once the server is
# Online in Systems Manager -> Fleet Manager).
# Progress on the instance:  sudo tail -f /var/log/cloud-init-output.log
set -euo pipefail

REPO_URL="https://github.com/abduIIahKhaIid/Lumber-Spine-AI.git"
APP_DIR="/home/ubuntu/lumber-spine-ai"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git unzip

# AWS CLI v2 (deploy scripts: Parameter Store, S3). Credentials come from the
# instance role; no keys are stored on the server.
if ! command -v aws > /dev/null 2>&1; then
  case "$(dpkg --print-architecture)" in
    amd64) arch="x86_64" ;;
    arm64) arch="aarch64" ;;
    *) echo "unsupported architecture" >&2; exit 1 ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${arch}.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  "$tmp/aws/install" --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli
  rm -rf -- "$tmp"
fi

# Docker Engine and the compose plugin (official repository)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu

# 4 GB swap: PyTorch and three models can spike memory on an 8 GB instance
if [[ ! -f /swapfile ]]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# The SSM agent ships with Ubuntu on EC2; make sure it runs (deploys use it instead of SSH).
snap start amazon-ssm-agent 2> /dev/null || systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service || true

# Checkout (public repository): compose file and deploy scripts. Code changes arrive as images.
if [[ ! -d "$APP_DIR/.git" ]]; then
  sudo -u ubuntu git clone --quiet "$REPO_URL" "$APP_DIR"
fi
echo "SERVER READY: re-run the CI workflow on main to deploy"
