/**
 * The browser side of a passport check, for the end-to-end scripts: opens a ZKPassport request for
 * a scope (as passport/client.ts does in a real browser) and has the mock phone (phone.ts) answer
 * it. MOCK passports only.
 */
import { ZKPassport } from "@zkpassport/sdk"
import { answerRequest } from "./phone"

const DOMAIN = process.env.SITE_DOMAIN ?? "localhost"
const TIMEOUT_MS = 10 * 60 * 1000

export type Proofs = { proofs: unknown; result: unknown }
export type Attempt = { proofs: Proofs | null; why: string }

/** Proves "18 or over" for this scope from a mock passport born on dateOfBirth. */
export async function prove(scope: string, dateOfBirth: string): Promise<Attempt> {
  const builder = await new ZKPassport(DOMAIN).request({
    name: "Age check",
    logo: "",
    purpose: "Prove you are 18 or over. Nothing else is shared.",
    scope,
    mode: "fast",
    devMode: true,
  })
  const { url, onSuccess, onError, onReject } = builder.gte("age", 18).done()
  // Why no proofs arrived matters: a relay hiccup is not the same failure as a proof that
  // could not be made, so each way out says which it was.
  const outcome = new Promise<Attempt>((resolve) => {
    onSuccess(({ proofs, result }) => resolve({ proofs: { proofs, result }, why: "" }))
    onError((error) => resolve({ proofs: null, why: `the request reported an error: ${error}` }))
    onReject(() => resolve({ proofs: null, why: "the request was rejected" }))
    setTimeout(
      () => resolve({ proofs: null, why: "the phone sent its proofs but they never arrived through ZKPassport's relay (timed out)" }),
      TIMEOUT_MS,
    )
  })
  const sent = await answerRequest(url, new Date(dateOfBirth))
  return sent ? outcome : { proofs: null, why: "the mock phone could not make a proof" }
}
