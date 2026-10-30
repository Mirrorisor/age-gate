/**
 * Browser side of the passport check, served by the age-gate site at /passport/client.js.
 * It opens a request to the ZKPassport app (QR code on a computer, a link on a phone), and
 * posts the proofs the app sends back to the site, which has them checked server side.
 */
import { ZKPassport } from "@zkpassport/sdk"
import QRCode from "qrcode"

function byId<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const root = byId<HTMLDivElement>("passport")
const button = byId<HTMLButtonElement>("passport-go")
const message = byId<HTMLParagraphElement>("passport-msg")
const qr = byId<HTMLDivElement>("passport-qr")
const link = byId<HTMLAnchorElement>("passport-link")
const testBox = byId<HTMLDetailsElement>("passport-test")
const testUrl = byId<HTMLTextAreaElement>("passport-url")
const devMode = root.dataset.dev === "1"
// The site makes a new scope for every visit, so a proof only works in the visit that asked.
const scope = root.dataset.scope!

async function start() {
  button.disabled = true
  message.textContent = "Starting..."
  try {
    const zkPassport = new ZKPassport()
    const builder = await zkPassport.request({
      name: "Age check",
      logo: "",
      purpose: "Prove you are 18 or over. Nothing else is shared.",
      scope,
      mode: "fast",
      devMode,
    })
    const { url, onRequestReceived, onGeneratingProof, onSuccess, onReject, onError } = builder
      .gte("age", 18)
      .done()

    qr.innerHTML = await QRCode.toString(url, { type: "svg", margin: 1, width: 240 })
    link.href = url
    link.hidden = false
    if (devMode) {
      testUrl.value = url
      testBox.hidden = false
    }
    message.textContent = "Scan the code with the ZKPassport app, or open the link on your phone."

    onRequestReceived(() => {
      message.textContent = "Request received in the app."
    })
    onGeneratingProof(() => {
      message.textContent = "The app is making the proof..."
    })
    onReject(() => {
      message.textContent = "The request was declined in the app."
      button.disabled = false
    })
    onError((error) => {
      message.textContent = "The app reported an error: " + error
      button.disabled = false
    })
    onSuccess(async ({ proofs, result }) => {
      message.textContent = "Checking the proof..."
      const response = await fetch(root.dataset.finish!, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proofs, result }),
      })
      const out = await response.json()
      if (out.ok) {
        location.href = out.next
      } else {
        message.textContent = out.message || "Not verified."
        button.disabled = false
      }
    })
  } catch (error) {
    message.textContent = "Error: " + (error as Error).message
    button.disabled = false
  }
}

button.addEventListener("click", start)
