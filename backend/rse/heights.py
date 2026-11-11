"""Building-height hierarchy with provenance, plus the footprint-based fallback model.

Order (presentation + brief):
 1 field-measured height
 2 mapped height attribute (OSM / Overture `height`), then Open Buildings 2.5D Temporal raster
 3 levels x 3 m
 4 footprint-based model - ONLY when >= 10 real measured buildings exist (fit/test split);
   otherwise a transparent neighbourhood fallback flagged 'unverified' with an uncertainty range.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M_PER_FLOOR = 3.0
MIN_MEASURED_FOR_MODEL = 10
RASTER_MIN_COVERAGE = 0.5
TINY_FOOTPRINT_M2 = 10.0


def height_from_floors(floors) -> float:
    if floors is None or (isinstance(floors, float) and np.isnan(floors)):
        raise ValueError("floors required")
    if floors <= 0:
        raise ValueError("floors must be positive")
    return float(floors) * M_PER_FLOOR


class FootprintHeightModel:
    """height = a + b * ln(footprint area). Trained/tested only on REAL measured buildings."""

    def __init__(self):
        self.calibrated = False
        self.coef = None
        self.report = {"calibrated": False, "reason": "no field measurements supplied"}

    @staticmethod
    def _split(n, seed=7):
        rng = np.random.default_rng(seed)
        idx = rng.permutation(n)
        n_test = max(3, int(round(n * 0.3)))
        return idx[n_test:], idx[:n_test]

    def fit(self, areas, heights):
        a, h = np.asarray(areas, float), np.asarray(heights, float)
        ok = (a > 0) & (h > 0)
        a, h = a[ok], h[ok]
        if len(a) < MIN_MEASURED_FOR_MODEL:
            self.calibrated = False
            self.report = {"calibrated": False, "n_measured": int(len(a)),
                           "reason": f"need >= {MIN_MEASURED_FOR_MODEL} measured buildings, have {len(a)}"}
            return self
        tr, te = self._split(len(a))
        x = np.log(a)
        b, c = np.polyfit(x[tr], h[tr], 1)
        pred = c + b * x[te]
        err = pred - h[te]
        self.coef = (float(c), float(b))
        self.calibrated = True
        self.report = {"calibrated": True, "n_measured": int(len(a)), "n_train": int(len(tr)), "n_test": int(len(te)),
                       "intercept_m": float(c), "slope_m_per_ln_m2": float(b),
                       "test_mae_m": float(np.abs(err).mean()), "test_rmse_m": float(np.sqrt((err ** 2).mean())),
                       "test_bias_m": float(err.mean()),
                       "note": "Very small sample: treat error estimates as indicative, not as a guarantee."}
        return self

    def predict(self, area_m2):
        if not self.calibrated:
            raise RuntimeError("model is not calibrated")
        c, b = self.coef
        return float(max(c + b * np.log(max(area_m2, 1.0)), M_PER_FLOOR))


def assign_heights(df: pd.DataFrame, model: FootprintHeightModel | None = None) -> pd.DataFrame:
    """df columns: area_m2, height (mapped), num_floors, raster_h, raster_cov, measured_h (optional).
    Adds: height_m, height_source, height_low_m, height_high_m, height_flags (list), height_status ('estimated'|'unverified'|'measured')."""
    model = model or FootprintHeightModel()
    n = len(df)
    H = np.full(n, np.nan); SRC = np.array([""] * n, dtype=object)
    LO = np.full(n, np.nan); HI = np.full(n, np.nan)
    FLAGS = [[] for _ in range(n)]
    g = lambda c: df[c].to_numpy(dtype=float) if c in df else np.full(n, np.nan)
    measured, mapped, floors, rh, rcov, area = g("measured_h"), g("height"), g("num_floors"), g("raster_h"), g("raster_cov"), g("area_m2")

    for i in range(n):
        cands = {}
        if not np.isnan(mapped[i]) and mapped[i] > 0:
            cands["mapped"] = mapped[i]
        if not np.isnan(rh[i]) and rh[i] > 0 and (np.isnan(rcov[i]) or rcov[i] >= RASTER_MIN_COVERAGE):
            cands["raster"] = rh[i]
        if not np.isnan(floors[i]) and floors[i] > 0:
            cands["floors"] = floors[i] * M_PER_FLOOR
        # conflict check among available independent sources
        if len(cands) >= 2:
            v = np.array(list(cands.values()))
            if v.max() - v.min() > max(3.0, 0.4 * v.max()):
                FLAGS[i].append("height_sources_conflict")
        if not np.isnan(measured[i]) and measured[i] > 0:
            H[i], SRC[i], LO[i], HI[i] = measured[i], "field_measured", measured[i] - 0.5, measured[i] + 0.5
        elif "mapped" in cands:
            H[i], SRC[i] = cands["mapped"], "mapped_height_attribute"; LO[i], HI[i] = H[i] - 1.5, H[i] + 1.5
        elif "raster" in cands:
            H[i], SRC[i] = cands["raster"], "open_buildings_2.5d_temporal_2023"; LO[i], HI[i] = H[i] * 0.7, H[i] * 1.3
        elif "floors" in cands:
            H[i], SRC[i] = cands["floors"], "levels_x_3m"; LO[i], HI[i] = H[i] - M_PER_FLOOR, H[i] + M_PER_FLOOR
        elif model.calibrated:
            H[i], SRC[i] = model.predict(area[i]), "footprint_model_calibrated"
            mae = model.report["test_mae_m"]; LO[i], HI[i] = H[i] - 2 * mae, H[i] + 2 * mae
        else:
            SRC[i] = "neighbourhood_fallback"
        if area[i] < TINY_FOOTPRINT_M2:
            FLAGS[i].append("tiny_footprint")
    df = df.copy()
    # neighbourhood fallback: median/IQR of known heights in the same footprint-size bucket (flagged unverified)
    known = ~np.isnan(H)
    buckets = pd.cut(area, [0, 50, 150, 400, np.inf], labels=False)
    for b in np.unique(buckets):
        sel = (buckets == b) & (SRC == "neighbourhood_fallback")
        ref = (buckets == b) & known
        if sel.any():
            vals = H[ref] if ref.sum() >= 5 else H[known]
            if len(vals):
                H[sel] = np.median(vals); LO[sel] = np.percentile(vals, 25); HI[sel] = np.percentile(vals, 75)
            else:
                H[sel], LO[sel], HI[sel] = 6.0, 3.0, 12.0
            for i in np.nonzero(sel)[0]:
                FLAGS[i].append("height_missing_fallback")
    status = []
    for i in range(n):
        if SRC[i] == "field_measured":
            status.append("measured")
        elif SRC[i] == "neighbourhood_fallback" or FLAGS[i]:
            status.append("unverified")
        else:
            status.append("estimated")
    df["height_m"], df["height_source"], df["height_low_m"], df["height_high_m"] = H, SRC, LO, HI
    df["height_flags"], df["height_status"] = FLAGS, status
    return df
