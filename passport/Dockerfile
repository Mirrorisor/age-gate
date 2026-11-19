# Pinned by digest (Bun 1.4.5, tested 2026-11-19).
FROM oven/bun:1.4.5@sha256:3aa040e5445efa09d75bb428a64ba50db13e2b3ac9b6b0c7f145615f62b2ee18
# Debian's security fixes published since the base image was built (Debian stable updates are
# security and bug fixes only). The images job in tests.yml fails if a fixable one is missing.
RUN apt-get update && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY check.ts server.ts client.ts ./
RUN bun run build:client
USER bun
EXPOSE 8100
CMD ["bun", "run", "server.ts"]
