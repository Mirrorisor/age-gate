/**
 * End-to-end check of the verification service (agecheck.service) with a site in another
 * language (examples/node-site), using MOCK passports only. Plays the visitor's browser across
 * both, keeping each one's cookies apart, as a real browser would.
 *
 * Cases:
 *   1. adult: Node site -> service -> passport proof -> token -> Node site lets them in
 *   2. the same callback URL again              -> refused (the site's nonce is used up)
 *   3. the token given to another visitor       -> refused (not their nonce)
 *   4. a tampered token                         -> refused (bad signature)
 *   5. minor: no proof can be made, the service hands over no token
 * Exits 0 only if all five hold.
 */
import { prove } from "./browser"

const SITE = (process.env.NODE_SITE_URL ?? "http://node-site:3000").replace(/\/$/, "")
const SERVICE = (process.env.SERVICE_URL ?? "http://agecheck-service:8200").replace(/\/$/, "")

/** One browser's cookies for one origin. */
class Jar {
  private cookies = new Map<string, string>()
  header() {
    return [...this.cookies].map(([k, v]) => `${k}=${v}`).join("; ")
  }
  take(response: Response) {
    for (const line of response.headers.getSetCookie()) {
      const [pair] = line.split(";")
      const at = pair.indexOf("=")
      this.cookies.set(pair.slice(0, at).trim(), pair.slice(at + 1).trim())
    }
  }
}

async function get(url: string, jar: Jar) {
  const response = await fetch(url, { redirect: "manual", headers: { Cookie: jar.header() } })
  jar.take(response)
  return response
}

async function post(url: string, jar: Jar, body?: unknown) {
  const response = await fetch(url, {
    method: "POST",
    redirect: "manual",
    headers: { Cookie: jar.header(), "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  jar.take(response)
  return response
}

const results: boolean[] = []
function check(name: string, passed: boolean, detail: string) {
  results.push(passed)
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}: ${detail}`)
}

/** Sends a fresh visitor from the Node site to the service and through a passport check. */
async function visit(dateOfBirth: string) {
  const site = new Jar()
  const service = new Jar()
  const toService = await get(`${SITE}/members`, site)
  const start = toService.headers.get("location") ?? ""
  if (toService.status !== 302 || !start.startsWith(`${SERVICE}/start?nonce=`)) {
    throw new Error(`the Node site did not send the visitor to the service (${toService.status} ${start})`)
  }
  const toPassport = await get(start, service)
  if (toPassport.status !== 302) throw new Error(`/start answered ${toPassport.status}`)
  const scope = ((await (await post(`${SERVICE}/passport/start`, service)).json()) as { scope: string }).scope
  const attempt = await prove(scope, dateOfBirth)
  let finished = { ok: false }
  if (attempt.proofs) {
    finished = await (await post(`${SERVICE}/passport/finish`, service, attempt.proofs)).json()
  }
  const handoff = await get(`${SERVICE}/handoff`, service)
  return { site, attempt, finished, handoff }
}

// 1. An adult goes from the Node site, through the service, and back in.
const adult = await visit("1995-11-12")
const callback = adult.handoff.headers.get("location") ?? ""
if (adult.handoff.status !== 302 || !callback.startsWith(`${SITE}/age-callback?token=`)) {
  check("adult gets into the Node site", false,
    adult.attempt.proofs ? `the service answered ${adult.handoff.status}` : adult.attempt.why)
} else {
  const back = await get(callback, adult.site)
  const members = await get(`${SITE}/members`, adult.site)
  const inside = members.status === 200 && (await members.text()).includes("adults only")
  check("adult gets into the Node site", back.status === 302 && inside,
    `callback ${back.status}, then /members ${members.status}`)

  // 2. The same callback again: the site's nonce was used up on the first one.
  const again = await get(callback, adult.site)
  check("the same token used twice is refused", again.status === 403, `${again.status}`)

  // 3. The token handed to a different visitor of the site (their own fresh nonce).
  const other = new Jar()
  await get(`${SITE}/members`, other)
  const stolen = await get(callback, other)
  check("the token in another visitor's hands is refused", stolen.status === 403, `${stolen.status}`)

  // 4. A tampered token, for a visitor whose nonce is waiting.
  const token = new URL(callback).searchParams.get("token") ?? ""
  const [body, sig] = token.split(".")
  const flipped = body.slice(0, -1) + (body.endsWith("A") ? "B" : "A")
  const tamperer = new Jar()
  await get(`${SITE}/members`, tamperer)
  const forged = await get(`${SITE}/age-callback?token=${flipped}.${sig}`, tamperer)
  check("a tampered token is refused", forged.status === 403, `${forged.status}`)
}

// 5. A minor: no proof, so the service hands over no token and the site never lets them in.
const minor = await visit("2015-01-01")
const minorMembers = await get(`${SITE}/members`, minor.site)
check("minor is kept out", minor.handoff.status === 400 && minorMembers.status === 302,
  `${minor.attempt.why || "proofs were made!"}; handoff ${minor.handoff.status}`)

const failed = results.filter((ok) => !ok).length
console.log(failed ? `\n${failed} of ${results.length} checks FAILED` : `\nAll ${results.length} checks passed`)
process.exit(failed ? 1 : 0)
