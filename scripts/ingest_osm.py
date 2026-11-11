import sys, json, time; sys.path.insert(0, "backend")
from rse import ingest, config
try:
    p = ingest.fetch_osm(config.PILOT["id"], config.PILOT["bbox"]); o = json.load(open(p))
    print("ok", o["mirror"], len(o["trees"]), len(o["buildings"]), o["buildings_unavailable"], flush=True)
except Exception as e:
    print("ERR", repr(e)[:300], flush=True)
