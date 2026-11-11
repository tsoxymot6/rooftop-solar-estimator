"""End-to-end analysis of one study area: footprints -> QA -> heights -> canopy -> shadows -> energy -> economics."""
from __future__ import annotations
import json, math, pickle, hashlib, time
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import rasterio.features
import shapely
from shapely import wkt
from shapely.geometry import shape, Point, box, mapping, Polygon, MultiPolygon

from . import geometry as G, heights as H, shadow as SH, economics as EC
from .config import PVAssumptions, EconAssumptions, SCENARIOS, RAW, PROCESSED, CACHE, DATA
from .pv import PVModel, load_nasa_hourly, build_typical_year, detect_interval_offset_minutes
from .ingest import area_dir, pad_bbox

PIPELINE_VERSION = "1"
TREE_MIN_H, TREE_MAX_H, TREE_MIN_AREA = 3.0, 35.0, 6.0
CLASS_EDGES = [3, 6, 10, 15, 36]


def _log(cb, msg, frac=None):
    if cb:
        cb(msg, frac)


# ------------------------------------------------------------------ footprints
def load_footprints(area_id, bbox, cb=None):
    raw = pd.read_parquet(area_dir(area_id) / "overture_buildings.parquet")
    geoms = shapely.from_wkt(raw["wkt"].values)
    gdf = gpd.GeoDataFrame(raw.drop(columns=["wkt"]), geometry=geoms, crs=4326)
    n0 = len(gdf)
    gdf["geometry"] = shapely.make_valid(gdf.geometry.values)
    gdf = gdf.explode(index_parts=False)
    gdf = gdf[gdf.geometry.geom_type == "Polygon"].copy()
    gdf["geom_utm"] = G.to_utm(gdf.geometry.values)
    gdf["area_m2"] = [G.geodesic_area_m2(g) for g in gdf.geometry.values]
    gdf = gdf[gdf.area_m2 >= 3.0].reset_index(drop=True)
    gdf["bid"] = gdf["id"].astype(str)
    # duplicates inside the conflated product: IoU > 0.5 -> keep the larger
    tree = shapely.STRtree(gdf.geom_utm.values)
    a, b = tree.query(gdf.geom_utm.values, predicate="intersects")
    m = a < b
    a, b = a[m], b[m]
    inter = shapely.area(shapely.intersection(gdf.geom_utm.values[a], gdf.geom_utm.values[b]))
    union = gdf.area_m2.values[a] + gdf.area_m2.values[b] - inter
    iou = inter / np.maximum(union, 1e-9)
    drop = set()
    for i, j, v in zip(a[iou > 0.5], b[iou > 0.5], iou[iou > 0.5]):
        drop.add(j if gdf.area_m2.values[i] >= gdf.area_m2.values[j] else i)
    dup_mask = np.zeros(len(gdf), bool)
    dup_mask[list(drop)] = True
    # overlap (0.1..0.5 IoU) pairs are kept but flagged
    susp = set(a[(iou > 0.1) & (iou <= 0.5)]) | set(b[(iou > 0.1) & (iou <= 0.5)])
    gdf["overlap_flag"] = [i in susp for i in range(len(gdf))]
    qa = {"overture_rows_in_padded_bbox": int(n0), "after_validity_and_size_filter": int(len(gdf)), "duplicates_removed_iou_gt_0.5": int(dup_mask.sum()),
          "overlap_flagged_iou_0.1_0.5": int(len(susp))}
    gdf = gdf[~dup_mask].reset_index(drop=True)
    w, s, e, n = bbox
    study = box(w, s, e, n)
    c = gdf.geometry.representative_point()
    gdf["in_study"] = shapely.contains_xy(study, c.x.values, c.y.values)
    return gdf, qa


