"""FastAPI service. Run:  uvicorn rse.api:app --app-dir backend --port 8000"""
from __future__ import annotations
import os, csv, json, threading, time, uuid, functools
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
import requests
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles

from . import geometry as G, shadow as SH, economics as EC, sun as SUN, ingest, pipeline
from .config import PVAssumptions, EconAssumptions, ECON_PARAMS, SCENARIOS, PROCESSED, RAW, DATA, PILOT, ROOT
from .pv import PVModel

app = FastAPI(title="Rooftop Solar Potential Estimator", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ.get("RSE_CORS_ORIGINS", "*").split(",")], allow_methods=["*"], allow_headers=["*"])
VALID = DATA / "validation"; VALID.mkdir(parents=True, exist_ok=True)
CONTRIB = DATA / "contributions"; CONTRIB.mkdir(parents=True, exist_ok=True)
SEASONS = {"winter (Dec-Feb)": [12, 1, 2], "summer (Mar-May)": [3, 4, 5], "monsoon (Jun-Sep)": [6, 7, 8, 9], "post-monsoon (Oct-Nov)": [10, 11]}
IST = "Asia/Kolkata"


# ------------------------------------------------------------------ state
class Area:
    def __init__(self, area_id):
        d = PROCESSED / area_id
        self.id = area_id
        self.meta = json.loads((d / "meta.json").read_text())
        self.gdf = gpd.read_parquet(d / "buildings.parquet").reset_index(drop=True)
        self.gdf["geom_utm"] = G.to_utm(self.gdf.geometry.values)
        self.idx = {b: i for i, b in enumerate(self.gdf.bid)}
        obs = gpd.read_parquet(d / "obstacles_utm.parquet")
        self.engine = SH.ShadowEngine(list(obs.geometry.values), obs.height_m.values, obs.is_tree.values, obs.oid.values,
                                      max_shadow_m=self.meta["pv_assumptions"]["max_shadow_m"])
        self.engine._display_trees()      # warm the coarse canopy tiles used by the shadow layer
        self.dir = d
        self._geojson = None
        self._trees = None

    def buildings_geojson(self) -> bytes:
        if self._geojson is None:
            g = self.gdf
            feats = []
            for r in g.itertuples():
                feats.append({"type": "Feature", "id": int(r.rank), "geometry": json.loads(shapely.to_geojson(shapely.set_precision(r.geometry, 1e-7))),
                              "properties": {"id": r.bid, "rank": int(r.rank), "area_m2": round(r.area_m2, 1), "height_m": round(r.height_m, 1),
                                             "quality": r.quality, "kwh_mid": round(r.kwh_middle), "kwh_low": round(r.kwh_low), "kwh_high": round(r.kwh_high),
                                             "kwh_per_kwp": round(r.kwh_per_kwp), "kwp_mid": round(r.kwp_middle, 2), "shading_loss_pct": round(r.shading_loss_pct, 2),
                                             "usable_mid_m2": round(r.usable_middle_m2, 1), "payback_mid": None if pd.isna(r.payback_mid_y) else round(r.payback_mid_y, 1),
                                             "height_source": r.height_source}})
            self._geojson = json.dumps({"type": "FeatureCollection", "features": feats}).encode()
        return self._geojson

    def trees_geojson(self) -> bytes:
        if self._trees is None:
            t = gpd.read_parquet(self.dir / "trees.parquet")
            t["geometry"] = shapely.set_precision(t.geometry.values, 1e-6)
            self._trees = t[["tid", "height_m", "geometry"]].to_json().encode()
        return self._trees


_AREAS: dict[str, Area] = {}


def get_area(area_id) -> Area:
    if area_id not in _AREAS:
        if not (PROCESSED / area_id / "meta.json").exists():
            raise HTTPException(404, f"area '{area_id}' has not been analysed")
        _AREAS[area_id] = Area(area_id)
    return _AREAS[area_id]


