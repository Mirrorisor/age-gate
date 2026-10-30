#!/usr/bin/env bash
# Answer a passport-page request with a MOCK passport (test only). Needs REQUEST_URL.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git ca-certificates >/dev/null
git clone -q --depth 1 https://github.com/zkpassport/zkpassport-packages.git /work && cd /work
echo "zkpassport commit: $(git log -1 --format='%h %ad' --date=short)"
bun install --frozen-lockfile 2>&1 | tail -1
bunx turbo run build --filter='@zkpassport/e2e^...' --filter='!onchain-credentials-contracts' --filter='!registry-contracts' 2>&1 | tail -40
cp /phone/test-phone.ts packages/e2e/src/test-phone.ts
cd packages/e2e
NODE_OPTIONS=--max-old-space-size=4096 bun src/test-phone.ts