def crosscheck_sources(gdf, area_id, bbox, cb=None):
    """Overture vs Open Buildings V3 vs OSM(direct): missing / single-source structures. Recorded, never silently ignored."""
    qa, missing = {}, []
    study = G.to_utm(box(*bbox))
    tree = shapely.STRtree(gdf.geom_utm.values)
    gdf["ob3_overlap"] = False
    gdf["osm_overlap"] = False
    p = area_dir(area_id) / "open_buildings_v3.parquet"
    if p.exists():
        ob = pd.read_parquet(p)
        ob = ob[ob.confidence >= 0.70]
        g = G.to_utm(shapely.from_wkt(ob.geometry.values))
        ob = ob.assign(g=g)
        ob = ob[shapely.intersects(study, ob.g.values)]
        a, b = tree.query(ob.g.values, predicate="intersects")
        has = np.zeros(len(ob), bool); has[np.unique(a)] = True
        gdf.loc[np.unique(b), "ob3_overlap"] = True
        miss = ob[(~has) & (ob.area_in_meters >= 15)]
        for _, r in miss.iterrows():
            missing.append({"source": "open_buildings_v3", "confidence": float(r.confidence), "area_m2": float(r.area_in_meters),
                            "geometry": shapely.geometry.mapping(G.to_wgs(r.g))})
        qa["open_buildings_v3"] = {"polygons_conf>=0.70_in_study": int(len(ob)), "not_in_overture_>=15m2": int(len(miss)),
                                   "share_of_overture_with_ob3_overlap": float(gdf.loc[gdf.in_study, "ob3_overlap"].mean())}
    else:
        qa["open_buildings_v3"] = "unavailable"
    p = area_dir(area_id) / "osm.json"
    gdf["osm_name"] = None; gdf["osm_addr"] = None; gdf["osm_levels"] = np.nan; gdf["osm_height"] = np.nan
    if p.exists():
        o = json.loads(p.read_text())
        els = [e for e in o.get("buildings", []) if e.get("geometry") and len(e["geometry"]) >= 4]
        if els:
            polys = [Polygon([(q["lon"], q["lat"]) for q in e["geometry"]]) for e in els]
            polys = [pp if pp.is_valid else shapely.make_valid(pp) for pp in polys]
            polys = [G.to_utm(pp) for pp in polys]
            a, b = tree.query(np.array(polys, dtype=object), predicate="intersects")
            ov = np.zeros(len(els), bool); ov[np.unique(a)] = True
            gdf.loc[np.unique(b), "osm_overlap"] = True
            # attach address/name/levels/height tags to the Overture polygon with the largest overlap
            best = {}
            for ia, ib in zip(a, b):
                ar = shapely.area(shapely.intersection(polys[ia], gdf.geom_utm.values[ib]))
                if ar > best.get(ia, (0, None))[0]:
                    best[ia] = (ar, ib)
            for ia, (ar, ib) in best.items():
                tg = els[ia].get("tags", {})
                if tg.get("name"): gdf.at[ib, "osm_name"] = tg["name"]
                addr = " ".join(x for x in [tg.get("addr:housenumber"), tg.get("addr:street"), tg.get("addr:suburb") or tg.get("addr:neighbourhood")] if x)
                if addr: gdf.at[ib, "osm_addr"] = addr
                try:
                    if tg.get("building:levels"): gdf.at[ib, "osm_levels"] = float(str(tg["building:levels"]).split(";")[0])
                except ValueError: pass
                try:
                    if tg.get("height"): gdf.at[ib, "osm_height"] = float(str(tg["height"]).lower().replace("m", "").strip())
                except ValueError: pass
            inside = shapely.intersects(study, np.array(polys, dtype=object))
            qa["osm_direct"] = {"buildings_in_study": int(inside.sum()), "without_overture_overlap": int((inside & ~ov).sum()),
                                "with_height_tag": int(sum(1 for e in els if "height" in e.get("tags", {}))),
                                "with_levels_tag": int(sum(1 for e in els if "building:levels" in e.get("tags", {}))),
                                "mirror": o.get("mirror")}
            for i in np.nonzero(inside & ~ov)[0]:
                missing.append({"source": "osm", "area_m2": float(polys[i].area), "geometry": shapely.geometry.mapping(G.to_wgs(polys[i]))})
        else:
            qa["osm_direct"] = "no buildings returned"
    else:
        qa["osm_direct"] = "unavailable"
    return gdf, qa, missing


