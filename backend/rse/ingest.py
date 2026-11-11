"""Open-data acquisition for any bbox (no credentials). Every function writes into data/raw/<area_id>/ and is idempotent.

Sources (all public, unauthenticated):
  Overture Maps buildings        s3://overturemaps-us-west-2/release/<RELEASE>/theme=buildings   (ODbL / CDLA-P; OSM-derived rows ODbL)
  Google Open Buildings V3       gs://open-buildings-data/v3/polygons_s2_level_6_gzip_no_header   (CC BY 4.0 / ODbL)
  Open Buildings 2.5D Temporal   gs://open-buildings-temporal-data/v1  (building_height band)     (CC BY 4.0)
  Meta/WRI Canopy Height Map v1  s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/chm  (CC BY 4.0)
  OSM via Overpass               trees / tree rows / woods / buildings with tags                    (ODbL)
  NASA POWER hourly              power.larc.nasa.gov                                                (public domain)
  PVGIS PVcalc                   re.jrc.ec.europa.eu (comparison only)
"""
from __future__ import annotations
import os, json, math, time
from pathlib import Path
import numpy as np
import requests

from .config import RAW, OBSTACLE_PAD_DEG

OVERTURE_RELEASE = "2026-10-21.0"
OBA_BUCKET = "https://storage.googleapis.com/open-buildings-temporal-data"
OBA_YEAR_SUFFIX = "2023_06_30"
UA = {"User-Agent": "RooftopSolarEstimator/0.1 (open-source student project%s)" % (" " + os.environ["RSE_NOMINATIM_EMAIL"] if os.environ.get("RSE_NOMINATIM_EMAIL") else ""), "Accept": "application/json"}


def area_dir(area_id: str) -> Path:
    d = RAW / area_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def pad_bbox(bbox, pad=OBSTACLE_PAD_DEG):
    w, s, e, n = bbox
    return (w - pad, s - pad, e + pad, n + pad)


# ------------------------------------------------------------------ Overture
def fetch_overture(area_id, bbox):
    out = area_dir(area_id) / "overture_buildings.parquet"
    if out.exists():
        return out
    import duckdb
    w, s, e, n = pad_bbox(bbox)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    con.execute(f"""
    COPY (SELECT id, ST_AsText(geometry) AS wkt, height, num_floors, subtype, class, names.primary AS name,
                 sources[1].dataset AS src_dataset, sources[1].record_id AS src_id, has_parts
          FROM read_parquet('s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=buildings/type=building/*', hive_partitioning=1)
          WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}) TO '{out}' (FORMAT PARQUET);""")
    return out


# ------------------------------------------------------------------ Open Buildings V3 polygons (cross-check)
def fetch_open_buildings_v3(area_id, bbox):
    import gzip, pandas as pd, s2sphere
    out = area_dir(area_id) / "open_buildings_v3.parquet"
    if out.exists():
        return out
    w, s, e, n = pad_bbox(bbox)
    tok = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees((s + n) / 2, (w + e) / 2)).parent(6).to_token()
    url = f"https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_6_gzip_no_header/{tok}_buildings.csv.gz"
    cols = ["latitude", "longitude", "area_in_meters", "confidence", "geometry", "full_plus_code"]
    keep = []
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        for ch in pd.read_csv(gzip.GzipFile(fileobj=r.raw), names=cols, header=None, chunksize=400_000):
            sub = ch[ch.longitude.between(w, e) & ch.latitude.between(s, n)]
            if len(sub):
                keep.append(sub)
    (pd.concat(keep) if keep else pd.DataFrame(columns=cols)).to_parquet(out)
    return out