@functools.lru_cache(maxsize=6)
def pv_model(tilt=12.0, azimuth=180.0, loss_pct=-1.0, harmonize=True) -> PVModel:
    ty, _ = pipeline._pv_inputs()
    ap = PVAssumptions(tilt_deg=tilt, azimuth_deg=azimuth)
    return PVModel(ty, ap, harmonize_components=harmonize)


def to_ist(t: str) -> pd.Timestamp:
    ts = pd.Timestamp(t)
    return ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)


def sun_at(t: str):
    ts = to_ist(t)
    sp = SUN.solar_position(pd.DatetimeIndex([ts]))
    return ts, float(sp["azimuth"].iloc[0]), float(sp["apparent_elevation"].iloc[0])


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


# ------------------------------------------------------------------ basics
@app.get("/api/health")
def health():
    return {"ok": True, "areas": [p.parent.name for p in PROCESSED.glob("*/meta.json")]}


@app.get("/api/areas")
def areas():
    out = []
    for p in sorted(PROCESSED.glob("*/meta.json"), key=lambda q: (q.parent.name != PILOT["id"], q.parent.name)):   # default pilot first
        m = json.loads(p.read_text())
        out.append({k: m[k] for k in ("area_id", "name", "bbox", "bbox_area_km2", "generated", "n_buildings_analysed", "quality_counts")})
    return out


@app.get("/api/areas/{area_id}/meta")
def meta(area_id: str):
    return get_area(area_id).meta


@app.get("/api/areas/{area_id}/buildings")
def buildings(area_id: str):
    return Response(get_area(area_id).buildings_geojson(), media_type="application/geo+json")


@app.get("/api/areas/{area_id}/trees")
def trees(area_id: str):
    return Response(get_area(area_id).trees_geojson(), media_type="application/geo+json")


@app.get("/api/areas/{area_id}/missing")
def missing(area_id: str):
    p = get_area(area_id).dir / "qa_missing_buildings.geojson"
    return Response(p.read_bytes(), media_type="application/geo+json")


@app.get("/api/assumptions")
def assumptions():
    return {"economic": ECON_PARAMS, "pv": PVAssumptions().to_dict(), "scenarios": SCENARIOS, "econ_defaults": EconAssumptions().to_dict()}


@app.get("/api/areas/{area_id}/ranking")
def ranking(area_id: str, min_kwh: float = 0, max_shading_pct: float = 100, min_usable_m2: float = 0, min_kwp: float = 0,
            quality: str = "", limit: int = 100):
    g = get_area(area_id).gdf
    q = g[(g.kwh_middle >= min_kwh) & (g.shading_loss_pct <= max_shading_pct) & (g.usable_middle_m2 >= min_usable_m2) & (g.kwp_middle >= min_kwp)]
    if quality:
        q = q[q.quality.isin(quality.split(","))]
    q = q.sort_values("rank").head(limit)
    return clean([{"rank": int(r.rank), "id": r.bid, "kwh_low": r.kwh_low, "kwh_mid": r.kwh_middle, "kwh_high": r.kwh_high, "kwh_per_kwp": r.kwh_per_kwp,
                   "kwp_mid": r.kwp_middle, "payback_mid_y": r.payback_mid_y, "quality": r.quality} for r in q.itertuples()])


# ------------------------------------------------------------------ building detail
def _econ_from(body: dict | None):
    body = body or {}
    ea = EconAssumptions()
    for k, v in body.items():
        if hasattr(ea, k) and v is not None:
            setattr(ea, k, tuple(v) if k == "self_consumption_scenarios" else v)
    return ea


