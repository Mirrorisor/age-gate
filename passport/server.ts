/**
 * The passport service the age-gate site calls server to server. Not exposed to visitors.
 *   POST /verify    {"proofs": [...], "result": {...}, "domain": "host", "scope": "age-over-18:..."}  ->  {"ok": true | false}
 *   GET  /client.js the browser side, built from client.ts (the site serves it to visitors)
 *   GET  /health    {"ok": true, "devMode": ...}
 * It keeps nothing: no proofs, no identifiers, no visitor addresses.
 */
import { checkOver18 } from "./check"

const defaultDomain = process.env.PASSPORT_DOMAIN ?? "localhost"
const devMode = process.env.PASSPORT_DEV_MODE !== "0"
const rpcUrl = process.env.PASSPORT_RPC_URL || undefined
const port = Number(process.env.PORT ?? 8100)
const client = Bun.file(new URL("./public/client.js", import.meta.url))

Bun.serve({
  port,
  hostname: "0.0.0.0",
  maxRequestBodySize: 8 * 1024 * 1024,
  async fetch(request) {
    const { pathname } = new URL(request.url)
    if (request.method === "GET" && pathname === "/health") {
      return Response.json({ ok: true, devMode })
    }
    if (request.method === "GET" && pathname === "/client.js") {
      return new Response(client, { headers: { "Content-Type": "text/javascript" } })
    }
    if (request.method === "POST" && pathname === "/verify") {
      let body: any
      try {
        body = await request.json()
      } catch {
        return Response.json({ ok: false, error: "bad json" }, { status: 400 })
      }
      const domain = typeof body?.domain === "string" && body.domain ? body.domain : defaultDomain
      const scope = typeof body?.scope === "string" ? body.scope : ""
      const ok = await checkOver18(body?.proofs, body?.result, { domain, scope, devMode, rpcUrl })
      console.log(JSON.stringify({ event: ok ? "passport_verified" : "passport_refused" }))
      return Response.json({ ok })
    }
    return Response.json({ error: "not found" }, { status: 404 })
  },
})
console.log(JSON.stringify({ event: "passport_service_started", devMode, port }))
