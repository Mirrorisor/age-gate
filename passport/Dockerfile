# Pinned by digest (tested 2026-10-30).
FROM oven/bun:1.3.8@sha256:371d30538b69303ced927bb5915697ac7e2fa8cb409ee332c66009de64de5aa3
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY check.ts server.ts client.ts ./
RUN bun run build:client
USER bun
EXPOSE 8100
CMD ["bun", "run", "server.ts"]
