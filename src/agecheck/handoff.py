"""Signed "over 18" tokens, for handing a passed check from the verification service to a site.

The service (``agecheck.service``) runs the age check and then sends the visitor back to the
site with a token. The site checks it with the secret they share. A token says only this:

    {"v": 1, "over18": true, "nonce": <the site's own one-time code>,
     "aud": <the site's origin>, "exp": <unix time, a couple of minutes ahead>}

Format: ``base64url(payload JSON) "." base64url(HMAC-SHA256(secret, first part))``, with no
padding. It is deliberately small, so a site in any language can check it in a few lines (see
``examples/node-site/server.js``). What the site must check, in this order:

1. the signature, with a constant-time comparison;
2. ``v`` is 1 and ``over18`` is true;
3. ``exp`` has not passed;
4. ``aud`` is the site's own origin;
5. ``nonce`` is the one the site stored for this visitor before sending them to the service,
   and the site forgets it on first use, so the same token cannot be used twice.
"""

import base64
import hashlib
import hmac
import json
import time

TOKEN_SECONDS = 120
VERSION = 1


class TokenError(Exception):
    """The token is malformed, forged, expired, or not meant for this site and visitor."""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret, body):
    return hmac.new(secret.encode(), body.encode("ascii"), hashlib.sha256).digest()


def issue(secret, nonce, audience, now=None):
    """A token saying "over 18" for this nonce and site origin, valid for TOKEN_SECONDS."""
    now = time.time() if now is None else now
    payload = {"v": VERSION, "over18": True, "nonce": nonce, "aud": audience,
               "exp": int(now) + TOKEN_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return body + "." + _b64(_signature(secret, body))


def check(token, secret, nonce, audience, now=None):
    """Return the payload if the token is valid for this nonce and origin; raise TokenError."""
    now = time.time() if now is None else now
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 2048:
        raise TokenError("malformed")
    body, sig = token.split(".")
    try:
        given = _unb64(sig)
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("malformed") from exc
    if not hmac.compare_digest(given, _signature(secret, body)):
        raise TokenError("bad signature")
    if not isinstance(payload, dict) or payload.get("v") != VERSION or payload.get("over18") is not True:
        raise TokenError("not an over-18 token")
    exp = payload.get("exp")
    if not isinstance(exp, int) or now > exp:
        raise TokenError("expired")
    if payload.get("aud") != audience:
        raise TokenError("for another site")
    if not isinstance(nonce, str) or not nonce or not hmac.compare_digest(
        str(payload.get("nonce", "")).encode(), nonce.encode()
    ):
        raise TokenError("for another visitor or already used")
    return payload
