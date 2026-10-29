# Changelog

## Unreleased

- Invoices untouched for 30 days are deleted (`INVOICE_RETENTION_DAYS`, 0 keeps them). Older invoice files are upgraded in place.
- The payment page asks visitors to pay from a shielded balance, and the privacy page says the verifier sees which organisation issued the credential.
- Logging out now clears the whole session cookie, including the invoice number. Before, a paid invoice stayed in the cookie, so the next person on a shared browser who passed the age check got in without paying, and their visit was tied to the previous person's.

## 0.1.0

- First release of the age-check client (`AgeVerifier`, `is_verified`, `VerifierError`).
- Flask demo site with a members page gated by a zero-knowledge over-18 check.
- Works end to end with a real Android wallet (Multipaz Test App, Age Verification document) and with a fake wallet in demo mode.
- Known limits: only the `eu.europa.ec.av.1` document type is accepted; the verifier is experimental; demo certificates are for local testing only.