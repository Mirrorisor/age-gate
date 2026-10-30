#!/usr/bin/env bash
# Answer a passport-page request with a MOCK passport (test only). Needs REQUEST_URL.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git ca-certificates >/dev/null
# Pinned to the zkpassport-packages commit this was tested with (2026-10-30).
ZKP_COMMIT=${ZKP_COMMIT:-a70fe82afe291950db096809bb006153cb157c8b}
git init -q /work && cd /work
git fetch -q --depth 1 https://github.com/zkpassport/zkpassport-packages.git "$ZKP_COMMIT" && git checkout -q FETCH_HEAD
echo "zkpassport commit: $(git log -1 --format='%h %ad' --date=short)"
bun install --frozen-lockfile 2>&1 | tail -1
bunx turbo run build --filter='@zkpassport/e2e^...' --filter='!onchain-credentials-contracts' --filter='!registry-contracts' 2>&1 | tail -40
cp /phone/test-phone.ts packages/e2e/src/test-phone.ts
cd packages/e2e
NODE_OPTIONS=--max-old-space-size=4096 bun src/test-phone.ts
