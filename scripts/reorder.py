"""Reorder the queued (not yet posted) reels: python3 scripts/reorder.py id1 id2 ...
Listed ids go first in that order; any other queued reels keep their order after them."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
q = json.load(open(f"{ROOT}/queue.json"))
done = [x for x in q if x["status"] != "queued"]
todo = {x["id"]: x for x in q if x["status"] == "queued"}
want = [i for i in sys.argv[1:] if i in todo]
missing = [i for i in sys.argv[1:] if i not in todo]
assert not missing, f"not queued: {missing}"
rest = [x for x in q if x["status"] == "queued" and x["id"] not in want]
json.dump(done + [todo[i] for i in want] + rest, open(f"{ROOT}/queue.json", "w"), indent=2)
print("queued order:", want + [x["id"] for x in rest])