def build_detail(a: Area, bid: str, econ: dict | None = None, pv: dict | None = None):
    if bid not in a.idx:
        raise HTTPException(404, "building not found")
    r = a.gdf.iloc[a.idx[bid]]
    pv = pv or {}
    shade = json.loads(r.shade_json)
    bl = np.array(shade["beam_loss"]) / 100.0
    tilt, az = float(pv.get("tilt_deg", 12.0)), float(pv.get("azimuth_deg", 180.0))
    sys_loss = pv.get("system_loss_pct")
    m = pv_model(tilt, az)
    sl = None if sys_loss is None else float(sys_loss) / 100.0
    sh = m.annual(m.beam_loss_series(bl), sl)
    un = m.annual(None, sl)
    kpk, kpk_un = sh["kwh_per_kwp"], un["kwh_per_kwp"]
    ap = m.ap
    ea = _econ_from(econ)
    scen = {}
    for k, s in SCENARIOS.items():
        kwp = EC.capacity_kwp(r.area_m2, s, ap)
        gen = kwp * kpk
        scen[k] = {"share": s, "usable_area_m2": r.area_m2 * s, "capacity_kwp": kwp, "annual_kwh": gen, "annual_kwh_unshaded": kwp * kpk_un,
                   "monthly_kwh": [kwp * x for x in sh["monthly_kwh_per_kwp"]], "economics": EC.economics(kwp, gen, ea, use=(r.subtype if isinstance(r.subtype, str) else None))}
    mon = np.array(sh["monthly_kwh_per_kwp"]); mon_un = np.array(un["monthly_kwh_per_kwp"])
    seasons = {name: {"kwh_per_kwp": float(mon[[x - 1 for x in ms]].sum()), "share_of_year": float(mon[[x - 1 for x in ms]].sum() / mon.sum()),
                      "shading_loss_pct": float((1 - mon[[x - 1 for x in ms]].sum() / mon_un[[x - 1 for x in ms]].sum()) * 100)} for name, ms in SEASONS.items()}
    flags = json.loads(r.quality_flags)
    missing = []
    if r.height_source in ("neighbourhood_fallback",): missing.append("No height from any source; neighbourhood median used (wide range).")
    if r.height_source == "open_buildings_2.5d_temporal_2023": missing.append("Height is a ~4 m resolution ML estimate, not a measurement.")
    if "levels_x_3m" == r.height_source: missing.append("Height inferred from floor count x 3 m.")
    missing += ["Rooftop obstructions (water tanks, stair rooms, parapets) are not detected; usable-area scenarios stand in for them.",
                "Roof type, tilt and orientation are unknown; a south-facing 12° array is assumed.",
                "No field shadow or height measurement exists for this building.",
                "Missing information can make these estimates overly optimistic."]
    sources = {"footprint": "Overture Maps buildings %s (%s)" % (a.meta["datasets"]["overture_release"], r.src_dataset),
               "footprint_crosschecks": {"open_buildings_v3_overlap": bool(r.ob3_overlap), "osm_direct_overlap": bool(r.osm_overlap)},
               "height": r.height_source, "canopy": a.meta["qa"]["trees"].get("source"), "irradiance": "NASA POWER hourly 2015-2024 (typical year), ~0.5°x0.625° grid",
               "dataset_dates": {"overture": a.meta["datasets"]["overture_release"], "open_buildings_temporal": "2023-06-30", "canopy_height": "~2018-2020 (v1)", "nasa_power": "2015-2024"}}
    return clean({
        "id": r.bid, "rank": int(r["rank"]), "source_record": {"dataset": r.src_dataset, "id": r.src_id}, "name": r.osm_name or r["name"], "address": r.osm_addr,
        "centroid": [float(r.geometry.centroid.x), float(r.geometry.centroid.y)], "bounds": list(r.geometry.bounds),
        "building": {"footprint_m2": r.area_m2, "height_m": r.height_m, "height_range_m": [r.height_low_m, r.height_high_m], "height_source": r.height_source,
                     "floors": None if pd.isna(r.num_floors) else r.num_floors, "type": r.subtype or r["class"]},
        "roof": {"total_m2": r.area_m2, "scenarios": {k: {"share": v["share"], "usable_area_m2": v["usable_area_m2"], "capacity_kwp": v["capacity_kwp"]} for k, v in scen.items()}},
        "shading": {"matrix_beam_loss_pct": shade["beam_loss"], "matrix_shaded_pct": shade["shaded_fraction"], "matrix_building_pct": shade["building_fraction"],
                    "matrix_tree_pct": shade["tree_fraction"], "hour_axis": "UTC interval start; IST mid-interval = hour + 6",
                    "mean_shaded_fraction_beam_weighted": r.mean_shaded_fraction, "annual_energy_loss_pct": (1 - kpk / kpk_un) * 100,
                    "tree_share_of_loss_pct": r.tree_energy_share_pct, "n_cells": int(r.n_cells), "shadow_casters_in_range": int(r.n_shadow_candidates), "seasons": seasons},
        "energy": {"kwh_per_kwp_year": kpk, "kwh_per_kwp_year_unshaded": kpk_un, "monthly_kwh_per_kwp": sh["monthly_kwh_per_kwp"],
                   "monthly_kwh_per_kwp_unshaded": un["monthly_kwh_per_kwp"], "scenarios": {k: {kk: vv for kk, vv in v.items() if kk != "economics"} for k, v in scen.items()},
                   "pv_assumptions": {"tilt_deg": tilt, "azimuth_deg": az, "system_loss": m.system_loss if sl is None else sl}},
        "financial": {k: v["economics"] for k, v in scen.items()},
        "transparency": {"quality": r.quality, "flags": flags, "sources": sources, "missing": missing,
                         "uncertainties": ["Height ±%.1f..%.1f m" % (r.height_low_m, r.height_high_m), "Irradiance is regional (NASA POWER ~50 km grid)",
                                           "Trees treated as %.0f%% opaque; canopy data ~2018-2020" % (ap.tree_opacity * 100),
                                           "Financials are indicative; consumer category is inferred from the building use (see /api/assumptions)"]},
    })


