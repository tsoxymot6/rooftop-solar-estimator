"""Spatially indexed solar shadow engine.

Geometry (all metres, UTM 43N, flat ground):
    shadow length  L = dh / tan(sun_elevation)      dh = obstacle top - roof surface height
    shadow points opposite the sun: direction = (-sin(az), -cos(az))   (x east, y north)
    shadow area   = footprint swept along that direction by L          (exact for concave footprints)
    roof shaded fraction = shaded roof cells / total roof cells

A roof cell at height z is in direct shadow iff it lies inside the swept polygon of any obstacle
whose top is higher than z. Obstacles are indexed with an STRtree; per sun position only obstacles
close enough to reach the roof (polygon distance <= L) are swept.
"""
from __future__ import annotations
import hashlib
import math
import numpy as np
import shapely
import shapely.ops
from shapely.geometry import Polygon
from shapely.strtree import STRtree

MIN_DH = 0.3  # ignore obstacles less than 30 cm above the roof surface


def shadow_length(dh: float, elevation_deg: float) -> float:
    """L = dh / tan(elevation). Returns inf at/below the horizon, 0 for dh <= 0."""
    if dh <= 0:
        return 0.0
    if elevation_deg <= 0:
        return math.inf
    return dh / math.tan(math.radians(elevation_deg))


def shadow_direction(azimuth_deg: float):
    """Unit vector (east, north) pointing AWAY from the sun (azimuth clockwise from north)."""
    a = math.radians(azimuth_deg)
    return -math.sin(a), -math.cos(a)


def sweep_polygon(poly: Polygon, dx: float, dy: float, length: float, convex_shortcut=True) -> Polygon:
    """Region covered by translating `poly` along (dx,dy)*length. Exact for non-convex footprints."""
    v = np.array([dx * length, dy * length])
    c = np.asarray(poly.exterior.coords)[:-1]
    if convex_shortcut and poly.area >= 0.92 * poly.convex_hull.area:
        return shapely.convex_hull(shapely.multipoints(np.vstack([c, c + v])))
    a, b = c, np.roll(c, -1, axis=0)
    quads = np.stack([a, b, b + v, a + v], axis=1)            # (n,4,2)
    cross = np.abs((b - a)[:, 0] * v[1] - (b - a)[:, 1] * v[0])
    quads = quads[cross > 1e-9]                                 # skip edges parallel to the sweep
    parts = [poly, shapely.affinity.translate(poly, v[0], v[1])]
    if len(quads):
        parts += list(shapely.polygons(quads))
    return shapely.union_all(parts)


