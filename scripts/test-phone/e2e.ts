/**
 * End-to-end check of the passport route against a running site, with MOCK passports only.
 * Plays both sides: the browser (the SDK's request, like passport/client.ts) and the phone
 * (phone.ts), then asks the site for its verdict. Payment needs a real wallet, so it is not here.
 *
 * Cases:
 *   1. adult (born 1995)          -> the site lets them in
 *   2. minor (born 2015)          -> no proof can be made, the site never lets them in
 *   3. replay in the same visit   -> refused (the visit's scope is used up)
 *   4. replay in a new visit      -> refused (different scope)
 * Exits 0 only if all four hold.
 */
import { ZKPassport } from "@zkpassport/sdk"
import { answerRequest } from "./phone"

const SITE = (process.env.SITE_URL ?? "http://host.docker.internal:5000").replace(/\/$/, "")
const DOMAIN = process.env.SITE_DOMAIN ?? "localhost"
const TIMEOUT_MS = 10 * 60 * 1000

type Visit = { cookie: string; scope: string }
type Proofs = { proofs: unknown; result: unknown }

async function openVisit(): Promise<Visit> {
  const page = await fetch(`${SITE}/passport`)
  if (page.status !== 200) throw new Error(`/passport answered ${page.status}`)
  if (page.headers.get("set-cookie")) throw new Error("Just visiting /passport set a cookie")
  const response = await fetch(`${SITE}/api/passport/start`, { method: "POST" })
  const scope = ((await response.json()) as { scope?: string }).scope
  const cookie = response.headers.get("set-cookie")?.split(";")[0]
  if (!scope || !cookie) throw new Error("Start gave no scope or no session cookie")
  return { cookie, scope }
}

async function finish(visit: Visit, body: Proofs) {
  const response = await fetch(`${SITE}/api/passport/finish`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Cookie: visit.cookie },
    body: JSON.stringify(body),
  })
  const reply = (await response.json()) as { ok?: boolean; message?: string }
  return { status: response.status, ok: reply.ok === true, message: reply.message ?? "" }
}

/** Opens a request for the visit's scope and has the mock phone answer it. */
async function prove(visit: Visit, dateOfBirth: string): Promise<Proofs | null> {
  const builder = await new ZKPassport(DOMAIN).request({
    name: "Age check",
    logo: "",
    purpose: "Prove you are 18 or over. Nothing else is shared.",
    scope: visit.scope,
    mode: "fast",
    devMode: true,
  })
  const { url, onSuccess, onError, onReject } = builder.gte("age", 18).done()
  const outcome = new Promise<Proofs | null>((resolve) => {
    onSuccess(({ proofs, result }) => resolve({ proofs, result }))
    onError(() => resolve(null))
    onReject(() => resolve(null))
    setTimeout(() => resolve(null), TIMEOUT_MS)
  })
  const sent = await answerRequest(url, new Date(dateOfBirth))
  return sent ? outcome : null
}

const results: [string, boolean, string][] = []
function check(name: string, passed: boolean, detail: string) {
  results.push([name, passed, detail])
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}: ${detail}`)
}

// 1. Adult
const adultVisit = await openVisit()
const adultProofs = await prove(adultVisit, "1995-11-12")
if (!adultProofs) {
  check("adult gets in", false, "the mock phone could not make a proof")
} else {
  const reply = await finish(adultVisit, adultProofs)
  check("adult gets in", reply.ok, `${reply.status} ${reply.ok ? "ok" : reply.message}`)

  // 3. Same visit again: its scope was used once already.
  const again = await finish(adultVisit, adultProofs)
  check("replay in the same visit is refused", !again.ok, `${again.status} ${again.message}`)

  // 4. A new visit gets a new scope; the old proofs were made for the old one.
  const other = await finish(await openVisit(), adultProofs)
  check("replay in a new visit is refused", !other.ok, `${other.status} ${other.message}`)
}

// 2. Minor
const minorVisit = await openVisit()
const minorProofs = await prove(minorVisit, "2015-01-01")
if (minorProofs) {
  const reply = await finish(minorVisit, minorProofs)
  check("minor is kept out", !reply.ok, `proofs were made! site said ${reply.status}`)
} else {
  check("minor is kept out", true, "no proof could be made")
}

const failed = results.filter(([, passed]) => !passed).length
console.log(failed ? `\n${failed} of ${results.length} checks FAILED` : `\nAll ${results.length} checks passed`)
process.exit(failed ? 1 : 0)