# ------------------------------------------------------------------ Open Buildings 2.5D Temporal heights
def _utm_epsg(lon):
    return 32600 + int((lon + 180) // 6) + 1


def _oba_manifest_index():
    idx = RAW / "oba_manifest_index.json"
    if idx.exists():
        return json.loads(idx.read_text())
    names, tok = [], None
    while True:
        p = {"prefix": "v1/manifests/", "maxResults": 1000}
        if tok:
            p["pageToken"] = tok
        d = requests.get("https://storage.googleapis.com/storage/v1/b/open-buildings-temporal-data/o", params=p, timeout=60).json()
        names += [i["name"] for i in d.get("items", [])]
        tok = d.get("nextPageToken")
        if not tok:
            break
    idx.write_text(json.dumps(names))
    return names


def find_oba_tile(bbox):
    """Locate the 12.5 km GeoTIFF tile (and its UTM grid) containing the bbox."""
    import pyproj
    w, s, e, n = bbox
    epsg = _utm_epsg((w + e) / 2)
    t = pyproj.Transformer.from_crs(4326, epsg, always_xy=True)
    x0, y0 = t.transform(w, s); x1, y1 = t.transform(e, n)
    for name in _oba_manifest_index():
        if f"_EPSG_{epsg}_{OBA_YEAR_SUFFIX}.json" not in name:
            continue
        mp = RAW / ("oba_" + name.split("/")[-1])
        if not mp.exists():
            mp.write_bytes(requests.get(f"{OBA_BUCKET}/{name}", timeout=120).content)
        m = json.loads(mp.read_text())
        for ts in m["tilesets"]:
            for src in ts["sources"]:
                a = src["affineTransform"]; W_ = src["dimensions"]["width"] * a["scaleX"]; H_ = src["dimensions"]["height"] * -a["scaleY"]
                if a["translateX"] <= x0 and x1 <= a["translateX"] + W_ and a["translateY"] - H_ <= y0 and y1 <= a["translateY"]:
                    return {"url": f"{OBA_BUCKET}/{m['uriPrefix'].split('/geotiffs/')[1] and 'v1/geotiffs/' + m['uriPrefix'].split('/geotiffs/')[1] + src['uris'][0]}",
                            "x0": a["translateX"], "y0": a["translateY"], "res": a["scaleX"], "epsg": epsg}
    return None


def fetch_heights(area_id, bbox):
    out = area_dir(area_id) / "oba_temporal_2023.tif"
    if out.exists():
        return out
    import fsspec, tifffile, zarr, pyproj, rasterio
    from rasterio.transform import Affine
    tile = find_oba_tile(pad_bbox(bbox, 0.0005))
    if tile is None:
        raise RuntimeError("Open Buildings 2.5D Temporal does not cover this area")
    w, s, e, n = pad_bbox(bbox)
    t = pyproj.Transformer.from_crs(4326, tile["epsg"], always_xy=True)
    xa, ya = t.transform(w, s); xb, yb = t.transform(e, n)
    res = tile["res"]
    c0, c1 = int((xa - tile["x0"]) / res), int((xb - tile["x0"]) / res)
    r0, r1 = int((tile["y0"] - yb) / res), int((tile["y0"] - ya) / res)
    fs = fsspec.filesystem("https", block_size=8 * 1024 * 1024)
    with fs.open(tile["url"]) as fh:
        z = zarr.open(tifffile.TiffFile(fh).aszarr(level=0), mode="r")
        arr = np.asarray(z[:, r0:r1, c0:c1]).astype("float32")
    tr = Affine(res, 0, tile["x0"] + c0 * res, 0, -res, tile["y0"] - r0 * res)
    with rasterio.open(out, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=3, dtype="float32",
                       crs=f"EPSG:{tile['epsg']}", transform=tr, compress="deflate", nodata=-99.0) as o:
        o.write(arr)
        o.descriptions = ("building_fractional_count", "building_height", "building_presence")
    return out


# ------------------------------------------------------------------ Meta/WRI canopy height
def quadkey(lat, lon, z):
    x = int((lon + 180) / 360 * 2 ** z); y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    q = ""
    for i in range(z, 0, -1):
        d, m = 0, 1 << (i - 1)
        d += 1 if x & m else 0
        d += 2 if y & m else 0
        q += str(d)
    return q


def fetch_canopy(area_id, bbox):
    out = area_dir(area_id) / "canopy_chm.tif"
    if out.exists():
        return out
    import fsspec, tifffile, zarr, pyproj, rasterio
    from rasterio.transform import Affine
    w, s, e, n = pad_bbox(bbox, 0.0005)
    qks = {quadkey(la, lo, 9) for la in (s, n) for lo in (w, e)}
    if len(qks) != 1:
        raise RuntimeError("bbox straddles two canopy tiles; select a smaller area")
    qk = qks.pop()
    url = f"https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{qk}.tif"
    fs = fsspec.filesystem("https", block_size=8 * 1024 * 1024)
    with fs.open(url) as fh:
        tf = tifffile.TiffFile(fh); p = tf.pages[0]
        tags = {t.name: t.value for t in p.tags.values()}
        sx, sy, _ = tags["ModelPixelScaleTag"]; tp = tags["ModelTiepointTag"]; ox, oy = tp[3], tp[4]
        t = pyproj.Transformer.from_crs(4326, 3857, always_xy=True)
        xa, ya = t.transform(w, s); xb, yb = t.transform(e, n)
        c0, c1 = int((xa - ox) / sx), int((xb - ox) / sx); r0, r1 = int((oy - yb) / sy), int((oy - ya) / sy)
        z = zarr.open(tf.aszarr(level=0), mode="r")
        arr = np.asarray(z[r0:r1, c0:c1])
    with rasterio.open(out, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=str(arr.dtype),
                       crs="EPSG:3857", transform=Affine(sx, 0, ox + c0 * sx, 0, -sy, oy - r0 * sy), compress="deflate") as o:
        o.write(arr, 1)
    return out


# ------------------------------------------------------------------ OSM (Overpass)
OVERPASS = ([os.environ["RSE_OVERPASS_URL"]] if os.environ.get("RSE_OVERPASS_URL") else []) + [
    "https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def overpass(query, retries=3, timeout=110):
    last = None
    for _ in range(retries):
        for h in OVERPASS:
            try:
                r = requests.post(h, data={"data": query}, headers=UA, timeout=timeout)
                if r.status_code == 200:
                    return r.json(), h
                last = f"{h} -> {r.status_code}"
            except Exception as ex:  # noqa
                last = f"{h} -> {type(ex).__name__}"
        time.sleep(4)
    raise RuntimeError("Overpass unavailable: " + str(last))


def fetch_osm(area_id, bbox, timeout=110):
    """Trees / tree rows / woods + building tags (2x2 tiled so slow mirrors still return partial data).
    Records which parts failed; callers degrade gracefully and the QA report states what is missing."""
    out = area_dir(area_id) / "osm.json"
    if out.exists():
        return out
    w, s, e, n = pad_bbox(bbox)
    trees, bld, host, failed = [], [], None, []
    try:
        t, host = overpass(f'[out:json][timeout:90];(node["natural"="tree"]({s},{w},{n},{e});way["natural"="tree_row"]({s},{w},{n},{e});'
                           f'way["natural"="wood"]({s},{w},{n},{e});way["landuse"="forest"]({s},{w},{n},{e}););out geom;', retries=2, timeout=timeout)
        trees = t["elements"]
    except Exception as ex:  # noqa
        failed.append("trees: " + str(ex)[:80])
    mx, my = (w + e) / 2, (s + n) / 2
    seen = set()
    tiles = [] if (failed and not trees) else [(w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)]  # skip when mirrors are down
    for (a, b, c, d) in tiles:
        try:
            r, host = overpass(f'[out:json][timeout:120];way["building"]({b},{a},{d},{c});out geom tags;', retries=2, timeout=timeout)
            for el in r["elements"]:
                if el["id"] not in seen:
                    seen.add(el["id"]); bld.append(el)
        except Exception as ex:  # noqa
            failed.append(f"buildings tile {a:.4f},{b:.4f}: " + str(ex)[:60])
    if not trees and not bld:
        raise RuntimeError("Overpass unavailable: " + "; ".join(failed))
    out.write_text(json.dumps({"mirror": host, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "trees": trees, "buildings": bld,
                               "buildings_unavailable": not bld, "partial_failures": failed}))
    return out


def ingest_area(area_id, bbox, log=print):
    status = {}
    for name, fn in [("overture", fetch_overture), ("open_buildings_v3", fetch_open_buildings_v3), ("heights_25d", fetch_heights),
                     ("canopy", fetch_canopy), ("osm", fetch_osm)]:
        try:
            log(f"ingest {name} ...")
            fn(area_id, bbox, **({"timeout": 40} if name == "osm" else {}))
            status[name] = "ok"
        except Exception as ex:  # noqa
            status[name] = f"unavailable: {type(ex).__name__}: {str(ex)[:140]}"
            log(f"  {name} FAILED -> {status[name]}")
    return status