class ShadowEngine:
    """Obstacles = building footprints (hard shadows) + tree-canopy patches (partial shadows)."""

    VERSION = "shadow-1"

    def __init__(self, geoms, heights, is_tree, ids, max_shadow_m=150.0, tree_tile_m=6.0):
        """Obstacles are split into convex-ish pieces (trees are tiled on a `tree_tile_m` grid, concave footprints are
        triangulated) so every piece can be swept with a cheap convex hull. A cell is shaded if ANY piece's swept
        region contains it, which equals the exact swept footprint up to the (sub-metre) tile approximation."""
        self.max_shadow_m = float(max_shadow_m)
        pg, ph, pt, pid = [], [], [], []
        for g, h, t, i in zip(geoms, heights, is_tree, ids):
            for piece in _pieces(g, bool(t), tree_tile_m):
                pg.append(piece); ph.append(h); pt.append(bool(t)); pid.append(i)
        self.geoms = np.empty(len(pg), dtype=object); self.geoms[:] = pg
        self.h = np.asarray(ph, dtype=float)
        self.is_tree = np.asarray(pt, dtype=bool)
        self.ids = np.asarray(pid, dtype=object)
        self.index = STRtree(self.geoms)
        self._convex = np.ones(len(pg), dtype=bool)
        self.parent_geoms = {i: g for g, i in zip(geoms, ids)}

    # ------------------------------------------------------------------ candidates
    def candidates(self, target: Polygon, z_roof: float, exclude_id=None):
        """Obstacles that could ever shade a roof at height z_roof (taller & within max range)."""
        idx = self.index.query(target.buffer(self.max_shadow_m))
        if len(idx) == 0:
            return _Cand(np.array([], int), np.array([]), np.array([]))
        dist = shapely.distance(target, self.geoms[idx])
        dh = self.h[idx] - z_roof
        keep = (dh > MIN_DH) & (dist <= self.max_shadow_m)
        if exclude_id is not None:
            keep &= self.ids[idx] != exclude_id
        keep &= ~(shapely.intersects(target, self.geoms[idx]) & ~self.is_tree[idx])  # overlapping duplicates are not neighbours
        return _Cand(idx[keep], dist[keep], dh[keep])

    def signature(self, cand) -> str:
        h = hashlib.sha1()
        h.update(self.VERSION.encode())
        seen = sorted({(str(self.ids[i]), round(float(self.h[i]), 2), int(self.is_tree[i])) for i in cand.idx})
        for k in seen:
            h.update(f"{k[0]}:{k[1]}:{k[2]};".encode())
        return h.hexdigest()[:16]

    # ------------------------------------------------------------------ shading
    def shaded_cells(self, cand, target: Polygon, xs, ys, azimuth_deg, elevation_deg):
        """Returns (building_shaded, tree_shaded) boolean arrays over the roof cells."""
        n = len(xs)
        bld, tree = np.zeros(n, bool), np.zeros(n, bool)
        if elevation_deg <= 0 or len(cand.idx) == 0:
            return bld, tree
        t = math.tan(math.radians(elevation_deg))
        reach = cand.dh / t
        sel = np.nonzero(cand.dist <= reach)[0]
        if sel.size == 0:
            return bld, tree
        dx, dy = shadow_direction(azimuth_deg)
        for j in sel:
            i = cand.idx[j]
            L = float(min(reach[j], self.max_shadow_m + 50.0))
            sw = sweep_polygon(self.geoms[i], dx, dy, L, convex_shortcut=bool(self._convex[i]))
            if not shapely.intersects(sw, target):
                continue
            m = shapely.contains_xy(sw, xs, ys)
            if self.is_tree[i]:
                tree |= m
            else:
                bld |= m
        return bld, tree

    def roof_shade_fractions(self, cand, target, xs, ys, az, el, tree_opacity=0.7):
        b, t = self.shaded_cells(cand, target, xs, ys, az, el)
        n = len(xs)
        geometric = float((b | t).sum()) / n                      # presentation: shaded cells / total cells
        beam_loss = (float(b.sum()) + tree_opacity * float((t & ~b).sum())) / n
        return {"shaded_fraction": geometric, "building_fraction": float(b.sum()) / n,
                "tree_fraction": float((t & ~b).sum()) / n, "beam_loss": beam_loss}

    # ------------------------------------------------------------------ annual profile
    def shade_profile(self, target, z_roof, xs, ys, suns, exclude_id=None, tree_opacity=0.7, cand=None):
        """suns: iterable of (month 1-12, hour 0-23, azimuth, elevation). Returns 12x24 arrays."""
        if cand is None:
            cand = self.candidates(target, z_roof, exclude_id)
        out = {k: np.zeros((12, 24)) for k in ("shaded_fraction", "building_fraction", "tree_fraction", "beam_loss")}
        if len(cand.idx):
            for m, h, az, el in suns:
                f = self.roof_shade_fractions(cand, target, xs, ys, az, el, tree_opacity)
                for k in out:
                    out[k][m - 1, h] = f[k]
        return out, cand

    # ------------------------------------------------------------------ map layers
    def _display_trees(self):
        """Coarser (12 m) canopy tiles used ONLY for the map's ground-shadow layer (speed); calculations use the fine tiles."""
        if getattr(self, "_disp", None) is None:
            g, h = [], []
            for pid, geom in self.parent_geoms.items():
                if str(pid).startswith("tree-"):
                    hh = float(self.h[np.nonzero(self.ids == pid)[0][0]]) if False else None
                    g.append(geom)
            hmap = {}
            for i, pid in enumerate(self.ids):
                if self.is_tree[i] and pid not in hmap:
                    hmap[pid] = float(self.h[i])
            geoms, hs = [], []
            for pid, geom in self.parent_geoms.items():
                if pid in hmap:
                    for pc in _pieces(geom, True, 12.0):
                        geoms.append(pc); hs.append(hmap[pid])
            arr = np.empty(len(geoms), dtype=object); arr[:] = geoms
            self._disp = (arr, np.asarray(hs), STRtree(arr))
        return self._disp

    def ground_shadows(self, azimuth_deg, elevation_deg, bbox_utm=None):
        """Ground-level shadow geometry (buildings, trees) with building footprints removed. Returns (building, tree) lists."""
        if elevation_deg <= 1.0:
            return [], []
        dx, dy = shadow_direction(azimuth_deg)
        tan = math.tan(math.radians(elevation_deg))
        pad = min(self.max_shadow_m, float(self.h.max()) / tan + 2.0)
        q = None if bbox_utm is None else shapely.box(bbox_utm[0] - pad, bbox_utm[1] - pad, bbox_utm[2] + pad, bbox_utm[3] + pad)
        idx = np.arange(len(self.geoms)) if q is None else self.index.query(q)
        idx = idx[~self.is_tree[idx]]
        b, t, foot = [], [], []
        for i in idx:
            L = min(self.h[i] / tan, self.max_shadow_m)
            if L < 0.5:
                continue
            b.append(sweep_polygon(self.geoms[i], dx, dy, L, convex_shortcut=True)); foot.append(self.geoms[i])
        tg, th, tt = self._display_trees()
        ti = np.arange(len(tg)) if q is None else tt.query(q)
        for i in ti:
            L = min(th[i] / tan, self.max_shadow_m)
            if L >= 0.5:
                t.append(sweep_polygon(tg[i], dx, dy, L, convex_shortcut=True))
        if b and foot:
            b = [shapely.union_all(b).difference(shapely.union_all(foot))]
        return b, t


