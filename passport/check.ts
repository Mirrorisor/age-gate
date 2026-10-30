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

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
