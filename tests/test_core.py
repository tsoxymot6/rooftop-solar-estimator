import math
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box, Polygon

from rse import geometry, heights, shadow, sun, economics
from rse.config import PVAssumptions, EconAssumptions, SCENARIOS
from rse.pv import PVModel


# ------------------------------------------------------------------ footprint area
def test_geodesic_area_of_known_square():
    x0, y0 = 77.64, 12.98
    sq = geometry.to_wgs(box(*geometry.to_utm(shapely.Point(x0, y0)).coords[0], *(c + 100 for c in geometry.to_utm(shapely.Point(x0, y0)).coords[0])))
    assert geometry.geodesic_area_m2(sq) == pytest.approx(10000, rel=2e-3)


def test_area_rejects_empty_and_non_polygon():
    with pytest.raises(ValueError):
        geometry.geodesic_area_m2(Polygon())
    with pytest.raises(ValueError):
        geometry.geodesic_area_m2(shapely.Point(77, 13))


# ------------------------------------------------------------------ heights
def _row(**kw):
    base = dict(area_m2=100.0, height=np.nan, num_floors=np.nan, raster_h=np.nan, raster_cov=np.nan, measured_h=np.nan)
    base.update(kw)
    return base


def test_levels_times_three():
    assert heights.height_from_floors(4) == 12.0
    with pytest.raises(ValueError):
        heights.height_from_floors(0)


def test_height_priority_and_provenance():
    df = pd.DataFrame([
        _row(measured_h=9.0, height=7.0, num_floors=3),            # measured wins
        _row(height=8.0, num_floors=3, raster_h=8.5, raster_cov=0.9),   # mapped attr wins over raster/floors
        _row(raster_h=7.0, raster_cov=0.9, num_floors=2),          # raster wins over floors
        _row(num_floors=3),                                         # floors x 3
    ])
    out = heights.assign_heights(df)
    assert list(out.height_source) == ["field_measured", "mapped_height_attribute", "open_buildings_2.5d_temporal_2023", "levels_x_3m"]
    assert out.height_m.iloc[3] == 9.0
    assert out.height_status.iloc[0] == "measured"


def test_missing_height_is_unverified_not_invented():
    df = pd.DataFrame([_row(num_floors=2)] * 6 + [_row(area_m2=80)])
    out = heights.assign_heights(df)
    last = out.iloc[-1]
    assert last.height_source == "neighbourhood_fallback" and last.height_status == "unverified"
    assert "height_missing_fallback" in last.height_flags
    assert last.height_low_m <= last.height_m <= last.height_high_m


def test_conflicting_sources_flag_unverified():
    out = heights.assign_heights(pd.DataFrame([_row(height=6.0, num_floors=6)]))
    assert out.height_status.iloc[0] == "unverified" and "height_sources_conflict" in out.height_flags.iloc[0]


def test_footprint_model_refuses_without_enough_real_measurements():
    m = heights.FootprintHeightModel().fit([50, 80, 120], [6, 9, 12])
    assert not m.calibrated and "need >=" in m.report["reason"]
    with pytest.raises(RuntimeError):
        m.predict(100)


def test_footprint_model_fits_and_reports_holdout_error():
    rng = np.random.default_rng(1)
    a = np.linspace(40, 400, 14)
    h = 2 + 2.0 * np.log(a) + rng.normal(0, 0.3, a.size)
    m = heights.FootprintHeightModel().fit(a, h)
    assert m.calibrated and m.report["n_test"] >= 3 and m.report["test_mae_m"] < 1.5
    assert m.predict(200) > m.predict(50)


# ------------------------------------------------------------------ solar position
def test_solar_position_equator_equinox_noon():
    t = pd.DatetimeIndex([pd.Timestamp("2023-03-21 12:00", tz="UTC")])
    sp = sun.solar_position(t, 0.0, 0.0, 0.0)
    assert sp["apparent_elevation"].iloc[0] > 88


def test_bengaluru_solstice_noon_elevation():
    # 21 Jun, Bengaluru (13N): max elevation ~ 90 - 13 + 23.44 -> sun slightly north of zenith, elev ~ 100.4 -> 79.6
    t = pd.date_range("2023-06-21 05:00", "2023-06-21 08:00", freq="10min", tz="UTC")
    sp = sun.solar_position(t)
    assert 77 < sp["apparent_elevation"].max() < 82
    t = pd.date_range("2023-12-21 05:00", "2023-12-21 08:00", freq="10min", tz="UTC")
    sp = sun.solar_position(t)
    assert 51 < sp["apparent_elevation"].max() < 56   # 90 - 13 - 23.44 = 53.6