def _pieces(g, tree, tile):
    """Convex-ish decomposition used for fast, accurate sweeps."""
    if g.geom_type == "MultiPolygon":
        out = []
        for part in g.geoms:
            out += _pieces(part, tree, tile)
        return out
    if g.is_empty or g.geom_type != "Polygon":
        return []
    frags = [g]
    minx, miny, maxx, maxy = g.bounds
    if tree and (maxx - minx > tile or maxy - miny > tile):
        xs = np.arange(minx, maxx + tile, tile); ys = np.arange(miny, maxy + tile, tile)
        boxes = np.array([shapely.box(x, y, x + tile, y + tile) for x in xs[:-1] for y in ys[:-1]], dtype=object)
        inter = shapely.intersection(g, boxes)
        frags = []
        for f in inter:
            if f.is_empty:
                continue
            frags += [q for q in (f.geoms if f.geom_type in ("MultiPolygon", "GeometryCollection") else [f]) if q.geom_type == "Polygon" and q.area > 0.5]
    out = []
    for f in frags:
        if f.area >= 0.92 * f.convex_hull.area or len(f.exterior.coords) <= 5:
            out.append(f)
        else:
            tris = shapely.ops.triangulate(f)
            kept = [t for t in tris if f.contains(t.representative_point()) or f.covers(t.representative_point())]
            out += kept if kept else [f]
    return out


class _Cand:
    __slots__ = ("idx", "dist", "dh")

    def __init__(self, idx, dist, dh):
        self.idx, self.dist, self.dh = idx, dist, dh
