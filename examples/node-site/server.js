// A site written in Node, with no dependencies, that uses the age-verification service
// (agecheck.service) for its "adults only" page. Test use only, like the rest of this repository.
//
//   SERVICE_URL=http://localhost:8200 SERVICE_SECRET=<the same 32+ characters as the service> \
//   SITE_ORIGIN=http://localhost:3000 node server.js
//
// All it needs from the service is the redirect to /start and the token check in checkToken().

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto"
import { createServer } from "node:http"

const SERVICE_URL = (process.env.SERVICE_URL ?? "http://localhost:8200").replace(/\/$/, "")
const SECRET = process.env.SERVICE_SECRET ?? ""
const ORIGIN = process.env.SITE_ORIGIN ?? "http://localhost:3000"
const PORT = Number(process.env.PORT ?? 3000)
if (SECRET.length < 32) throw new Error("SERVICE_SECRET must be at least 32 characters")

// Visitors' sessions, in memory: id -> { nonce, adult }. A real site would use its own sessions.
const sessions = new Map()

/** The token check from agecheck/handoff.py: signature, version, expiry, origin, nonce. */
function checkToken(token, nonce) {
  if (typeof token !== "string" || token.length > 2048) return false
  const [body, sig, extra] = token.split(".")
  if (!body || !sig || extra !== undefined) return false
  const expected = createHmac("sha256", SECRET).update(body).digest()
  const given = Buffer.from(sig, "base64url")
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return false
  let payload
  try {
    payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8"))
  } catch {
    return false
  }
  return (
    payload.v === 1 &&
    payload.over18 === true &&
    Number.isInteger(payload.exp) &&
    Date.now() / 1000 <= payload.exp &&
    payload.aud === ORIGIN &&
    typeof nonce === "string" &&
    payload.nonce === nonce
  )
}

function sessionOf(req, res) {
  const id = /(?:^|;\s*)sid=([A-Za-z0-9_-]+)/.exec(req.headers.cookie ?? "")?.[1]
  if (id && sessions.has(id)) return sessions.get(id)
  const fresh = randomBytes(18).toString("base64url")
  const state = { nonce: null, adult: false }
  sessions.set(fresh, state)
  res.setHeader("Set-Cookie", `sid=${fresh}; HttpOnly; SameSite=Lax; Path=/`)
  return state
}

function send(res, status, html, headers = {}) {
  res.writeHead(status, {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer", // the callback URL carries the token
    ...headers,
  })
  res.end(html)
}

createServer((req, res) => {
  const url = new URL(req.url, ORIGIN)
  const state = sessionOf(req, res)

  if (url.pathname === "/members") {
    if (state.adult) return send(res, 200, "<h1>Members area</h1><p>adults only</p>")
    // Not verified yet: a fresh one-time code, then off to the service.
    state.nonce = randomBytes(24).toString("base64url")
    const target = `${SERVICE_URL}/start?nonce=${state.nonce}`
    return send(res, 302, "", { Location: target })
  }

  if (url.pathname === "/age-callback") {
    const nonce = state.nonce
    state.nonce = null // one use, whatever happens
    if (!checkToken(url.searchParams.get("token"), nonce)) {
      return send(res, 403, "<h1>Not verified</h1><p>The age check did not go through.</p>")
    }
    state.adult = true
    return send(res, 302, "", { Location: "/members" })
  }

  if (url.pathname === "/") {
    return send(res, 200, '<h1>Welcome</h1><p><a href="/members">Members (adults only)</a></p>')
  }
  send(res, 404, "<h1>Not found</h1>")
}).listen(PORT, () => console.log(`node example site on ${ORIGIN} (port ${PORT})`))
