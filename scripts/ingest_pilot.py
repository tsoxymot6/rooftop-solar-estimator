import sys, json; sys.path.insert(0, "backend")
from rse import ingest, config
st = ingest.ingest_area(config.PILOT["id"], config.PILOT["bbox"], log=lambda m: print(m, flush=True))
json.dump(st, open(config.RAW / config.PILOT["id"] / "ingest_status.json", "w"), indent=1); print(st)
