"""Smoke test of every API endpoint against the processed pilot (requires data/processed/indiranagar-pilot)."""
import sys, time, json; sys.path.insert(0, "backend")
from fastapi.testclient import TestClient
from rse.api import app
c = TestClient(app); from rse.config import PILOT; A = PILOT["id"]; bad = 0
def T(name, r, show=None):
    global bad
    ok = r.status_code == 200; bad += (not ok)
    print(("OK   " if ok else "FAIL ") + name, r.status_code, f"{len(r.content)//1024}KB", (show(r.json()) if show and ok else "" if ok else r.text[:160]))
T("health", c.get("/api/health"))
T("areas", c.get("/api/areas"), lambda j: [a["name"] for a in j])
t = time.time(); r = c.get(f"/api/areas/{A}/buildings"); T("buildings", r, lambda j: len(j["features"])); print("   first-load s", round(time.time() - t, 1))
T("trees", c.get(f"/api/areas/{A}/trees")); T("missing", c.get(f"/api/areas/{A}/missing"))
feats = r.json()["features"]; by = {f["properties"]["rank"]: f["properties"]["id"] for f in feats}; bid, mid = by[1], by[1500]
for b in (bid, mid):
    t = time.time(); d = c.get(f"/api/areas/{A}/buildings/{b}")
    T("detail rank%s" % d.json()["rank"], d, lambda j: (round(j["energy"]["scenarios"]["middle"]["annual_kwh"]), round(j["energy"]["kwh_per_kwp_year"]), j["transparency"]["quality"], j["financial"]["middle"]["payback_years"])); print("   s", round(time.time() - t, 2))
T("recalculate", c.post(f"/api/areas/{A}/buildings/{mid}/recalculate", json={"economics": {"metering": "gross_metering", "retail_energy_charge": 7.5}, "pv": {"tilt_deg": 20, "azimuth_deg": 160}}),
  lambda j: (round(j["energy"]["kwh_per_kwp_year"]), j["financial"]["middle"]["metering"], j["energy"]["pv_assumptions"]))
for tm in ("2026-06-21T12:00", "2026-12-21T09:00", "2026-12-21T17:55", "2026-11-11T23:00"):
    t = time.time(); T("shadows " + tm, c.get(f"/api/areas/{A}/shadows", params={"time": tm, "west": 77.636, "south": 12.975, "east": 77.642, "north": 12.98}), lambda j: (round(j["sun"]["elevation"], 1), len(j["features"]))); print("   s", round(time.time() - t, 2))
T("roof shade", c.get(f"/api/areas/{A}/buildings/{mid}/shade", params={"time": "2026-12-21T09:00"}), lambda j: (j["fractions"], len(j["cells"]["features"]), j["sources"][:2]))
T("ranking", c.get(f"/api/areas/{A}/ranking", params={"quality": "estimated", "max_shading_pct": 2, "limit": 3}), lambda j: j[:1])
T("sunpath", c.get("/api/sunpath", params={"date": "2026-11-11"}), lambda j: len(j["points"]))
T("assumptions", c.get("/api/assumptions"))
T("validation", c.get(f"/api/areas/{A}/validation"), lambda j: (round(j["pvgis_comparison"]["difference_pct"], 2), round(j["pvgis_comparison"]["poa_difference_pct"], 2), round(j["pvgis_comparison"]["without_component_closure_correction"]["difference_pct"], 2), j["height_measurements"]["status"]))
T("search coords", c.get("/api/search", params={"q": "12.97, 77.64"}))
T("search nominatim", c.get("/api/search", params={"q": "Indiranagar"}), lambda j: [x["name"][:40] for x in j[:2]])
T("contribution", c.post("/api/contributions", json={"building_id": bid, "roof_type": "flat RCC", "obstructions": ["water tank"]}), lambda j: j["status"])
print("job too large ->", c.post("/api/jobs", json={"bbox": [77.5, 12.9, 77.7, 13.1]}).json())
print("404s ->", c.get("/api/areas/x/meta").status_code, c.get(f"/api/areas/{A}/buildings/nope").status_code)
print("FAILURES:", bad)
