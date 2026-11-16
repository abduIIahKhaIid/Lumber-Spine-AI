#!/bin/bash
# Writes deploy/runtime.env from AWS Systems Manager Parameter Store. Runs ON the EC2 instance
# (as root, by the deploy). The parameter is one SecureString whose value is a complete dotenv
# file (standard tier: free, up to 4 KB). Nothing from it is ever printed.
#
#   parameter:  /lumber-spine-ai/prod/dotenv   (override with PARAMETER_NAME)
#   region:     the instance's own region     (override with AWS_REGION)
#
# Fail-closed: if the parameter cannot be read or a required key is missing, the current
# runtime.env is left untouched and the script exits non-zero, so the deploy stops before it
# changes anything.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${DEPLOY_DIR}/runtime.env"
PARAMETER_NAME="${PARAMETER_NAME:-/lumber-spine-ai/prod/dotenv}"
REQUIRED=(PUBLIC_HOST REVIEW_ACCESS_TOKEN)

if [[ -z "${AWS_REGION:-}" ]]; then
  token="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' --max-time 3)"
  AWS_REGION="$(curl -fsS -H "X-aws-ec2-metadata-token: ${token}" --max-time 3 \
    http://169.254.169.254/latest/meta-data/placement/region)"
fi
export AWS_REGION

umask 077
tmp="$(mktemp "${DEPLOY_DIR}/.runtime.env.XXXXXX")"
trap 'rm -f -- "$tmp"' EXIT

echo "== reading ${PARAMETER_NAME} from SSM Parameter Store (${AWS_REGION})"
# The redirection keeps the values out of stdout and therefore out of the SSM and CI logs.
AWS_PAGER="" aws ssm get-parameter --name "$PARAMETER_NAME" --with-decryption \
  --query Parameter.Value --output text > "$tmp"

# Windows line endings (text pasted from a Windows editor) would end up inside the values.
sed -i 's/\r$//' "$tmp"

missing=()
for key in "${REQUIRED[@]}"; do
  grep -Eq "^${key}=.+" "$tmp" || missing+=("$key")
done
if ! grep -Eq '^(GROQ_API_KEY|GEMINI_API_KEY|OLLAMA_BASE_URL)=.+' "$tmp"; then
  missing+=("GROQ_API_KEY or GEMINI_API_KEY")
fi
if ((${#missing[@]})); then
  echo "!! the parameter is missing: ${missing[*]} (nothing was changed)" >&2
  exit 1
fi

# IMAGE_TAG belongs to the deploy: keep the current value (remote_deploy.sh updates it).
if [[ -f "$TARGET" ]]; then
  grep -E '^IMAGE_TAG=' "$TARGET" >> "$tmp" || true
fi
chmod 600 "$tmp"
mv -f "$tmp" "$TARGET"
trap - EXIT
echo "== runtime.env updated ($(grep -c '=' "$TARGET") settings)"
