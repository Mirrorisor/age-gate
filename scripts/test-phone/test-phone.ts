/**
 * Answers the passport page's request link (from REQUEST_URL) with a MOCK passport, like the
 * ZKPassport app would. Give it the link from the page's "Test mode" box. See README.md.
 */
import { answerRequest } from "./phone"

const requestUrl = (process.env.REQUEST_URL ?? process.argv[2] ?? "").trim()
if (!requestUrl) throw new Error("Give the request link in REQUEST_URL")
const dateOfBirth = new Date(process.env.DATE_OF_BIRTH ?? "1995-11-12")
const sent = await answerRequest(requestUrl, dateOfBirth)
if (sent) console.log("Check the browser.")
process.exit(0)