@app.get("/api/areas/{area_id}/buildings/{bid}")
def detail(area_id: str, bid: str):
    return build_detail(get_area(area_id), bid)


@app.post("/api/areas/{area_id}/buildings/{bid}/recalculate")
def recalc(area_id: str, bid: str, body: dict = Body(default={})):
    return build_detail(get_area(area_id), bid, body.get("economics"), body.get("pv"))


# ------------------------------------------------------------------ time-dependent shadows
_SHADOW_CACHE: dict = {}


@app.get("/api/areas/{area_id}/shadows")
def shadows(area_id: str, time: str, west: float | None = None, south: float | None = None, east: float | None = None, north: float | None = None):
    a = get_area(area_id)
    ts, az, el = sun_at(time)
    # snap the view outwards to a coarse grid so panning/scrubbing re-uses results
    if None not in (west, south, east, north):
        g = 0.002
        west, south = np.floor(west / g) * g, np.floor(south / g) * g
        east, north = np.ceil(east / g) * g, np.ceil(north / g) * g
    key = (area_id, ts.floor("min").isoformat(), west, south, east, north)
    if key in _SHADOW_CACHE:
        return _SHADOW_CACHE[key]
    out = {"type": "FeatureCollection", "features": [], "sun": {"time": ts.isoformat(), "azimuth": az, "elevation": el}}
    if el <= 1.0:
        return out
    bb = None
    if None not in (west, south, east, north):
        bb = G.to_utm(shapely.box(west, south, east, north)).bounds
    b, t = a.engine.ground_shadows(az, el, bb)
    for kind, geoms in (("building", b), ("tree", t)):
        if geoms:
            u = shapely.union_all(geoms).simplify(0.4)
            u = shapely.set_precision(G.to_wgs(u), 2e-6)
            out["features"].append({"type": "Feature", "properties": {"kind": kind}, "geometry": json.loads(shapely.to_geojson(u))})
    if len(_SHADOW_CACHE) > 200:
        _SHADOW_CACHE.clear()
    _SHADOW_CACHE[key] = out
    return out


