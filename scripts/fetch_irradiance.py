"""NASA POWER hourly (primary) + PVGIS PVcalc (independent unshaded check only).
NASA POWER hourly: MERRA-2/CERES-derived, ~0.5 deg x 0.625 deg grid cell (~50-60 km) -> NOT building-level meteorology."""
import json, sys, time, requests, pandas as pd, io
LAT, LON = 12.979, 77.640
YEARS = range(2015, 2025)
P = "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DNI,ALLSKY_SFC_SW_DIFF,T2M,WS10M"
frames = []
import os
os.makedirs("data/raw/nasa_years", exist_ok=True)
for y in YEARS:
    cache = f"data/raw/nasa_years/{y}.parquet"
    if os.path.exists(cache):
        frames.append(pd.read_parquet(cache)); print(y,"cached",flush=True); continue
    url = ("https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=%s&community=RE&longitude=%s&latitude=%s"
           "&start=%d0101&end=%d1231&format=JSON&time-standard=UTC" % (P, LON, LAT, y, y))
    for a in range(4):
        r = requests.get(url, timeout=120)
        if r.status_code == 200: break
        print(y, r.status_code, r.text[:120]); time.sleep(5)
    j = r.json()
    d = pd.DataFrame(j["properties"]["parameter"])
    d.index = pd.to_datetime(d.index, format="%Y%m%d%H"); d.to_parquet(cache); frames.append(d); print(y, len(d), flush=True)
    meta = j.get("header", {})
df = pd.concat(frames).replace(-999, float("nan"))
df = df[["ALLSKY_SFC_SW_DWN","ALLSKY_SFC_SW_DNI","ALLSKY_SFC_SW_DIFF","T2M","WS10M"]]
df.columns = ["ghi","dni","dhi","temp_air","wind_speed"]
df.index.name = "time_utc"
df.to_parquet("data/raw/nasa_power_hourly_2015_2024.parquet")
json.dump({"header": meta, "lat": LAT, "lon": LON, "years": [min(YEARS), max(YEARS)], "fetched": pd.Timestamp.utcnow().isoformat()}, open("data/raw/nasa_power_meta.json","w"), indent=1, default=str)
print(df.describe().T)
