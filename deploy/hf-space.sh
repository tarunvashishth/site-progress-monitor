#!/bin/sh
# Publish backend/ as a free Hugging Face Docker Space (API + worker in one container).
# Usage: HF_TOKEN=<write token> deploy/hf-space.sh <hf-username>/<space-name>
set -eu
SPACE="${1:?usage: hf-space.sh <user>/<space>}"
: "${HF_TOKEN:?set HF_TOKEN (a write token from huggingface.co/settings/tokens)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a --exclude .venv --exclude .env --exclude tests --exclude '.*cache' --exclude __pycache__ "$ROOT/backend/" "$TMP/"
cp "$ROOT/deploy/hf-space-README.md" "$TMP/README.md"
# Space image: same Dockerfile, but run both processes on the port Spaces expects.
sed -i.bak 's#^EXPOSE 8000#EXPOSE 7860\nENV PORT=7860#; s#^CMD .*#CMD ["./start.sh"]#' "$TMP/Dockerfile" && rm "$TMP/Dockerfile.bak"
sed -i.bak 's#^COPY cpm ./cpm#COPY cpm ./cpm\nCOPY start.sh ./#' "$TMP/Dockerfile" && rm "$TMP/Dockerfile.bak"
cd "$TMP"
git init -q -b main && git add -A && git -c user.name=deploy -c user.email=deploy@localhost commit -qm "deploy"
git push -f "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE}" main
echo "Pushed. Add secrets in Space → Settings, then API URL is https://$(echo "$SPACE" | tr '/' '-' | tr '[:upper:]' '[:lower:]').hf.space"
