FROM oven/bun:1.3.8
WORKDIR /app
COPY package.json ./
RUN bun install
COPY check.ts server.ts client.ts ./
RUN bun run build:client
USER bun
EXPOSE 8100
CMD ["bun", "run", "server.ts"]