@app.get("/api/areas/{area_id}/buildings/{bid}/shade")
def roof_shade(area_id: str, bid: str, time: str):
    a = get_area(area_id)
    if bid not in a.idx:
        raise HTTPException(404, "building not found")
    r = a.gdf.iloc[a.idx[bid]]
    ts, az, el = sun_at(time)
    ap = PVAssumptions()
    xs, ys, step = G.roof_cells(r.geom_utm, ap.cell_size_m, ap.roof_setback_m, ap.max_cells_per_roof)
    cand = a.engine.candidates(r.geom_utm, float(r.height_m), exclude_id=r.bid)
    bld, tre = a.engine.shaded_cells(cand, r.geom_utm, xs, ys, az, el)
    f = a.engine.roof_shade_fractions(cand, r.geom_utm, xs, ys, az, el, ap.tree_opacity) if el > 0 else {"shaded_fraction": 0, "building_fraction": 0, "tree_fraction": 0, "beam_loss": 0}
    feats = []
    h = step / 2
    for x, y, b_, t_ in zip(xs, ys, bld, tre):
        poly = G.to_wgs(shapely.box(x - h, y - h, x + h, y + h))
        feats.append({"type": "Feature", "properties": {"state": "building" if b_ else ("tree" if t_ else "sun")}, "geometry": json.loads(shapely.to_geojson(shapely.set_precision(poly, 1e-8)))})
    names = {}
    if el > 0 and len(cand.idx):
        t = np.tan(np.radians(el)); reach = cand.dh / t
        for j in np.nonzero(cand.dist <= reach)[0]:
            i = cand.idx[j]; oid = str(a.engine.ids[i])
            if oid not in names or cand.dist[j] < names[oid]["distance_m"]:
                names[oid] = {"id": oid, "type": "tree canopy" if a.engine.is_tree[i] else "building", "height_m": float(a.engine.h[i]),
                              "distance_m": float(cand.dist[j]), "shadow_length_m": float(cand.dh[j] / t)}
    names = sorted(names.values(), key=lambda x: x["distance_m"])[:10]
    return clean({"sun": {"time": ts.isoformat(), "azimuth": az, "elevation": el}, "fractions": f, "sources": names,
                  "cells": {"type": "FeatureCollection", "features": feats}})


@app.get("/api/sunpath")
def sunpath(date: str):
    day = to_ist(date + "T00:00")
    sp = SUN.sun_track(day, step_min=20)
    return clean({"date": date, "points": [{"t": str(i.tz_convert(IST).strftime("%H:%M")), "az": float(r.azimuth), "el": float(r.apparent_elevation)} for i, r in sp.iterrows() if r.apparent_elevation > -2]})


# ------------------------------------------------------------------ search (Nominatim proxy, 1 req/s, cached)
_SEARCH = {}
_last = [0.0]


@app.get("/api/search")
def search(q: str = Query(min_length=2)):
    key = q.strip().lower()
    import re
    m = re.match(r"^\s*(-?\d+\.\d+)\s*[, ]\s*(-?\d+\.\d+)\s*$", q)
    if m:
        la, lo = float(m.group(1)), float(m.group(2))
        return [{"name": f"{la:.5f}, {lo:.5f}", "lat": la, "lon": lo, "bbox": None, "kind": "coordinates"}]
    if key in _SEARCH:
        return _SEARCH[key]
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": q, "format": "jsonv2", "limit": 6, "countrycodes": "in", "viewbox": "77.3,13.2,77.9,12.7"},
                         headers=ingest.UA, timeout=15)
        r.raise_for_status()
        res = [{"name": x["display_name"], "lat": float(x["lat"]), "lon": float(x["lon"]), "kind": x.get("type"),
                "bbox": [float(x["boundingbox"][2]), float(x["boundingbox"][0]), float(x["boundingbox"][3]), float(x["boundingbox"][1])]} for x in r.json()]
    except Exception as ex:
        raise HTTPException(502, f"Nominatim unavailable: {type(ex).__name__}")
    _SEARCH[key] = res
    return res


# ------------------------------------------------------------------ analysis jobs for another area
JOBS: dict[str, dict] = {}
MAX_JOB_KM2 = float(os.environ.get("RSE_MAX_JOB_KM2", "2.5"))


