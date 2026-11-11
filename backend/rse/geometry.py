"""Projection, area and roof-grid helpers (all metric work is done in UTM 43N, EPSG:32643)."""
from __future__ import annotations
import math
import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon, Point
from pyproj import Transformer, Geod

UTM_EPSG = 32643
_to_utm = Transformer.from_crs(4326, UTM_EPSG, always_xy=True)
_to_wgs = Transformer.from_crs(UTM_EPSG, 4326, always_xy=True)
_GEOD = Geod(ellps="WGS84")


def _tx(tr):
    return lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1]))


def to_utm(geom):
    return shapely.transform(geom, _tx(_to_utm))


def to_wgs(geom):
    return shapely.transform(geom, _tx(_to_wgs))


def geodesic_area_m2(geom_wgs84) -> float:
    """Ellipsoidal area in m2 of a lon/lat polygon (independent of any map projection)."""
    if geom_wgs84 is None or geom_wgs84.is_empty:
        raise ValueError("empty geometry")
    if isinstance(geom_wgs84, MultiPolygon):
        return float(sum(geodesic_area_m2(g) for g in geom_wgs84.geoms))
    if not isinstance(geom_wgs84, Polygon):
        raise ValueError("polygon required")
    area, _ = _GEOD.geometry_area_perimeter(geom_wgs84)
    return abs(float(area))


def bbox_area_km2(bbox) -> float:
    w, s, e, n = bbox
    return geodesic_area_m2(shapely.box(w, s, e, n)) / 1e6


def roof_cells(poly_utm: Polygon, cell=1.0, setback=0.5, max_cells=400):
    """Regular grid of cell centres inside a roof polygon (equal-area cells).

    The polygon is shrunk by `setback` (parapet / fire lane) when that leaves area; the
    grid spacing is coarsened for very large roofs so no roof exceeds `max_cells`.
    Returns (xs, ys, step_m). Always returns at least one cell for a valid polygon.
    """
    if poly_utm.is_empty or poly_utm.area <= 0:
        raise ValueError("invalid roof polygon")
    inner = poly_utm.buffer(-setback) if poly_utm.area > 4 * setback * setback * 4 else poly_utm
    if inner.is_empty:
        inner = poly_utm
    step = max(cell, math.sqrt(inner.area / max_cells))
    minx, miny, maxx, maxy = inner.bounds
    gx = np.arange(minx + step / 2, maxx, step)
    gy = np.arange(miny + step / 2, maxy, step)
    if gx.size == 0 or gy.size == 0:
        p = inner.representative_point()
        return np.array([p.x]), np.array([p.y]), step
    X, Y = np.meshgrid(gx, gy)
    xs, ys = X.ravel(), Y.ravel()
    m = shapely.contains_xy(inner, xs, ys)
    if not m.any():
        p = inner.representative_point()
        return np.array([p.x]), np.array([p.y]), step
    return xs[m], ys[m], step
