/**
 * Over-18 check for passports and ID cards through ZKPassport, verified on this server only.
 *
 * - verifierMode "local": proofs are never sent to ZKPassport's verifier API.
 * - The query is rebuilt here (age >= 18, nothing disclosed), so a visitor cannot swap in a
 *   different question.
 * - The per-site unique identifier the SDK returns is dropped: an age gate has no use for it,
 *   and keeping it would let visits be linked.
 */
import { ZKPassport } from "@zkpassport/sdk"
import type { ProofResult, QueryResult } from "@zkpassport/utils"

export const MIN_AGE = 18
export const SCOPE_PREFIX = "age-over-18:"

export type CheckConfig = {
  /** The site's host name, as the visitor's browser sees it (no scheme, no path) */
  domain: string
  /** The scope the request was made with: SCOPE_PREFIX plus a random part, new for every visit */
  scope: string
  /** Accept mock passports (Zero Knowledge Republic) and read the Sepolia registries. Test only. */
  devMode: boolean
  /** Ethereum RPC used to read ZKPassport's certificate and circuit registries */
  rpcUrl?: string
}

export async function checkOver18(
  proofs: unknown,
  queryResult: unknown,
  config: CheckConfig,
): Promise<boolean> {
  if (!config.scope.startsWith(SCOPE_PREFIX) || config.scope.length > 100) return false
  if (!Array.isArray(proofs) || proofs.length === 0 || !isRecord(queryResult)) return false
  if (!isWellFormedSet(proofs)) return false
  const age = queryResult.age
  if (!isRecord(age) || !isRecord(age.gte)) return false
  if (age.gte.expected !== MIN_AGE || age.gte.result !== true) return false
  if (Object.keys(queryResult).some((key) => key !== "age")) return false

  const zkPassport = new ZKPassport(config.domain)
  const { query } = zkPassport.createQuery().gte("age", MIN_AGE).done()
  try {
    const { verified } = await zkPassport.verify({
      proofs: proofs as ProofResult[],
      originalQuery: query,
      queryResult: queryResult as QueryResult,
      scope: config.scope,
      devMode: config.devMode,
      verifierMode: "local",
      config: config.rpcUrl ? { rpcUrl: config.rpcUrl } : undefined,
    })
    return verified === true
  } catch {
    return false
  }
}

/**
 * Each proof in a set says its place (index) and the set's size (total). The SDK accepts a set
 * with a piece repeated, which proves nothing extra but is not what the app sent, so refuse
 * anything but pieces 0..total-1, each once, with total the set's real size.
 */
function isWellFormedSet(proofs: unknown[]): boolean {
  const seen = new Set<number>()
  for (const proof of proofs) {
    if (!isRecord(proof) || proof.total !== proofs.length) return false
    const index = proof.index
    if (!Number.isInteger(index) || index < 0 || index >= proofs.length || seen.has(index)) {
      return false
    }
    seen.add(index)
  }
  return true
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