def _run_job(jid, area_id, name, bbox):
    j = JOBS[jid]
    try:
        j.update(state="running", message="Downloading open datasets", progress=0.01)
        st = ingest.ingest_area(area_id, bbox, log=lambda m: j.update(message=m))
        j["ingest"] = st
        if st.get("overture") != "ok":
            raise RuntimeError("building footprints unavailable: " + st.get("overture", ""))
        meta = pipeline.analyze_area(area_id, bbox, name=name, cb=lambda m, f: j.update(message=m, progress=0.05 + 0.95 * (f or 0)))
        _AREAS.pop(area_id, None)
        j.update(state="done", progress=1.0, message="Analysis complete", area_id=area_id, quality_counts=meta["quality_counts"])
    except Exception as ex:
        j.update(state="failed", message=f"{type(ex).__name__}: {str(ex)[:300]}")


@app.post("/api/jobs")
def new_job(body: dict = Body(...)):
    try:
        bbox = tuple(float(x) for x in body["bbox"])
    except Exception:
        raise HTTPException(422, "bbox must be [west, south, east, north]")
    w, s, e, n = bbox
    if not (w < e and s < n and 68 < w < 98 and 6 < s < 38):
        raise HTTPException(422, "bbox must be a valid area in India")
    km2 = G.bbox_area_km2(bbox)
    if km2 > MAX_JOB_KM2:
        raise HTTPException(422, f"area {km2:.1f} km² exceeds the {MAX_JOB_KM2} km² analysis limit")
    name = str(body.get("name") or "Custom area")[:80]
    area_id = "area-" + uuid.uuid4().hex[:8]
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"id": jid, "state": "queued", "progress": 0.0, "message": "Queued", "area_id": area_id, "bbox": bbox, "km2": km2}
    threading.Thread(target=_run_job, args=(jid, area_id, name, bbox), daemon=True).start()
    return JOBS[jid]


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[jid]