# ------------------------------------------------------------------ heights
def zonal_heights(gdf, area_id):
    p = area_dir(area_id) / "oba_temporal_2023.tif"
    gdf["raster_h"], gdf["raster_cov"] = np.nan, np.nan
    if not p.exists():
        return gdf, {"status": "unavailable"}
    with rasterio.open(p) as ds:
        hgt, pres = ds.read(2), ds.read(3)
        tr = ds.transform
        shapes = [(g, i + 1) for i, g in enumerate(gdf.geom_utm.values)]
        lab = rasterio.features.rasterize(shapes, out_shape=hgt.shape, transform=tr, fill=0, dtype="int32", all_touched=False)
    m = lab > 0
    df = pd.DataFrame({"lab": lab[m], "h": hgt[m], "p": pres[m]})
    df["ok"] = (df.p >= 0.5) & (df.h > 0)
    cov = df.groupby("lab")["ok"].mean()
    med = df[df.ok].groupby("lab")["h"].median()
    cnt = df.groupby("lab").size()
    idx = np.arange(len(gdf)) + 1
    gdf["raster_cov"] = cov.reindex(idx).values
    gdf["raster_h"] = med.reindex(idx).values
    gdf.loc[cnt.reindex(idx).fillna(0).values < 4, ["raster_h", "raster_cov"]] = np.nan   # too few pixels (small roofs @ ~4 m native res)
    return gdf, {"status": "ok", "buildings_with_raster_height": int(np.isfinite(gdf.raster_h).sum()), "median_raster_height_m": float(np.nanmedian(gdf.raster_h))}


def load_measurements():
    p = DATA / "validation" / "height_measurements.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


# ------------------------------------------------------------------ trees
def canopy_patches(area_id, gdf, bbox, cb=None):
    p = area_dir(area_id) / "canopy_chm.tif"
    qa = {"source": "Meta/WRI Global Canopy Height Map v1 (1.2 m, ~2018-2020 vintage)"}
    if not p.exists():
        return gpd.GeoDataFrame({"tid": [], "height_m": [], "kind": []}, geometry=[], crs=32643), {"status": "unavailable", **qa}
    import pyproj
    with rasterio.open(p) as ds:
        chm = ds.read(1).astype("float32"); tr = ds.transform; crs = ds.crs
        t = pyproj.Transformer.from_crs(32643, crs, always_xy=True)
        bl = shapely.transform(shapely.buffer(gdf.geom_utm.values, 1.0), lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))
        bmask = rasterio.features.rasterize([(g, 1) for g in bl], out_shape=chm.shape, transform=tr, fill=0, dtype="uint8").astype(bool)
    raw_tree = (chm >= TREE_MIN_H)
    too_high = raw_tree & (chm > TREE_MAX_H)
    tree = raw_tree & ~bmask & ~too_high
    cls = np.zeros(chm.shape, "uint8")
    for k in range(len(CLASS_EDGES) - 1):
        cls[tree & (chm >= CLASS_EDGES[k]) & (chm < CLASS_EDGES[k + 1])] = k + 1
    cls_h = {k + 1: float(np.mean(chm[cls == k + 1])) if (cls == k + 1).any() else 0.0 for k in range(len(CLASS_EDGES) - 1)}
    inv = pyproj.Transformer.from_crs(crs, 32643, always_xy=True)
    rows = []
    for geom, v in rasterio.features.shapes(cls, mask=cls > 0, transform=tr):
        g = shape(geom)
        g = shapely.transform(g, lambda c: np.column_stack(inv.transform(c[:, 0], c[:, 1])))
        g = g.simplify(0.8)
        if g.is_empty or g.area < TREE_MIN_AREA:
            continue
        rows.append((g if g.is_valid else shapely.make_valid(g), cls_h[int(v)]))
    out = gpd.GeoDataFrame({"height_m": [r[1] for r in rows]}, geometry=[r[0] for r in rows], crs=32643)
    out = out[out.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].explode(index_parts=False).reset_index(drop=True)
    out = out[out.geometry.area >= TREE_MIN_AREA].reset_index(drop=True)
    out["tid"] = [f"tree-{i}" for i in range(len(out))]
    out["kind"] = "canopy"
    qa.update({"status": "ok", "pixels_ge_3m_total": int(raw_tree.sum()), "pixels_excluded_inside_buildings": int((raw_tree & bmask).sum()),
               "pixels_excluded_height_gt_35m_artefact": int(too_high.sum()), "patches_kept": int(len(out)),
               "patches_dropped_lt_6m2": "applied", "class_mean_heights_m": {str(k): round(v, 1) for k, v in cls_h.items()}})
    # second-pass review against OSM trees (independent mapped data) - unsupported mapped trees are flagged, not used
    po = area_dir(area_id) / "osm.json"
    if po.exists():
        o = json.loads(po.read_text())
        nodes = [e for e in o.get("trees", []) if e["type"] == "node"]
        if nodes:
            sup = 0
            for e in nodes:
                x, y = pyproj.Transformer.from_crs(4326, crs, always_xy=True).transform(e["lon"], e["lat"])
                c, r = ~tr * (x, y)
                r0, c0 = int(r), int(c)
                win = chm[max(r0 - 3, 0): r0 + 4, max(c0 - 3, 0): c0 + 4]
                sup += int(win.size > 0 and np.nanmax(win) >= TREE_MIN_H)
            qa["second_pass_osm_tree_nodes"] = {"mapped_trees": len(nodes), "supported_by_canopy_height": sup, "unsupported_flagged_unverified": len(nodes) - sup,
                                               "note": "OSM tree points are never used as shadow casters without canopy support (position/height unreliable)"}
    return out, qa


