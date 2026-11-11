"""Solar geometry via pvlib (NREL SPA). Azimuth is degrees clockwise from north."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pvlib

BENGALURU = (12.979, 77.640, 906.0)  # lat, lon, altitude m (PVGIS reports 906 m for the pilot)


def solar_position(times, lat=BENGALURU[0], lon=BENGALURU[1], altitude=BENGALURU[2]) -> pd.DataFrame:
    """times: tz-aware DatetimeIndex (or convertible). Returns apparent elevation/azimuth/zenith."""
    idx = pd.DatetimeIndex(times)
    if idx.tz is None:
        raise ValueError("times must be timezone-aware")
    sp = pvlib.solarposition.get_solarposition(idx, lat, lon, altitude=altitude)
    return sp[["apparent_elevation", "elevation", "azimuth", "apparent_zenith", "zenith"]]


def representative_days(year=2023, tz="Asia/Kolkata"):
    """15th of each month - used for the monthly shade profile and interactive seasonal views."""
    return [pd.Timestamp(year=year, month=m, day=15, tz=tz) for m in range(1, 13)]


def sun_track(day: pd.Timestamp, lat=BENGALURU[0], lon=BENGALURU[1], step_min=30) -> pd.DataFrame:
    idx = pd.date_range(day.normalize(), day.normalize() + pd.Timedelta(hours=24), freq=f"{step_min}min", inclusive="left")
    sp = solar_position(idx, lat, lon)
    sp.index = idx
    return sp