# ------------------------------------------------------------------ contributions (always unverified)
@app.post("/api/contributions")
def contribute(body: dict = Body(...)):
    rec = {"id": uuid.uuid4().hex[:10], "received": pd.Timestamp.utcnow().isoformat(), "status": "unverified",
           "building_id": str(body.get("building_id", ""))[:80], "roof_type": str(body.get("roof_type", ""))[:40],
           "obstructions": [str(x)[:40] for x in body.get("obstructions", [])][:10], "tall_trees_nearby": bool(body.get("tall_trees_nearby", False)),
           "photo_url": str(body.get("photo_url", ""))[:300], "notes": str(body.get("notes", ""))[:1000]}
    if not rec["building_id"]:
        raise HTTPException(422, "building_id required")
    with open(CONTRIB / "contributions.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"ok": True, "id": rec["id"], "status": "unverified", "note": "Stored as unverified; it does not change any calculation until reviewed."}


# ------------------------------------------------------------------ validation
HEIGHT_CSV = VALID / "height_measurements.csv"
SHADOW_CSV = VALID / "shadow_checks.csv"


def _append(path, header, row):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(header)
        w.writerow(row)


@app.post("/api/validation/height-measurements")
def add_height(body: dict = Body(...)):
    try:
        bid, h = str(body["building_id"]), float(body["height_m"])
        assert 1 <= h <= 200
    except Exception:
        raise HTTPException(422, "building_id and height_m (1-200) required")
    _append(HEIGHT_CSV, ["building_id", "height_m", "method", "measured_on", "measured_by", "notes"],
            [bid, h, body.get("method", ""), body.get("measured_on", ""), body.get("measured_by", ""), body.get("notes", "")])
    return {"ok": True, "note": "Re-run the pipeline to refit the footprint model and re-label the building as measured."}


@app.post("/api/validation/shadow-checks")
def add_shadow(body: dict = Body(...)):
    try:
        bid, t, frac = str(body["building_id"]), str(body["time"]), float(body["observed_shaded_fraction"])
        assert 0 <= frac <= 1
    except Exception:
        raise HTTPException(422, "building_id, time (ISO) and observed_shaded_fraction (0-1) required")
    _append(SHADOW_CSV, ["building_id", "time", "observed_shaded_fraction", "method", "notes"], [bid, t, frac, body.get("method", ""), body.get("notes", "")])
    return {"ok": True}


@app.get("/api/areas/{area_id}/validation")
def validation(area_id: str):
    a = get_area(area_id)
    # (1) unshaded yield vs PVGIS (independent; not an input)
    pvg = None
    p = RAW / "pvgis_PVGIS-ERA5.json"
    if p.exists():
        t = json.loads(p.read_text())["outputs"]["totals"]["fixed"]
        m = pv_model(12.0, 180.0)
        mine14 = m.annual(None, 0.14)["kwh_per_kwp"]
        raw_m = pv_model(12.0, 180.0, 0.0, False)
        pvg = {"pvgis_database": "PVGIS-ERA5", "pvgis_E_y_kwh_per_kwp": t["E_y"], "pvgis_H_i_y_kwh_m2": t["H(i)_y"], "tilt_deg": 12, "azimuth": "south", "system_loss_pct": 14,
               "model_E_y_kwh_per_kwp_same_loss": mine14, "difference_pct": (mine14 / t["E_y"] - 1) * 100,
               "model_poa_kwh_m2": m.poa_annual_kwh_m2(), "poa_difference_pct": (m.poa_annual_kwh_m2() / t["H(i)_y"] - 1) * 100,
               "without_component_closure_correction": {"E_y": raw_m.annual(None, 0.14)["kwh_per_kwp"], "poa": raw_m.poa_annual_kwh_m2(),
                                                        "difference_pct": (raw_m.annual(None, 0.14)["kwh_per_kwp"] / t["E_y"] - 1) * 100},
               "note": "PVGIS uses ERA5 irradiance, NASA POWER is the model input: they are independent datasets. The closure correction was motivated by NASA's own GHI/DNI/DHI imbalance, not tuned to PVGIS."}
    hm = pd.read_csv(HEIGHT_CSV) if HEIGHT_CSV.exists() else pd.DataFrame()
    sc = pd.read_csv(SHADOW_CSV) if SHADOW_CSV.exists() else pd.DataFrame()
    shadow_val = {"n_checks": int(len(sc)), "required": "3-5 roofs at 3 times of day", "status": "not performed" if len(sc) == 0 else "partial"}
    if len(sc):
        errs = []
        for r in sc.itertuples():
            if r.building_id in a.idx:
                try:
                    d = roof_shade(area_id, r.building_id, r.time)
                    errs.append(d["fractions"]["shaded_fraction"] - r.observed_shaded_fraction)
                except Exception:
                    pass
        if errs:
            shadow_val.update(mae=float(np.mean(np.abs(errs))), bias=float(np.mean(errs)), n_compared=len(errs), status="complete" if len(errs) >= 9 else "partial")
    height_val = {"n_measured": int(len(hm)), "required": "10-15 buildings", "status": "not performed" if len(hm) == 0 else ("model calibrated" if a.meta["height_model"].get("calibrated") else "insufficient")}
    if len(hm):
        comp = []
        for r in hm.itertuples():
            if r.building_id in a.idx:
                g = a.gdf.iloc[a.idx[r.building_id]]
                comp.append(g.height_m - r.height_m)
        if comp:
            height_val.update(compared=len(comp), dataset_height_mae_m=float(np.mean(np.abs(comp))), dataset_height_bias_m=float(np.mean(comp)))
    return clean({"pvgis_comparison": pvg, "height_measurements": height_val, "height_model": a.meta["height_model"], "shadow_field_checks": shadow_val,
                  "footprint_qa": a.meta["qa"]["cross_check"], "footprint_qa_sample_of_20_roofs": "not performed - needs legally accessible imagery or a field visit; record results via the data-entry workflow",
                  "tree_second_pass": a.meta["qa"]["trees"].get("second_pass_osm_tree_nodes", "OSM trees unavailable in this build"),
                  "claim": "No field validation is claimed. Results are model estimates."})


# ------------------------------------------------------------------ frontend
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