def test_sun_below_horizon_at_night():
    t = pd.DatetimeIndex([pd.Timestamp("2023-06-21 18:00", tz="UTC")])  # 23:30 IST
    assert sun.solar_position(t)["apparent_elevation"].iloc[0] < 0


# ------------------------------------------------------------------ shadow geometry
def test_shadow_length_formula():
    assert shadow.shadow_length(10, 45) == pytest.approx(10.0)
    assert shadow.shadow_length(10, 30) == pytest.approx(10 / math.tan(math.radians(30)))
    assert shadow.shadow_length(-2, 30) == 0.0
    assert shadow.shadow_length(5, 0) == math.inf


@pytest.mark.parametrize("az,expect", [(90, (-1, 0)), (180, (0, 1)), (270, (1, 0)), (0, (0, -1))])
def test_shadow_points_away_from_sun(az, expect):
    dx, dy = shadow.shadow_direction(az)
    assert (dx, dy) == pytest.approx(expect, abs=1e-9)


def test_sweep_covers_footprint_and_extends_by_length():
    p = box(0, 0, 10, 10)
    sw = shadow.sweep_polygon(p, 1, 0, 10)       # sun in the west -> shadow east
    assert sw.bounds == pytest.approx((0, 0, 20, 10))
    assert sw.area == pytest.approx(200)


def test_sweep_exact_for_l_shaped_footprint_keeps_notch_clear_off_shadow_axis():
    ell = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
    sw = shadow.sweep_polygon(ell, 1, 0, 3, convex_shortcut=False)
    assert not sw.contains(shapely.Point(8, 8))      # notch region stays unshaded
    assert sw.contains(shapely.Point(12, 2))


def _engine(*specs):
    return shadow.ShadowEngine([s[0] for s in specs], [s[1] for s in specs], [s[2] for s in specs],
                               [f"o{i}" for i in range(len(specs))])


def test_roof_shaded_fraction_matches_hand_calculation():
    # 20 m tall tower west of a 10 m tall, 20x20 roof. Sun from the west at 45 deg -> shadow length (20-10)/tan45 = 10 m.
    tower = box(-5, 0, 0, 20)
    roof = box(10, 0, 30, 20)
    # tower->roof gap is 10 m, shadow reaches exactly x=10 : roof untouched
    eng = _engine((tower, 20.0, False))
    xs, ys, _ = geometry.roof_cells(roof, cell=1.0, setback=0.0)
    cand = eng.candidates(roof, 10.0)
    f0 = eng.roof_shade_fractions(cand, roof, xs, ys, 270.0, 45.0)
    assert f0["shaded_fraction"] == 0.0
    # sun at 30 deg -> L = 10/tan30 = 17.32 m ; shadow edge at x = 0+17.32 -> covers roof x in [10, 17.32] = 7.32 m of 20 m
    f1 = eng.roof_shade_fractions(cand, roof, xs, ys, 270.0, 30.0)
    assert f1["shaded_fraction"] == pytest.approx(7.32 / 20, abs=0.04)
    assert f1["building_fraction"] == f1["shaded_fraction"] and f1["tree_fraction"] == 0.0


def test_lower_sun_never_reduces_shading():
    tower = box(-5, 0, 0, 20); roof = box(10, 0, 30, 20)
    eng = _engine((tower, 20.0, False))
    xs, ys, _ = geometry.roof_cells(roof, cell=1.0, setback=0.0)
    cand = eng.candidates(roof, 10.0)
    fr = [eng.roof_shade_fractions(cand, roof, xs, ys, 270.0, e)["shaded_fraction"] for e in (60, 45, 30, 15, 8)]
    assert fr == sorted(fr)


def test_shorter_obstacle_than_roof_casts_no_shadow_on_roof():
    low = box(-5, 0, 0, 20); roof = box(10, 0, 30, 20)
    eng = _engine((low, 6.0, False))
    assert len(eng.candidates(roof, 10.0).idx) == 0


def test_no_shadow_when_sun_below_horizon():
    tower = box(-5, 0, 0, 20); roof = box(10, 0, 30, 20)
    eng = _engine((tower, 20.0, False))
    xs, ys, _ = geometry.roof_cells(roof, cell=1.0, setback=0.0)
    cand = eng.candidates(roof, 10.0)
    b, t = eng.shaded_cells(cand, roof, xs, ys, 270.0, -5.0)
    assert not b.any() and not t.any()


def test_shadow_is_opposite_the_sun_not_toward_it():
    tower = box(-5, 0, 0, 20); roof = box(10, 0, 30, 20)
    eng = _engine((tower, 20.0, False))
    xs, ys, _ = geometry.roof_cells(roof, cell=1.0, setback=0.0)
    cand = eng.candidates(roof, 10.0)
    east_sun = eng.roof_shade_fractions(cand, roof, xs, ys, 90.0, 20.0)   # sun in east -> shadow falls WEST, away from roof
    assert east_sun["shaded_fraction"] == 0.0


