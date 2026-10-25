"""A small client for the zk-age-verifier service.

It knows how to open a session, pass the wallet's answer to the verifier,
and read the verdict. It knows nothing about any particular website.
"""

import requests


class VerifierError(Exception):
    """The verifier could not be reached, or its answer made no sense."""


def is_verified(result):
    """True only if the verifier says 'verified' AND age_over_18 is true."""
    return (
        isinstance(result, dict)
        and result.get("state") == "verified"
        and result.get("result", {}).get("age_over_18") is True
    )


class AgeVerifier:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def start_session(self):
        """Open a session. Returns {"session_id": ..., "offer": ...}."""
        try:
            r = requests.post(
                self.base_url + "/sessions",
                json={"checks": ["age_over_18"]},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return {"session_id": data["session_id"], "offer": data["transports"]["dc"]}
        except (requests.RequestException, ValueError, KeyError) as e:
            raise VerifierError(str(e)) from e

    def finish(self, session_id, response):
        """Send the wallet's response. Returns (verified, details)."""
        try:
            r = requests.post(
                self.base_url + "/sessions/" + session_id + "/presentation",
                json={"response": response},
                timeout=30,
            )
            result = r.json()
        except (requests.RequestException, ValueError) as e:
            raise VerifierError(str(e)) from e
        return is_verified(result), result

    def health(self):
        """Return the verifier's health report, or raise VerifierError."""
        try:
            r = requests.get(self.base_url + "/health", timeout=3)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise VerifierError(str(e)) from e
