"""Stream Google Open Buildings V3 polygons (CC-BY 4.0 / ODbL) for a bbox from the public S2 level-6 tile (no credentials)."""
import sys, gzip, io, requests, pandas as pd, s2sphere
W,S,E,N = [float(x) for x in sys.argv[1:5]]; out = sys.argv[5]
tok = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees((S+N)/2,(W+E)/2)).parent(6).to_token()
url = f"https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_6_gzip_no_header/{tok}_buildings.csv.gz"
print("tile", tok, url, flush=True)
cols = ["latitude","longitude","area_in_meters","confidence","geometry","full_plus_code"]
keep = []
with requests.get(url, stream=True, timeout=120) as r:
    r.raise_for_status()
    r.raw.decode_content = False
    gz = gzip.GzipFile(fileobj=r.raw)
    rd = pd.read_csv(gz, names=cols, header=None, chunksize=400_000, usecols=[0,1,2,3,4,5])
    n = 0
    for ch in rd:
        n += len(ch)
        sub = ch[(ch.longitude.between(W,E)) & (ch.latitude.between(S,N))]
        if len(sub): keep.append(sub)
        print("rows", n, "kept", sum(len(k) for k in keep), flush=True)
df = pd.concat(keep) if keep else pd.DataFrame(columns=cols)
df.to_parquet(out); print("saved", len(df))