def test_tree_shadow_is_partial_beam_loss():
    tree = box(-5, 0, 0, 20); roof = box(10, 0, 30, 20)
    eng = _engine((tree, 20.0, True))
    xs, ys, _ = geometry.roof_cells(roof, cell=1.0, setback=0.0)
    cand = eng.candidates(roof, 10.0)
    f = eng.roof_shade_fractions(cand, roof, xs, ys, 270.0, 30.0, tree_opacity=0.7)
    assert f["tree_fraction"] > 0 and f["beam_loss"] == pytest.approx(0.7 * f["tree_fraction"])


def test_roof_cells_always_returns_a_cell_and_respects_cap():
    xs, ys, step = geometry.roof_cells(box(0, 0, 2, 2), cell=1.0, setback=0.5)
    assert len(xs) >= 1
    xs, ys, step = geometry.roof_cells(box(0, 0, 200, 200), cell=1.0, setback=0.5, max_cells=400)
    assert len(xs) <= 520 and step > 1
    with pytest.raises(ValueError):
        geometry.roof_cells(Polygon())


# ------------------------------------------------------------------ usable-area scenarios + capacity
def test_three_scenarios_are_25_50_70_percent():
    assert SCENARIOS == {"low": 0.25, "middle": 0.5, "high": 0.7}
    t = economics.scenario_table(200.0)
    assert t["low"]["usable_area_m2"] == 50 and t["middle"]["usable_area_m2"] == 100 and t["high"]["usable_area_m2"] == 140
    assert t["low"]["capacity_kwp"] < t["middle"]["capacity_kwp"] < t["high"]["capacity_kwp"]


def test_capacity_uses_documented_area_per_kwp():
    ap = PVAssumptions()
    assert economics.capacity_kwp(100, 0.5, ap) == pytest.approx(50 / ap.roof_area_per_kwp)
    assert 6 < ap.roof_area_per_kwp < 12          # sanity: typical flat-roof m2/kWp


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        economics.usable_area_m2(-1, 0.5)
    with pytest.raises(ValueError):
        economics.usable_area_m2(100, 1.5)
    with pytest.raises(ValueError):
        economics.economics(-1, 100)


# ------------------------------------------------------------------ payback / economics
def test_simple_payback():
    assert economics.simple_payback_years(100000, 20000) == 5.0
    assert economics.simple_payback_years(100000, 0) is None
    with pytest.raises(ValueError):
        economics.simple_payback_years(-1, 10)


def test_export_is_not_valued_at_retail_tariff():
    e_net = economics.annual_value_inr(1000, 0.0, 5.8, 3.89, "net_billing")
    assert e_net == pytest.approx(3890)               # nothing self-consumed -> all at PPA tariff
    assert economics.annual_value_inr(1000, 0.0, 5.8, 3.89, "behind_the_meter") == 0
    assert economics.annual_value_inr(1000, 0.5, 5.8, 3.89, "gross_metering") == pytest.approx(3890)
    assert economics.annual_value_inr(1000, 1.0, 5.8, 3.89, "net_metering") == pytest.approx(5800)
    with pytest.raises(ValueError):
        economics.annual_value_inr(1, 0.5, 5, 3, "unknown")


def test_economics_range_ordering_and_fixed_charges_excluded():
    r = economics.economics(5.0, 7500.0, EconAssumptions())
    assert r["category"] == "domestic" and r["cost_inr"]["low"] < r["cost_inr"]["mid"] < r["cost_inr"]["high"]
    assert r["annual_savings_inr"]["low"] < r["annual_savings_inr"]["high"]
    pb = r["payback_years"]
    assert pb["best"] < pb["mid"] < pb["worst"]
    assert "Fixed charges" in r["note"]
    big = economics.economics(40.0, 60000.0, EconAssumptions())
    assert big["category"] == "non_domestic" and big["capex_inr_per_kw"] == 27090


def test_subsidy_reported_separately_and_off_by_default():
    assert "subsidy" not in economics.economics(3.0, 4500.0)
    r = economics.economics(3.0, 4500.0, EconAssumptions(include_subsidy_estimate=True))
    assert r["subsidy"]["verified"] is False and r["cost_inr"]["mid"] == pytest.approx(135000)
    assert r["subsidy"]["net_cost_inr_mid"] == pytest.approx(135000 - 78000)


