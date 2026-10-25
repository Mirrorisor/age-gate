import json, sys
sys.path.insert(0, "/tmp/work")
from tests.integration.presenter import present

job = json.load(sys.stdin)
data = present(job["request"], job["origin"])
sys.stdout.write(json.dumps(data))
