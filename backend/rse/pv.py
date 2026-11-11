"""Irradiance handling and PV energy model (pvlib).

Primary resource: NASA POWER hourly (GHI, DNI, DHI, T2M, WS10M). Spatial resolution ~0.5 x 0.625 deg:
this is a regional resource value, NOT a building-level measurement. A simplified typical year is
assembled from 10 years: for each calendar month, the year whose mean GHI is closest to the 10-year
mean of that month. This is a TMY-style construction, not the ISO 15927-4 / Sandia TMY procedure.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pvlib
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS
from .config import PVAssumptions
from .sun import solar_position, BENGALURU

LAT, LON, ALT = BENGALURU


def load_nasa_hourly(path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"allsky_sfc_sw_dwn": "ghi", "allsky_sfc_sw_dni": "dni", "allsky_sfc_sw_diff": "dhi",
                            "t2m": "temp_air", "ws10m": "wind_speed"})
    df.index = pd.DatetimeIndex(df.index).tz_localize("UTC")
    return df[["ghi", "dni", "dhi", "temp_air", "wind_speed"]]


def detect_interval_offset_minutes(df: pd.DataFrame, lat=LAT, lon=LON) -> int:
    """Pick the timestamp convention (interval start vs centred) whose solar geometry best explains GHI."""
    best, best_c = 0, -2
    sample = df.iloc[: 24 * 365]
    for off in (0, 30, 60):
        sp = solar_position(sample.index + pd.Timedelta(minutes=off), lat, lon)
        cz = np.cos(np.radians(sp["apparent_zenith"].clip(upper=90))).values
        c = np.corrcoef(cz, sample["ghi"].values)[0, 1]
        if c > best_c:
            best, best_c = off, c
    return best


def build_typical_year(df: pd.DataFrame, offset_min=30):
    """Returns (typical-year frame [8760 rows, UTC interval-start index in 2023], metadata)."""
    d = df.copy()
    d["ist"] = d.index.tz_convert("Asia/Kolkata") + pd.Timedelta(minutes=offset_min)
    d["year"], d["month"] = d["ist"].dt.year, d["ist"].dt.month
    cnt = d.groupby(["year", "month"])["ghi"].count().unstack()
    mm = d.groupby(["year", "month"])["ghi"].mean().unstack()
    mm = mm.where(cnt >= 0.95 * cnt.max())          # ignore partial months created by the UTC->IST shift
    ltm = mm.mean(axis=0)
    chosen = {m: int((mm[m] - ltm[m]).abs().idxmin()) for m in range(1, 13)}
    parts = []
    for m, y in chosen.items():
        sub = d[(d.year == y) & (d.month == m)].drop(columns=["ist", "year", "month"])
        sub = sub[~((sub.index.month == 2) & (sub.index.day == 29))]
        sub.index = sub.index.map(lambda t: t.replace(year=2023))
        parts.append(sub)
    ty = pd.concat(parts).sort_index()
    ty = ty[~ty.index.duplicated()]
    full = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h", tz="UTC")
    ty = ty.reindex(full).interpolate(limit=3).fillna(0.0)
    meta = {"selected_year_per_month": chosen, "method": "per-month year closest to 10-yr mean GHI (simplified TMY-style)",
            "source_years": [int(df.index.year.min()), int(df.index.year.max())], "interval_offset_min": offset_min,
            "annual_ghi_kwh_m2": float(ty["ghi"].sum() / 1000.0), "annual_dni_kwh_m2": float(ty["dni"].sum() / 1000.0),
            "annual_dhi_kwh_m2": float(ty["dhi"].sum() / 1000.0)}
    return ty, meta


class PVModel:
    """Hourly typical-year POA irradiance on the array plane + temperature-corrected PV model, per kWp."""

    def __init__(self, typical_year: pd.DataFrame, ap: PVAssumptions | None = None, offset_min=30, lat=LAT, lon=LON, alt=ALT,
                 harmonize_components=True):
        self.ap = ap or PVAssumptions()
        ty = typical_year
        self.times_mid = ty.index + pd.Timedelta(minutes=offset_min)         # UTC mid-interval
        self.utc_hour = np.asarray(ty.index.hour)                            # interval-start UTC hour (0-23)
        self.month = np.asarray((self.times_mid.tz_convert("Asia/Kolkata")).month)
        sp = solar_position(self.times_mid, lat, lon, alt)
        self.sun = sp
        ghi, dni, dhi = ty["ghi"].values.copy(), ty["dni"].values.copy(), ty["dhi"].values.copy()
        cz = np.cos(np.radians(sp["apparent_zenith"].values))
        up = sp["apparent_elevation"].values > 0
        ghi, dni, dhi = [np.where(up, np.clip(x, 0, None), 0.0) for x in (ghi, dni, dhi)]
        self.closure_factor_mean = 1.0
        if harmonize_components:
            # NASA POWER's DNI*cos(Z)+DHI does not close to its own GHI (typically 4-20 % low). GHI is anchored and
            # DNI/DHI are rescaled hourly by k = GHI/(DNI*cosZ+DHI), bounded to [0.8, 1.5]. Documented QC step.
            recon = dni * cz + dhi
            ok = (sp["apparent_elevation"].values > 5) & (recon > 20)
            k = np.where(ok, np.clip(ghi / np.where(recon > 0, recon, 1), 0.8, 1.5), 1.0)
            dni, dhi = dni * k, dhi * k
            self.closure_factor_mean = float(ghi[ok].sum() / (dni * cz + dhi)[ok].sum()) if ok.any() else 1.0
            self.closure_applied = float(np.average(k[ok])) if ok.any() else 1.0
        extra = pvlib.irradiance.get_extra_radiation(self.times_mid)
        am = pvlib.atmosphere.get_relative_airmass(sp["apparent_zenith"])
        poa = pvlib.irradiance.get_total_irradiance(
            self.ap.tilt_deg, self.ap.azimuth_deg, sp["apparent_zenith"], sp["azimuth"], dni, ghi, dhi,
            dni_extra=extra, airmass=am, albedo=self.ap.albedo, model="haydavies")
        self.poa_direct = np.nan_to_num(np.asarray(poa["poa_direct"]))
        self.poa_diffuse = np.nan_to_num(np.asarray(poa["poa_sky_diffuse"]))
        self.poa_ground = np.nan_to_num(np.asarray(poa["poa_ground_diffuse"]))
        self.aoi = np.asarray(pvlib.irradiance.aoi(self.ap.tilt_deg, self.ap.azimuth_deg, sp["apparent_zenith"], sp["azimuth"]))
        self.temp_air, self.wind = ty["temp_air"].values, ty["wind_speed"].values
        self.ghi, self.dni, self.dhi = ghi, dni, dhi
        self._tp = TEMPERATURE_MODEL_PARAMETERS["sapm"][self.ap.temperature_model]
        self.system_loss = pvlib.pvsystem.pvwatts_losses(
            soiling=self.ap.soiling, shading=0.0, snow=0.0, mismatch=self.ap.mismatch, wiring=self.ap.wiring,
            connections=self.ap.connections, lid=self.ap.lid, nameplate_rating=self.ap.nameplate_rating,
            age=0.0, availability=self.ap.availability) / 100.0

    # ------------------------------------------------------------------
    def hourly_kwh_per_kwp(self, beam_loss_hourly=None, system_loss=None) -> np.ndarray:
        """AC kWh per kWp for each typical-year hour. beam_loss_hourly in [0,1] reduces ONLY the direct beam;
        diffuse and ground-reflected irradiance are retained (they do not vanish in a direct-beam shadow)."""
        bl = np.zeros_like(self.poa_direct) if beam_loss_hourly is None else np.clip(beam_loss_hourly, 0, 1)
        iam = np.clip(pvlib.iam.ashrae(self.aoi, b=self.ap.iam_b), 0, 1)
        direct = self.poa_direct * (1.0 - bl) * np.where(self.aoi < 90, iam, 0.0)
        poa = direct + self.poa_diffuse + self.poa_ground
        tc = pvlib.temperature.sapm_cell(poa, self.temp_air, self.wind, **self._tp)
        loss = self.system_loss if system_loss is None else system_loss
        pdc = pvlib.pvsystem.pvwatts_dc(poa, tc, 1.0, self.ap.gamma_pdc) * (1.0 - loss)
        pdc0_inv = (1.0 / self.ap.dc_ac_ratio) / self.ap.inverter_efficiency
        pac = pvlib.inverter.pvwatts(pdc, pdc0_inv, eta_inv_nom=self.ap.inverter_efficiency)
        return np.nan_to_num(np.clip(pac, 0, None))

    def beam_loss_series(self, month_hour_loss: np.ndarray) -> np.ndarray:
        """Expand a 12x24 (month x UTC interval-start hour) beam-loss table to the 8760 hourly series."""
        return month_hour_loss[self.month - 1, self.utc_hour]

    def annual(self, beam_loss_hourly=None, system_loss=None) -> dict:
        e = self.hourly_kwh_per_kwp(beam_loss_hourly, system_loss)
        monthly = np.array([e[self.month == m].sum() for m in range(1, 13)])
        return {"kwh_per_kwp": float(e.sum()), "monthly_kwh_per_kwp": monthly.tolist()}

    def poa_annual_kwh_m2(self) -> float:
        return float((self.poa_direct + self.poa_diffuse + self.poa_ground).sum() / 1000.0)

    def sun_table(self, min_elev=3.0):
        """(month, utc_hour, azimuth, elevation) for the 15th of each month at each mid-interval hour."""
        rows = []
        for m in range(1, 13):
            for h in range(24):
                t = pd.Timestamp(year=2023, month=m, day=15, hour=h, tz="UTC") + pd.Timedelta(minutes=30)
                rows.append((m, h, t))
        idx = pd.DatetimeIndex([r[2] for r in rows])
        sp = solar_position(idx, LAT, LON, ALT)
        out = []
        for (m, h, _), az, el in zip(rows, sp["azimuth"].values, sp["apparent_elevation"].values):
            if el >= min_elev:
                out.append((m, h, float(az), float(el)))
        return out