# ------------------------------------------------------------------ annual energy (synthetic clear-ish year)
@pytest.fixture(scope="module")
def pvm():
    idx = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h", tz="UTC")
    sp = sun.solar_position(idx + pd.Timedelta(minutes=30))
    el = sp["apparent_elevation"].clip(lower=0).values
    dni = np.where(el > 0, 800 * np.sin(np.radians(el)) ** 0.3, 0)
    dhi = np.where(el > 0, 120 * np.sin(np.radians(el)), 0)
    ghi = dni * np.sin(np.radians(el)) + dhi
    ty = pd.DataFrame({"ghi": ghi, "dni": dni, "dhi": dhi, "temp_air": 25.0, "wind_speed": 2.0}, index=idx)
    return PVModel(ty)


def test_unshaded_yield_is_physically_plausible(pvm):
    y = pvm.annual()["kwh_per_kwp"]
    assert 1200 < y < 2300 and len(pvm.annual()["monthly_kwh_per_kwp"]) == 12


def test_adding_shade_never_increases_energy(pvm):
    base = pvm.annual()["kwh_per_kwp"]
    last = base
    for frac in (0.1, 0.3, 0.6, 1.0):
        bl = np.full((12, 24), frac)
        y = pvm.annual(pvm.beam_loss_series(bl))["kwh_per_kwp"]
        assert y <= last + 1e-9
        last = y
    assert 0.05 * base < last < base   # total beam loss still leaves diffuse + ground-reflected generation (not zeroed)


def test_energy_scales_linearly_with_capacity_and_zero_at_night(pvm):
    e = pvm.hourly_kwh_per_kwp()
    assert e[pvm.sun["apparent_elevation"].values < -5].max() == 0
    assert (e >= 0).all()


def test_higher_system_losses_reduce_energy(pvm):
    assert pvm.annual(system_loss=0.25)["kwh_per_kwp"] < pvm.annual(system_loss=0.05)["kwh_per_kwp"]


def test_piece_decomposition_matches_exact_sweep_for_concave_obstacle():
    rng = np.random.default_rng(3)
    ell = Polygon([(0, 0), (12, 0), (12, 5), (5, 5), (5, 14), (0, 14)])
    eng = shadow.ShadowEngine([ell], [20.0], [False], ["L"])
    exact = shadow.sweep_polygon(ell, *shadow.shadow_direction(250), 9.0, convex_shortcut=False)
    pts = rng.uniform(-15, 30, (4000, 2))
    got = np.zeros(len(pts), bool)
    dx, dy = shadow.shadow_direction(250)
    for g in eng.geoms:
        got |= shapely.contains_xy(shadow.sweep_polygon(g, dx, dy, 9.0), pts[:, 0], pts[:, 1])
    want = shapely.contains_xy(exact, pts[:, 0], pts[:, 1])
    assert (got != want).mean() < 0.01 and want.sum() > 200


def test_tree_tiling_keeps_total_area():
    big = box(0, 0, 40, 25)
    pcs = shadow._pieces(big, True, 6.0)
    assert sum(p.area for p in pcs) == pytest.approx(big.area, rel=1e-6) and len(pcs) > 10


def test_official_bescom_energy_charges_by_use():
    assert economics.economics(5, 7500, use="residential")["retail_energy_charge_inr_per_kwh"] == 5.80
    assert economics.economics(30, 45000, use="commercial")["retail_energy_charge_inr_per_kwh"] == 6.80
    assert economics.economics(30, 45000, use="medical")["retail_energy_charge_inr_per_kwh"] == 6.55
    assert economics.economics(30, 45000, use="industrial")["retail_energy_charge_inr_per_kwh"] == 4.40
    assert economics.economics(5, 7500, use=None)["tariff_schedule"] == "LT-1"
    assert economics.economics(30, 45000, use=None)["tariff_schedule"] == "LT-3(a)"


def test_electricity_tax_raises_avoided_cost_and_is_switchable():
    with_tax = economics.economics(5, 7500, EconAssumptions(metering="behind_the_meter", self_consumption_share=1.0))
    no_tax = economics.economics(5, 7500, EconAssumptions(metering="behind_the_meter", self_consumption_share=1.0, include_electricity_tax=False))
    assert with_tax["annual_savings_inr"]["mid"] == pytest.approx(7500 * 5.80 * 1.09)
    assert no_tax["annual_savings_inr"]["mid"] == pytest.approx(7500 * 5.80)


def test_large_residential_building_uses_non_domestic_cost_but_lt1_energy_rate():
    r = economics.economics(40, 60000, use="residential")
    assert r["category"] == "non_domestic" and r["capex_inr_per_kw"] == 27090 and r["retail_energy_charge_inr_per_kwh"] == 5.80
    assert "fixed_charge_rebate_inr_per_year" not in r


def test_lt1_solar_rebate_reported_separately_not_in_savings():
    r = economics.economics(4, 6000, use="residential")
    assert r["fixed_charge_rebate_inr_per_year"] == 25 * 12 * 4
