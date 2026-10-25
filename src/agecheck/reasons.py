"""Plain-language explanations for the verifier's failure reasons.

The verifier answers a failed check with a machine code such as
``untrusted-issuer``. These helpers turn that into a sentence a visitor can act
on, without exposing internals.
"""

from __future__ import annotations

import json

REASONS: dict[str, str] = {
    "invalid-envelope": (
        "The wallet's reply was malformed. Try again, or use a different wallet."
    ),
    "decrypt-failed": (
        "The wallet's reply could not be decrypted. The page may have been open too "
        "long, or the site address may not match. Reload the page and try again."
    ),
    "standard-mdoc-not-accepted": (
        "The wallet sent an ordinary proof that reveals details. This site only "
        "accepts zero-knowledge proofs."
    ),
    "unsupported-circuit": (
        "The wallet used a proof format this verifier does not support."
    ),
    "claim-mismatch": (
        "Your credential does not contain the claim this site asked for (over 18). "
        "Use an age-verification credential."
    ),
    "stale-proof": (
        "The proof is too old, or the clock on your device is wrong. Check the "
        "date and time on your phone and try again."
    ),
    "untrusted-issuer": (
        "This site does not trust the organisation that issued your credential."
    ),
    "proof-invalid": "The proof did not check out.",
    "engine-error": "The verifier hit an internal error. Try again later.",
}


def reason_from_detail(detail: object) -> str | None:
    """Pull the reason code out of whatever the verifier returned.

    Accepts the parsed dict, the JSON text of it, or a bare reason code.
    Returns None when no reason can be found.
    """
    if isinstance(detail, dict):
        reason = detail.get("reason")
        return reason if isinstance(reason, str) else None
    if isinstance(detail, str):
        text = detail.strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            return text if text in REASONS else None
        return reason_from_detail(parsed) if isinstance(parsed, dict) else None
    return None


def explain(detail: object) -> str:
    """Return a short, visitor-friendly sentence for a failed check."""
    code = reason_from_detail(detail)
    if code in REASONS:
        return REASONS[code]
    if code:
        return f"Verification failed ({code})."
    return "Verification failed."