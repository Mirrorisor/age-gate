"""Tamper with a real, valid mock-passport proof and check the passport service refuses it.

Part of docs/SELF-REVIEW.md. Test use only, mock passports only. First capture a proof: run
scripts/test-phone/e2e.ts with PROOF_OUT set (it writes the adult's proofs and scope to that
file). Then, with the stack up, run this inside the stack's network with the file at
/out/adult.json:

    docker run --rm --network age-gate_default -v <folder with adult.json>:/out:ro         --entrypoint python age-gate-site /out/self_review_tamper.py

For the dev-mode check, also start a copy of the service with dev mode off first:

    docker run -d --name passport-nodev --network age-gate_default         -e PASSPORT_DEV_MODE=0 age-gate-passport
"""
import copy
import json

import requests

captured = json.load(open("/out/adult.json"))
proofs, result, scope = captured["proofs"], captured["result"], captured["scope"]


def ask(url, proofs=proofs, result=result, domain="localhost", scope=scope):
    body = {"proofs": proofs, "result": result, "domain": domain, "scope": scope}
    return requests.post(url + "/verify", json=body, timeout=180).json().get("ok")


def flipped(ps):
    ps = copy.deepcopy(ps)
    p = ps[0]["proof"]
    i = len(p) // 2
    ps[0]["proof"] = p[:i] + ("0" if p[i] != "0" else "1") + p[i + 1:]
    return ps


DEV = "http://passport:8100"
checks = [
    ("the untouched valid proof is accepted (sanity check)", ask(DEV), True),
    ("the same proof for another domain is refused", ask(DEV, domain="evil.example"), False),
    ("the same proof under another scope is refused", ask(DEV, scope="age-over-18:somethingelse"), False),
    ("one changed character in a proof is refused", ask(DEV, proofs=flipped(proofs)), False),
    ("the proof set with its last piece removed is refused", ask(DEV, proofs=proofs[:-1]), False),
    ("the proof set with a piece repeated is refused", ask(DEV, proofs=proofs + proofs[-1:]), False),
]
for name, got, want in checks:
    print(("PASS" if got is want else "FAIL"), name, f"(ok={got})")

try:
    got = ask("http://passport-nodev:8100")
    print(("PASS" if got is False else "FAIL"), "a mock passport is refused when dev mode is off", f"(ok={got})")
except requests.RequestException as exc:
    print("SKIP  dev-mode-off service not reachable:", type(exc).__name__)
