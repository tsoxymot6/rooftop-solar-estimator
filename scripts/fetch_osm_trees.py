"""Fetch OSM trees / tree rows / woods / building tags via Overpass (with polite UA + mirror fallback)."""
import sys, json, time, requests
S,W,N,E = 12.973,77.634,12.986,77.647
Q = f'[out:json][timeout:90];(node["natural"="tree"]({S},{W},{N},{E});way["natural"="tree_row"]({S},{W},{N},{E});way["natural"="wood"]({S},{W},{N},{E});way["landuse"="forest"]({S},{W},{N},{E}););out geom;'
HOSTS = ["https://overpass-api.de/api/interpreter","https://overpass.private.coffee/api/interpreter","https://overpass.kumi.systems/api/interpreter"]
H = {"User-Agent":"RooftopSolarEstimator/0.1 (student research project; contact via repo)","Accept":"application/json"}
for attempt in range(3):
    for h in HOSTS:
        try:
            r = requests.post(h,data={"data":Q},headers=H,timeout=100)
            if r.status_code==200:
                j=r.json(); json.dump(j,open(sys.argv[1],"w")); print("ok",h,len(j["elements"]),"elements"); sys.exit(0)
            print(h,r.status_code)
        except Exception as e: print(h,"err",type(e).__name__)
    time.sleep(5)
sys.exit(1)
