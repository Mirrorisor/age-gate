#!/usr/bin/env bash
# Answer a passport-page request with a MOCK passport (test only). Needs REQUEST_URL.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git ca-certificates >/dev/null
# Pinned zkpassport-packages commit (2026-11-16). It must be new enough to hash every
# certificate type in ZKPassport's live Sepolia registry: since mid-November 2026 it also
# holds Aadhaar (UIDAI) certificates, and older commits fail with "Validation failed for
# packaged certificates" before proving.
ZKP_COMMIT=${ZKP_COMMIT:-1045a75e3d073d0e80ed49e3d5bd53e6fdebf298}
git init -q /work && cd /work
git fetch -q --depth 1 https://github.com/zkpassport/zkpassport-packages.git "$ZKP_COMMIT" && git checkout -q FETCH_HEAD
echo "zkpassport commit: $(git log -1 --format='%h %ad' --date=short)"
bun install --frozen-lockfile 2>&1 | tail -1
bunx turbo run build --filter='@zkpassport/e2e^...' --filter='!onchain-credentials-contracts' --filter='!registry-contracts' 2>&1 | tail -40
cp /phone/*.ts packages/e2e/src/
cd packages/e2e
# Which script to run: test-phone.ts (answer one link) by default, or e2e.ts (full check).
NODE_OPTIONS=--max-old-space-size=4096 bun "src/${1:-test-phone.ts}"
