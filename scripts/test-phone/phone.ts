/**
 * A stand-in for the ZKPassport app, for testing with a MOCK passport only.
 * answerRequest() joins a request through ZKPassport's relay, proves "18 or over" from a mock
 * passport of the fictional Zero Knowledge Republic, and sends the proofs back like the app would.
 * It refuses requests that are not in dev mode, so it can never stand in for a real passport.
 *
 * Runs inside a checkout of zkpassport-packages, from packages/e2e (it reuses that package's
 * prover). Based on packages/e2e/src/headless-app.ts.
 */
import { Bridge } from "@obsidion/bridge"
import { createRegistryClient } from "@zkpassport/registry"
import { getChainFromQuery } from "@zkpassport/utils"
import { createMockPassport } from "@zkpassport/utils/mock-passports"
import { proveSubproofs } from "./prove"

const CIRCUIT_VERSION = process.env.CIRCUIT_VERSION ?? "0.21.1"

function decode(base64: string) {
  return JSON.parse(Buffer.from(base64, "base64").toString("utf8"))
}

/** Answers one request link. Returns true if proofs were sent, false if none could be made. */
export async function answerRequest(requestUrl: string, dateOfBirth: Date): Promise<boolean> {
  const params = new URL(requestUrl).searchParams
  const request = {
    domain: params.get("d")!,
    pubkey: params.get("p")!,
    query: decode(params.get("c")!),
    service: decode(params.get("s")!),
    mode: params.get("m") ?? "fast",
    devMode: params.get("dev") === "1",
  }
  if (!request.devMode) throw new Error("This test phone only answers dev-mode requests")
  if (request.mode !== "fast") throw new Error(`Only fast mode is handled, got ${request.mode}`)
  console.log(`Request from ${request.domain}: ${JSON.stringify(request.query)}`)
  console.log(`Mock passport born ${dateOfBirth.toISOString().slice(0, 10)}`)

  const chain = getChainFromQuery(request.query, request.devMode)
  const registry = createRegistryClient(
    chain,
    process.env.SEPOLIA_RPC_URL ? { rpcUrl: process.env.SEPOLIA_RPC_URL } : {},
  )
  const origin =
    (/localhost|192\.168\.|127\.0/.test(request.domain) ? "http://" : "https://") + request.domain
  const bridge = await Bridge.join(`obsidion:${request.pubkey}?d=${origin}`, {
    bridgeUrl: request.service.bridgeUrl,
    originOnConnect: true,
    pinOrigin: false,
  })
  if (!bridge.isSecureChannelEstablished()) {
    await new Promise<void>((resolve) => bridge.onSecureChannelEstablished(resolve))
  }
  await bridge.sendMessage("accept")
  console.log("Accepted; proving (a minute or two)...")
  let sent = false
  try {
    const { subproofs, queryResult } = await proveSubproofs({
      passport: createMockPassport({ dateOfBirth }),
      query: request.query,
      domain: request.domain,
      scope: request.service.scope,
      circuitVersion: CIRCUIT_VERSION,
      registry,
    })
    for (const proof of subproofs) {
      await bridge.sendMessage("proof", proof)
    }
    await bridge.sendMessage("done", queryResult)
    console.log(`Sent ${subproofs.length} proofs.`)
    sent = true
  } catch (error) {
    console.log(`Could not prove: ${(error as Error).message}`)
    await bridge.sendMessage("error", { error: "Could not prove" })
  }
  await new Promise((resolve) => setTimeout(resolve, 3000))
  bridge.cleanup()
  return sent
}
