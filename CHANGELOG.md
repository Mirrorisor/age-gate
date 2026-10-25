# Changelog

## 0.1.0

- First release of the age-check client (`AgeVerifier`, `is_verified`, `VerifierError`).
- Flask demo site with a members page gated by a zero-knowledge over-18 check.
- Works end to end with a real Android wallet (Multipaz Test App, Age Verification document) and with a fake wallet in demo mode.
- Known limits: only the `eu.europa.ec.av.1` document type is accepted; the verifier is experimental; demo certificates are for local testing only.