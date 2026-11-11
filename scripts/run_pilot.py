import sys, json, time; sys.path.insert(0, "backend")
from rse import pipeline, config
last = [0]
def cb(m, f):
    if time.time() - last[0] > 15 or f == 1.0:
        last[0] = time.time(); print(f"{f:.2f} {m}", flush=True)
m = pipeline.analyze_area(config.PILOT["id"], config.PILOT["bbox"], name=config.PILOT["name"], cb=cb)
print(json.dumps(m["quality_counts"]), m["seconds"], flush=True)
