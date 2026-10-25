import json, sys, urllib.request
sys.path.insert(0, "/tmp/work")
from tests.integration.presenter import present

BASE = "http://127.0.0.1:8000"
ORIGIN = "http://localhost:5000"

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)

session = post("/sessions", {"checks": ["age_over_18"]})
print("1. session opened:", session["session_id"])
data = present(session["transports"]["dc"], ORIGIN)
print("2. fake wallet answered, response length:", len(data["response"]))
result = post("/sessions/" + session["session_id"] + "/presentation", {"response": data["response"]})
print("3. verifier says:", result)