# ------------------------------------------------------------------ main
def _pv_inputs():
    ty_p, meta_p = PROCESSED / "typical_year.parquet", PROCESSED / "typical_year_meta.json"
    if ty_p.exists() and meta_p.exists():
        return pd.read_parquet(ty_p), json.loads(meta_p.read_text())
    df = load_nasa_hourly(RAW / "nasa_power_hourly_2015_2024.parquet")
    ty, meta = build_typical_year(df, detect_interval_offset_minutes(df))
    ty.to_parquet(ty_p); meta_p.write_text(json.dumps(meta, indent=1))
    return ty, meta


def analyze_area(area_id, bbox, name=None, ap: PVAssumptions | None = None, cb=None, limit=None):
    t0 = time.time()
    ap = ap or PVAssumptions()
    _log(cb, "Loading building footprints", 0.02)
    gdf, qa_fp = load_footprints(area_id, bbox)
    _log(cb, "Cross-checking Overture / Open Buildings / OSM", 0.06)
    gdf, qa_cross, missing = crosscheck_sources(gdf, area_id, bbox)
    _log(cb, "Sampling Open Buildings 2.5D height raster", 0.10)
    gdf, qa_h = zonal_heights(gdf, area_id)
    meas = load_measurements()
    gdf["measured_h"] = np.nan
    model = H.FootprintHeightModel()
    if meas is not None and len(meas):
        m = meas.dropna(subset=["height_m"])
        mm = dict(zip(m["building_id"].astype(str), m["height_m"]))
        gdf["measured_h"] = gdf["bid"].map(mm).astype(float)
        sub = gdf.dropna(subset=["measured_h"])
        model.fit(sub.area_m2.values, sub.measured_h.values)
    # combine mapped height attributes: Overture `height` (OSM/other) falls back to OSM direct tag
    gdf["height"] = gdf["height"].astype(float)
    gdf.loc[gdf.height.isna(), "height"] = gdf.loc[gdf.height.isna(), "osm_height"]
    gdf["num_floors"] = gdf["num_floors"].astype(float)
    gdf.loc[gdf.num_floors.isna(), "num_floors"] = gdf.loc[gdf.num_floors.isna(), "osm_levels"]
    gdf = H.assign_heights(gdf, model)
    _log(cb, "Building canopy shadow casters", 0.15)
    trees, qa_t = canopy_patches(area_id, gdf, bbox)
    # ---- shadow engine
    eng = SH.ShadowEngine(
        list(gdf.geom_utm.values) + list(trees.geometry.values),
        list(gdf.height_m.values) + list(trees.height_m.values),
        [False] * len(gdf) + [True] * len(trees),
        list(gdf.bid.values) + list(trees.tid.values), max_shadow_m=ap.max_shadow_m)
    ty, ty_meta = _pv_inputs()
    pvm = PVModel(ty, ap)
    suns = pvm.sun_table(ap.min_sun_elevation_deg)
    base = pvm.annual()
    sys_loss = pvm.system_loss
    # ---- per-building analysis
    todo = np.nonzero(gdf.in_study.values)[0]
    if limit:
        todo = todo[:limit]
    cache_p = CACHE / f"shade_{area_id}.pkl"
    cache = pickle.loads(cache_p.read_bytes()) if cache_p.exists() else {}
    cells_cfg = f"{ap.cell_size_m}|{ap.roof_setback_m}|{ap.max_cells_per_roof}|{ap.tree_opacity}|{ap.max_shadow_m}|{ap.min_sun_elevation_deg}"
    res = {}
    hits = 0
    for n_done, i in enumerate(todo):
        row = gdf.iloc[i]
        target = row.geom_utm
        cand = eng.candidates(target, float(row.height_m), exclude_id=row.bid)
        key = hashlib.sha1(f"{row.bid}|{target.wkb_hex[:200]}|{row.height_m:.2f}|{eng.signature(cand)}|{cells_cfg}".encode()).hexdigest()
        if key in cache:
            prof = cache[key]; hits += 1
        else:
            xs, ys, step = G.roof_cells(target, ap.cell_size_m, ap.roof_setback_m, ap.max_cells_per_roof)
            prof, _ = eng.shade_profile(target, float(row.height_m), xs, ys, suns, exclude_id=row.bid, tree_opacity=ap.tree_opacity, cand=cand)
            prof["n_cells"] = int(len(xs)); prof["n_candidates"] = int(len(cand.idx))
            cache[key] = prof
        bl = prof["beam_loss"]
        yr = pvm.annual(pvm.beam_loss_series(bl), sys_loss)
        res[i] = (prof, yr)
        if n_done % 100 == 0:
            _log(cb, f"Shading & energy: {n_done}/{len(todo)} buildings", 0.2 + 0.7 * n_done / max(len(todo), 1))
    cache_p.write_bytes(pickle.dumps(cache))
    # ---- assemble table
    out = gdf.loc[list(res.keys())].copy()
    unsh = pvm.annual(None, sys_loss)
    out["kwh_per_kwp_unshaded"] = unsh["kwh_per_kwp"]
    out["kwh_per_kwp"] = [res[i][1]["kwh_per_kwp"] for i in out.index]
    out["shading_loss_pct"] = (1 - out.kwh_per_kwp / out.kwh_per_kwp_unshaded) * 100
    out["monthly_kwh_per_kwp"] = [json.dumps([round(x, 2) for x in res[i][1]["monthly_kwh_per_kwp"]]) for i in out.index]
    def pack(i):
        p = res[i][0]
        return json.dumps({k: np.round(p[k] * 100).astype(int).tolist() for k in ("beam_loss", "shaded_fraction", "building_fraction", "tree_fraction")})
    out["shade_json"] = [pack(i) for i in out.index]
    out["n_cells"] = [res[i][0]["n_cells"] for i in out.index]
    out["n_shadow_candidates"] = [res[i][0]["n_candidates"] for i in out.index]
    # sun-weighted mean shaded fraction (share of roof in direct shadow, weighted by DNI-on-plane energy)
    w = pvm.poa_direct
    def wmean(i):
        s = res[i][0]["shaded_fraction"]
        ser = pvm.beam_loss_series(s)
        return float((ser * w).sum() / max(w.sum(), 1e-9))
    out["mean_shaded_fraction"] = [wmean(i) for i in out.index]
    out["tree_energy_share_pct"] = [float(100 * (res[i][0]["tree_fraction"] * ap.tree_opacity).sum() / max(res[i][0]["beam_loss"].sum(), 1e-9)) for i in out.index]
    for k, s in SCENARIOS.items():
        out[f"usable_{k}_m2"] = out.area_m2 * s
        out[f"kwp_{k}"] = out[f"usable_{k}_m2"] / ap.roof_area_per_kwp
        out[f"kwh_{k}"] = out[f"kwp_{k}"] * out.kwh_per_kwp
    ea = EconAssumptions()
    ec = [EC.economics(r.kwp_middle, r.kwh_middle, ea, use=(r.subtype if isinstance(r.subtype, str) else None)) for r in out.itertuples()]
    out["cost_mid_inr"] = [e["cost_inr"]["mid"] for e in ec]
    out["savings_mid_inr"] = [e["annual_savings_inr"]["mid"] for e in ec]
    out["payback_mid_y"] = [e["payback_years"]["mid"] for e in ec]
    out["payback_best_y"] = [e["payback_years"]["best"] for e in ec]
    out["payback_worst_y"] = [e["payback_years"]["worst"] for e in ec]
    # ---- data-quality status & flags
    flags, status = [], []
    for r in out.itertuples():
        f = list(r.height_flags)
        if r.overlap_flag: f.append("overlapping_footprints")
        if not (r.ob3_overlap or r.osm_overlap): f.append("single_source_footprint")
        if r.tree_energy_share_pct > 40 and r.shading_loss_pct > 3: f.append("tree_shading_unverified")
        if r.kwp_middle < 1.0: f.append("below_1kw_at_middle_scenario")
        flags.append(f)
        if r.height_status == "measured": status.append("measured")
        elif r.height_status == "unverified" or "overlapping_footprints" in f: status.append("unverified")
        else: status.append("estimated")
    out["quality_flags"], out["quality"] = flags, status
    out = out.sort_values("kwh_middle", ascending=False)
    out["rank"] = np.arange(1, len(out) + 1)
    out = out.sort_index()
    out["geometry"] = out.geometry
    # ---- persist
    d = PROCESSED / area_id
    d.mkdir(parents=True, exist_ok=True)
    keep = [c for c in out.columns if c not in ("geom_utm",)]
    sv = gpd.GeoDataFrame(out[keep].drop(columns=["geometry"]), geometry=out.geometry, crs=4326)
    for c in ("height_flags", "quality_flags"):
        sv[c] = sv[c].apply(json.dumps)
    sv.to_parquet(d / "buildings.parquet")
    obs = gpd.GeoDataFrame({"oid": list(gdf.bid.values) + list(trees.tid.values), "height_m": list(gdf.height_m.values) + list(trees.height_m.values),
                            "is_tree": [False] * len(gdf) + [True] * len(trees)}, geometry=list(gdf.geom_utm.values) + list(trees.geometry.values), crs=32643)
    obs.to_parquet(d / "obstacles_utm.parquet")
    tw = trees.copy(); tw = tw.to_crs(4326); tw.to_parquet(d / "trees.parquet")
    (d / "qa_missing_buildings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {k: v for k, v in m.items() if k != "geometry"}, "geometry": m["geometry"]} for m in missing]}))
    meta = {
        "area_id": area_id, "name": name or area_id, "bbox": list(bbox), "bbox_area_km2": G.bbox_area_km2(bbox), "pipeline_version": PIPELINE_VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - t0, 1),
        "n_buildings_analysed": int(len(out)), "n_obstacle_buildings": int(len(gdf)), "n_tree_patches": int(len(trees)), "cache_hits": hits,
        "quality_counts": {k: int((out.quality == k).sum()) for k in ("measured", "estimated", "unverified")},
        "height_source_counts": out.height_source.value_counts().to_dict(),
        "qa": {"footprints": qa_fp, "cross_check": qa_cross, "heights": qa_h, "trees": qa_t, "possible_missing_structures": len(missing)},
        "pv_assumptions": ap.to_dict(), "typical_year": ty_meta, "unshaded_kwh_per_kwp": unsh["kwh_per_kwp"],
        "poa_kwh_m2": pvm.poa_annual_kwh_m2(), "closure_factor_mean": pvm.closure_factor_mean,
        "height_model": model.report,
        "datasets": {"overture_release": "2026-10-21.0", "open_buildings_v3": "v3 polygons (S2 level 6)", "open_buildings_temporal": "v1 2023-06-30",
                     "canopy_height": "Meta/WRI v1 (alsgedi_global_v6_float)", "nasa_power": "hourly 2015-2024 (MERRA-2/CERES)", },
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    _log(cb, "Done", 1.0)
    return meta
